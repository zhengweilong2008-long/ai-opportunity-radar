"""日报推送（阶段五）。

用法：python scripts/push_report.py [YYYY-MM-DD]
    RADAR_BASE_URL 环境变量指定网站地址（默认 http://127.0.0.1:8000）

流程：拉取 /api/daily-report -> 生成中文日报文本 -> 按配置发送
     （邮件/Telegram，未启用则只打印，供定时任务投递到聊天）。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app import notify


def format_report(d: dict) -> str:
    lines = [f"📡 AI 机会雷达日报（{d['date']}）", ""]
    if d.get("hot_summary"):
        lines += ["📰 " + d["hot_summary"], ""]
    lines.append("🔥 24H 热点 Top10：")
    for i, h in enumerate(d.get("hot", []), 1):
        lines.append(f"{i}. {h['title']}（{h['score']:.0f}分，{h['source']}）")
        lines.append(f"   {h['url']}")
    lines += ["", "💡 本周机会 Top5："]
    for i, o in enumerate(d.get("opportunities", []), 1):
        lines.append(f"{i}. {o['title']}（{o['score']:.0f}分）")
        lines.append(f"   {o['url']}")
    r = d.get("last_run") or {}
    lines += ["",
              f"📊 最近采集：{r.get('started_at')}，状态 {r.get('status')}，"
              f"新增 {r.get('new_items')} 条",
              "",
              "（本消息由定时任务自动生成；详细评分依据见网站）"]
    return "\n".join(lines)


def main() -> int:
    base = os.environ.get("RADAR_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    date = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        resp = httpx.get(f"{base}/api/daily-report",
                         params={"date": date} if date else {},
                         timeout=30.0)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:  # noqa: BLE001
        print(f"拉取日报失败：{e}")
        return 2

    text = format_report(data)
    print(text)  # 始终打印：供 cron/定时任务捕获投递
    print("\n--- 通知渠道 ---")
    results = notify.send_report(f"AI 机会雷达日报 {data['date']}", text)
    for ch, (ok, msg) in results.items():
        print(f"[{'OK' if ok else '--'}] {ch}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
