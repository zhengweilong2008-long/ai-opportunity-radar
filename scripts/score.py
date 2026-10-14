"""评分流水线（阶段三）。

用法：python scripts/score.py   （通常在 collect.py 之后运行；
     阶段四由 scripts/daily.py 统一编排。）

流程：
1. 取近 72h 的 raw 条目，做跨信源事件去重（同事件只留热度最高者）。
2. 热度评分（100 分制）-> status='scored'；近 24h 热度 Top10 -> 'hot'。
3. 机会评分（100 分制）/ 投资观察评分 -> 近 7 天 Top5 -> 'opportunity'。
4. 中文标题摘要：LLM 未启用时保留原文（不编造翻译）。
5. 生成今日中文摘要，写入 daily_reports。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, llm
from app.scoring import (classify_category, cluster_events, score_heat,
                         score_investment, score_opportunity)


def _rows(sql: str, params: tuple = ()) -> list[dict]:
    conn = db.get_conn()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _exec(sql: str, params: tuple = ()) -> None:
    conn = db.get_conn()
    try:
        conn.execute(sql, params)
        conn.commit()
    finally:
        conn.close()


def main() -> dict:
    db.init_db()
    now = datetime.now(timezone.utc)
    cutoff_72h = (now - timedelta(hours=72)).isoformat()
    cutoff_24h = (now - timedelta(hours=24)).isoformat()
    cutoff_7d = (now - timedelta(days=7)).isoformat()

    stats = {"clustered": 0, "dup_event": 0, "scored": 0,
             "hot": 0, "opportunities": 0, "translated": 0}

    # ---- 1. 跨信源事件去重 ----
    raws = _rows("SELECT * FROM items WHERE status='raw' AND collected_at >= ?",
                 (cutoff_72h,))
    if raws:
        clusters = cluster_events(raws)
        members: dict[int, list[dict]] = {}
        for it in raws:
            members.setdefault(clusters[it["id"]], []).append(it)
        for cid, ms in members.items():
            if len(ms) < 2:
                continue
            # 同事件只留"标题最长者"为候选（先占位，热度评分后按分数定正选）
            ms_sorted = sorted(ms, key=lambda x: len(x.get("title_orig") or ""),
                               reverse=True)
            for dup in ms_sorted[1:]:
                _exec("UPDATE items SET status='dup_event' WHERE id=?",
                      (dup["id"],))
                stats["dup_event"] += 1
        stats["clustered"] = len([m for m in members.values() if len(m) > 1])

    # ---- 2. 热度评分 ----
    candidates = _rows(
        "SELECT * FROM items WHERE status IN ('raw','scored') AND collected_at >= ?",
        (cutoff_72h,))
    # 簇内独立信源数
    raws2 = _rows("SELECT id, title_orig FROM items WHERE collected_at >= ? "
                  "AND status != 'dup_event'", (cutoff_72h,))
    clusters2 = cluster_events(raws2)
    cluster_srcs: dict[int, set] = {}
    src_of = {r["id"]: r for r in _rows(
        "SELECT id, source FROM items WHERE collected_at >= ?", (cutoff_72h,))}
    for iid, cid in clusters2.items():
        cluster_srcs.setdefault(cid, set()).add(src_of.get(iid, {}).get("source"))

    for it in candidates:
        cid = clusters2.get(it["id"], it["id"])
        n_src = len(cluster_srcs.get(cid, {it["source"]}))
        heat, reasons, conf = score_heat(it, n_src)
        cat = classify_category(it.get("title_orig") or "",
                                it.get("summary_cn"), it.get("source") or "")
        _exec("""UPDATE items SET heat_score=?, heat_reasons=?, confidence=?,
                 category=?, status='scored' WHERE id=?""",
              (heat, json.dumps(reasons, ensure_ascii=False), conf, cat, it["id"]))
        stats["scored"] += 1

    # ---- 3. 24H 热点 Top10（按发布时间，缺失则按采集时间） ----
    _exec("UPDATE items SET status='scored' WHERE status='hot'")
    hot_candidates = _rows(
        """SELECT * FROM items WHERE status='scored' AND heat_score IS NOT NULL
           AND (published_at >= ? OR (published_at IS NULL AND collected_at >= ?))
           ORDER BY heat_score DESC LIMIT 10""",
        (cutoff_24h, cutoff_24h))
    for it in hot_candidates:
        _exec("UPDATE items SET status='hot' WHERE id=?", (it["id"],))
    stats["hot"] = len(hot_candidates)

    # ---- 4. 机会评分 / 投资观察 ----
    _exec("UPDATE items SET status='scored' WHERE status='opportunity'")
    opp_candidates = _rows(
        """SELECT * FROM items WHERE status IN ('scored','hot')
           AND collected_at >= ? AND heat_score IS NOT NULL""",
        (cutoff_7d,))
    scored_list = []
    for it in opp_candidates:
        if it["source"] == "sec_edgar":
            total, reasons, conf = score_investment(it)
            fields = {"opp_type": "投资",
                      "cost_range": "不适用（投资观察非创业机会）",
                      "monetization": "不适用",
                      "mvp_plan": "不适用",
                      "risks": ("缺乏可靠股价与财务数据，无法评估估值；"
                                "8-K 仅为事件信号，不构成买入建议。"),
                      "next_action": "阅读申报原文 → 查询公司最新财报与股价（需外部数据源）→ 自行判断。",
                      "_note": "投资观察独立评分；数据不足已标注"}
        else:
            total, reasons, fields = score_opportunity(it, it["heat_score"] or 0)
            conf = "估算热度"
        scored_list.append((total, it, reasons, fields, conf))

    scored_list.sort(key=lambda x: x[0], reverse=True)
    top5 = scored_list[:5]
    for total, it, reasons, fields, conf in top5:
        _exec("""UPDATE items SET opp_score=?, opp_reasons=?, opp_type=?,
                 cost_range=?, monetization=?, mvp_plan=?, risks=?,
                 next_action=?, status='opportunity' WHERE id=?""",
              (total, json.dumps(reasons, ensure_ascii=False),
               fields.get("opp_type"), fields.get("cost_range"),
               fields.get("monetization"), fields.get("mvp_plan"),
               fields.get("risks"), fields.get("next_action"), it["id"]))
    stats["opportunities"] = len(top5)

    # ---- 5. 中文翻译（LLM 未启用则跳过，保留原文） ----
    hot_now = _rows("SELECT * FROM items WHERE status='hot'")
    opp_now = _rows("SELECT * FROM items WHERE status='opportunity'")
    to_translate = [{"id": it["id"], "title": it["title_orig"],
                     "summary": it.get("summary_cn")}
                    for it in hot_now + opp_now if not it.get("title_cn")]
    if to_translate:
        zh = llm.zh_translate(to_translate)
        for eid, t in zh.items():
            _exec("UPDATE items SET title_cn=?, summary_cn=? WHERE id=?",
                  (t["title_cn"], t["summary_cn"], eid))
            stats["translated"] += 1

    # ---- 6. 今日摘要 ----
    hot_now = _rows("SELECT * FROM items WHERE status='hot' ORDER BY heat_score DESC")
    opp_now = _rows("SELECT * FROM items WHERE status='opportunity' ORDER BY opp_score DESC")
    titles = "、".join((it["title_cn"] or it["title_orig"])[:24] for it in hot_now[:3])
    hot_summary = (f"今日共采集入库 {len(candidates)} 条参与评分，"
                   f"产生 {len(hot_now)} 条 24H 热点。热度前三：{titles}。"
                   f"（{db.beijing_today()} 北京时间；规则评分，无大模型参与时标题为原文）")
    o_titles = "、".join((it["title_cn"] or it["title_orig"])[:24] for it in opp_now[:3])
    opp_summary = (f"本周从近 7 天内容中提炼 {len(opp_now)} 条机会：{o_titles}。"
                   "均为规则评分初筛，变现路径与收入未经证实，不构成投资建议。")
    conn = db.get_conn()
    try:
        conn.execute(
            """INSERT INTO daily_reports (date, hot_summary_cn, opp_summary_cn, created_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(date) DO UPDATE SET hot_summary_cn=excluded.hot_summary_cn,
                 opp_summary_cn=excluded.opp_summary_cn""",
            (db.beijing_today(), hot_summary, opp_summary, db.utcnow_iso()))
        conn.commit()
    finally:
        conn.close()

    print(json.dumps({"status": "ok", **stats}, ensure_ascii=False, indent=2))
    return stats


if __name__ == "__main__":
    main()
