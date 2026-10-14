"""中文翻译流水线（阶段三，零成本）。

用法：python scripts/translate.py  （在 score.py 之后、export_json.py 之前运行）

流程：
1. 取出待发布的 15 条（24H 热点 Top10 + 本周机会 Top5）
2. 标题优先翻译 title_orig -> title_cn
3. 剩余预算翻译 summary_orig（截断 400 字符） -> summary_cn
4. 预算耗尽或 API 失败时保留原文，页面显示"暂无中文摘要"，绝不编造
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import db  # noqa: E402
from app.translator import Translator, strip_html  # noqa: E402

SUMMARY_MAX = 200  # 摘要翻译截断长度（省预算，保证匿名额度内覆盖 15 条）


def main() -> dict:
    db.init_db()
    tr = Translator()
    stats = {"titles_ok": 0, "summaries_ok": 0, "skipped": 0, "failed": 0}
    try:
        day_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        week_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        conn = tr.conn
        hot_ids = [r["id"] for r in conn.execute(
            """SELECT id FROM items WHERE status IN ('hot','opportunity','scored')
               AND collected_at >= ? ORDER BY heat_score DESC LIMIT 10""", (day_cutoff,))]
        opp_ids = [r["id"] for r in conn.execute(
            """SELECT id FROM items WHERE status='opportunity' AND collected_at >= ?
               ORDER BY opp_score DESC LIMIT 5""", (week_cutoff,))]
        target_ids = list(dict.fromkeys(hot_ids + opp_ids))  # 去重保序
        if not target_ids:
            print("没有待翻译的条目")
            return stats

        # 第一遍：标题
        for iid in target_ids:
            row = conn.execute(
                "SELECT id, title_orig, title_cn FROM items WHERE id=?", (iid,)).fetchone()
            if not row or row["title_cn"]:
                stats["skipped"] += 1
                continue
            got = tr.translate(row["title_orig"])
            if got:
                conn.execute("UPDATE items SET title_cn=? WHERE id=?", (got, iid))
                conn.commit()
                stats["titles_ok"] += 1
            else:
                stats["failed"] += 1

        # 第二遍：摘要（用剩余预算）
        for iid in target_ids:
            row = conn.execute(
                "SELECT id, summary_orig, summary_cn FROM items WHERE id=?", (iid,)).fetchone()
            if not row or row["summary_cn"] or not row["summary_orig"]:
                stats["skipped"] += 1
                continue
            src = strip_html(row["summary_orig"])[:SUMMARY_MAX]
            got = tr.translate(src)
            if got:
                conn.execute("UPDATE items SET summary_cn=? WHERE id=?", (got, iid))
                conn.commit()
                stats["summaries_ok"] += 1
            else:
                stats["failed"] += 1
    finally:
        tr.close()
    print(f"翻译完成：标题 {stats['titles_ok']} 条，摘要 {stats['summaries_ok']} 条，"
          f"跳过 {stats['skipped']}，失败/预算不足 {stats['failed']}")
    return stats


if __name__ == "__main__":
    main()
