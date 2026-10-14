"""可配置的大模型接口：中文翻译与摘要。

默认关闭（LLM_ENABLED=false），零费用。开启后：
- 每日调用量限制（LLM_DAILY_CALL_LIMIT，默认 60）
- 每月费用预算（MONTHLY_BUDGET_CNY，默认 20 元），超限自动停用
- 任何失败自动降级为原文展示，不中断主流程

支持 OpenAI 兼容接口：
- deepseek:    LLM_PROVIDER=deepseek     (https://api.deepseek.com)
- siliconflow: LLM_PROVIDER=siliconflow  (https://api.siliconflow.cn/v1)
- 自定义:      LLM_PROVIDER=custom + LLM_BASE_URL
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import httpx

from . import db

PROVIDER_BASE = {
    "deepseek": "https://api.deepseek.com",
    "siliconflow": "https://api.siliconflow.cn/v1",
}

# 保守的费用估算（元/千 tokens），宁可高估
COST_PER_1K = {
    "deepseek": {"input": 0.001, "output": 0.002},
    "siliconflow": {"input": 0.001, "output": 0.002},
    "custom": {"input": 0.002, "output": 0.004},
}


def is_enabled() -> bool:
    return os.environ.get("LLM_ENABLED", "false").lower() == "true"


def _config() -> dict | None:
    if not is_enabled():
        return None
    api_key = os.environ.get("LLM_API_KEY")
    if not api_key:
        return None
    provider = os.environ.get("LLM_PROVIDER", "deepseek")
    base = PROVIDER_BASE.get(provider, os.environ.get("LLM_BASE_URL", ""))
    if not base:
        return None
    return {
        "api_key": api_key,
        "base": base.rstrip("/"),
        "model": os.environ.get("LLM_MODEL", "deepseek-chat"),
        "provider": provider if provider in COST_PER_1K else "custom",
        "daily_limit": int(os.environ.get("LLM_DAILY_CALL_LIMIT", "60")),
        "monthly_budget": float(os.environ.get("MONTHLY_BUDGET_CNY", "20")),
    }


def _usage_today() -> dict:
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM llm_usage WHERE date=?", (db.beijing_today(),)).fetchone()
        return dict(row) if row else {"calls": 0, "cost_cny_est": 0.0}
    finally:
        conn.close()


def _usage_month() -> float:
    month = db.beijing_today()[:7]
    conn = db.get_conn()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(cost_cny_est),0) AS c FROM llm_usage "
            "WHERE date LIKE ?", (month + "%",)).fetchone()
        return float(row["c"])
    finally:
        conn.close()


def _record_usage(calls: int, in_chars: int, out_chars: int, provider: str) -> None:
    # 粗略估算：英文约 4 字符/token，中文约 2 字符/token，取保守值
    in_tok = in_chars / 3
    out_tok = out_chars / 2
    rate = COST_PER_1K.get(provider, COST_PER_1K["custom"])
    cost = in_tok / 1000 * rate["input"] + out_tok / 1000 * rate["output"]
    conn = db.get_conn()
    try:
        conn.execute(
            """INSERT INTO llm_usage (date, calls, cost_cny_est)
               VALUES (?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET
                 calls = calls + excluded.calls,
                 cost_cny_est = cost_cny_est + excluded.cost_cny_est""",
            (db.beijing_today(), calls, round(cost, 4)),
        )
        conn.commit()
    finally:
        conn.close()


def budget_allows(cfg: dict) -> tuple[bool, str]:
    """检查每日调用量与每月预算。"""
    u = _usage_today()
    if u["calls"] >= cfg["daily_limit"]:
        return False, f"已达每日调用上限（{cfg['daily_limit']} 次）"
    if _usage_month() >= cfg["monthly_budget"]:
        return False, f"已达每月预算（{cfg['monthly_budget']} 元）"
    return True, ""


def zh_translate(items: list[dict]) -> dict[int, dict]:
    """批量翻译：[{id, title, summary}] -> {id: {title_cn, summary_cn}}。

    未启用/无 key/超限/失败 -> 返回 {}，调用方保留原文展示。
    """
    cfg = _config()
    if not cfg:
        return {}
    ok, reason = budget_allows(cfg)
    if not ok:
        print(f"[LLM] 跳过翻译：{reason}")
        return {}

    results: dict[int, dict] = {}
    batch_size = 5
    try:
        with httpx.Client(timeout=60.0) as client:
            for i in range(0, len(items), batch_size):
                batch = items[i:i + batch_size]
                ok_b, _ = budget_allows(cfg)
                if not ok_b:
                    print("[LLM] 达到上限，停止本轮翻译")
                    break
                prompt_items = "\n".join(
                    f"[{b['id']}] 标题：{b['title']}\n摘要：{b.get('summary') or '无'}"
                    for b in batch)
                messages = [{
                    "role": "user",
                    "content": (
                        "你是中文科技编辑。把下面每条英文科技资讯翻译成："
                        "中文标题（一句话，不超过25字）+ 一句中文摘要（不超过60字）。"
                        "只翻译转述，不要编造原文没有的信息。\n"
                        "严格返回 JSON 数组，顺序与输入一致："
                        '[{"id": 数字, "title_cn": "...", "summary_cn": "..."}]\n\n'
                        + prompt_items),
                }]
                resp = client.post(
                    f"{cfg['base']}/chat/completions",
                    headers={"Authorization": f"Bearer {cfg['api_key']}"},
                    json={"model": cfg["model"], "messages": messages,
                          "temperature": 0.3, "response_format": {"type": "json_object"}},
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                # 兼容返回 {"items": [...]} 或直接 [...]
                parsed = json.loads(content)
                arr = parsed if isinstance(parsed, list) else parsed.get("items", parsed.get("data", []))
                in_chars = sum(len(b["title"]) + len(b.get("summary") or "") for b in batch)
                for entry in arr:
                    eid = entry.get("id")
                    if eid in {b["id"] for b in batch}:
                        results[eid] = {
                            "title_cn": (entry.get("title_cn") or "").strip() or None,
                            "summary_cn": (entry.get("summary_cn") or "").strip() or None,
                        }
                _record_usage(1, len(prompt_items) + 300, len(content), cfg["provider"])
    except Exception as e:  # noqa: BLE001 - 翻译失败整体降级
        print(f"[LLM] 翻译失败，降级为原文展示：{e}")
        return results  # 返回已成功部分
    return results


def usage_report() -> dict:
    """费用与用量报告（网站状态页/部署文档用）。"""
    u = _usage_today()
    return {"enabled": is_enabled(), "today_calls": u["calls"],
            "today_cost_est": round(u["cost_cny_est"], 4),
            "month_cost_est": round(_usage_month(), 4),
            "month_budget": float(os.environ.get("MONTHLY_BUDGET_CNY", "20")),
            "as_of": datetime.now().isoformat()}
