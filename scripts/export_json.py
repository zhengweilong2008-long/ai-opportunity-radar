"""导出静态网站所需数据：SQLite -> data/site-data.json。

静态站（GitHub Pages）没有数据库，构建时只读这一个 JSON 文件。
每天的数据文件会提交到仓库，天然保留历史。
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from app import db  # noqa: E402

DATA_JSON = BASE / "data" / "site-data.json"


def _item_brief(row: dict, score_key: str, reasons_key: str) -> dict:
    reasons = {}
    try:
        reasons = json.loads(row.get(reasons_key) or "{}")
    except (json.JSONDecodeError, TypeError):
        pass
    return {
        "title_cn": row.get("title_cn"),
        "title_orig": row.get("title_orig"),
        "summary_cn": row.get("summary_cn"),
        "url": row.get("url"),
        "source": row.get("source"),
        "source_display": _source_display(row.get("source")),
        "category": row.get("category"),
        "published_at": db.to_beijing_display(row.get("published_at")),
        "score": row.get(score_key),
        "confidence": row.get("confidence"),
        "reasons": {k: v for k, v in reasons.items() if not k.startswith("_")},
        "note": reasons.get("_说明"),
        "opp_type": row.get("opp_type"),
        "cost_range": row.get("cost_range"),
        "monetization": row.get("monetization"),
        "mvp_plan": row.get("mvp_plan"),
        "risks": row.get("risks"),
        "next_action": row.get("next_action"),
    }


def _source_display(name: str | None) -> str:
    mapping = {n: d for n, d, _ in db.SOURCES}
    return mapping.get(name or "", name or "未知来源")


def export(out: Path = DATA_JSON) -> dict:
    """从 SQLite 导出热点 Top10、机会 Top5、统计信息，写入 JSON。"""
    conn = db.get_conn()
    try:
        day_cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        week_cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        hot_rows = conn.execute(
            """SELECT * FROM items
               WHERE status IN ('hot','opportunity','scored') AND collected_at >= ?
               ORDER BY heat_score DESC LIMIT 10""",
            (day_cutoff,),
        ).fetchall()
        opp_rows = conn.execute(
            """SELECT * FROM items
               WHERE status='opportunity' AND collected_at >= ?
               ORDER BY opp_score DESC LIMIT 5""",
            (week_cutoff,),
        ).fetchall()

        # 首页统计
        srow = conn.execute("SELECT MAX(last_success_at) AS t FROM sources").fetchone()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE status != 'running'").fetchone()["c"]
        good = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE status IN ('success','partial')").fetchone()["c"]
        sources = [dict(r) for r in conn.execute(
            "SELECT name, display_name, url, status, last_success_at, items_collected,"
            " last_error FROM sources ORDER BY display_name").fetchall()]
        runs = [dict(r) for r in conn.execute(
            "SELECT started_at, status, new_items, deduped_count, failed_sources"
            " FROM runs ORDER BY id DESC LIMIT 10").fetchall()]
        for r in runs:
            r["started_at"] = db.to_beijing_display(r["started_at"])
            try:
                r["failed_sources"] = json.loads(r["failed_sources"] or "[]")
            except (json.JSONDecodeError, TypeError):
                r["failed_sources"] = []
    finally:
        conn.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": db.beijing_today(),
        "hot": [_item_brief(dict(r), "heat_score", "heat_reasons") for r in hot_rows],
        "opportunities": [_item_brief(dict(r), "opp_score", "opp_reasons") for r in opp_rows],
        "stats": {
            "last_ok": db.to_beijing_display(srow["t"]) if srow and srow["t"] else None,
            "success_rate": (good / total) if total else None,
            "runs_total": total,
            "hot_count": len(hot_rows),
            "opp_count": len(opp_rows),
        },
        "sources": sources,
        "runs": runs,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


if __name__ == "__main__":
    p = export()
    print(f"已导出 {DATA_JSON}：热点 {len(p['hot'])} 条，机会 {len(p['opportunities'])} 条")
