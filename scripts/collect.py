"""每日采集入口。

用法：python scripts/collect.py
阶段四由系统 cron 在每天 08:00（北京时间）调用。

流程：逐个运行十个信源采集器 -> 入库（URL 去重）->
     更新信源状态 -> 记录本次运行（新增/去重/失败来源/错误原因）。
单个信源失败不影响其他信源。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.collectors import COLLECTORS


def main() -> dict:
    db.init_db()
    run_id = db.start_run()
    total_new, total_dedup = 0, 0
    failed: list[str] = []
    errors: dict[str, str] = {}
    notes: list[str] = []

    for name, collector in COLLECTORS.items():
        try:
            res = collector.collect()
        except Exception as e:  # noqa: BLE001 - 采集器自身也可能抛未捕获异常
            res = None
            err = f"采集器未捕获异常：{e}"
            failed.append(name)
            errors[name] = err
            db.update_source(name, "failed", error=err)
            print(f"[FAIL] {name}: {err}", flush=True)
            continue

        if res.ok:
            n, d = db.save_items([{
                "title_orig": it.title_orig, "url": it.url, "source": it.source,
                "published_at": it.published_at, "category": it.category,
                "summary_orig": it.summary_orig, "engagement": it.engagement,
            } for it in res.items])
            total_new += n
            total_dedup += d
            status = "degraded" if res.degraded else "ok"
            db.update_source(name, status, items_collected=n,
                             error=None if res.ok else res.error)
            if res.degraded:
                # 降级但仍产出数据：不计入失败来源，note 记入运行备注以便追溯
                notes.append(f"{name}[降级]: {res.note or res.error}")
            print(f"[{'WARN' if res.degraded else 'OK'}] {name}: 新增 {n} 条，"
                  f"去重 {d} 条。{res.note or ''}", flush=True)
        else:
            failed.append(name)
            errors[name] = res.error or "未知错误"
            db.update_source(name, "failed", error=res.error)
            print(f"[FAIL] {name}: {res.error}", flush=True)
        if res and res.note:
            notes.append(f"{name}: {res.note}")

    ok_count = len(COLLECTORS) - len(failed)
    if ok_count == len(COLLECTORS):
        run_status = "success"
    elif ok_count > 0:
        run_status = "partial"
    else:
        run_status = "failed"
    db.finish_run(run_id, run_status, total_new, total_dedup,
                  failed, errors,
                  note="；".join(notes) if notes else None)

    summary = {"run_id": run_id, "status": run_status,
               "new_items": total_new, "deduped": total_dedup,
               "failed_sources": failed, "errors": errors}
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


if __name__ == "__main__":
    result = main()
    # 退出码语义（供 daily.py 判断）：0=成功/部分成功（有数据），2=彻底失败
    sys.exit(2 if result["status"] == "failed" else 0)
