"""AI 机会雷达 - Web 服务。

阶段一：前端与导航（主页 / 24H 热点 / 本周机会 / 运行状态）。
数据来自 SQLite；采集器（阶段二）未运行前，页面如实展示"暂无数据"，
不编造任何热点或机会条目。

启动：uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import db
from . import llm as _llm
from . import notify as _notify

app = FastAPI(title="AI 机会雷达")
BASE = Path(__file__).resolve().parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")
# 模板里直接用 {{ to_bj(iso) }} 转北京时间
templates.env.globals["to_bj"] = db.to_beijing_display
templates.env.globals["llm_enabled"] = _llm.is_enabled()

db.init_db()

STATUS_LABEL = {
    "pending": "待首次采集",
    "ok": "正常",
    "degraded": "降级",
    "failed": "失败",
}


def _home_stats() -> dict:
    conn = db.get_conn()
    try:
        # 最近一次成功更新（任一信源）
        row = conn.execute(
            "SELECT MAX(last_success_at) AS t FROM sources"
        ).fetchone()
        last_ok = row["t"] if row else None

        # 近 7 天采集成功率 = 成功/部分成功的运行 / 总运行
        week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
        total = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE started_at >= ? AND status != 'running'",
            (week_ago,),
        ).fetchone()["c"]
        good = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE started_at >= ? AND status IN ('success','partial')",
            (week_ago,),
        ).fetchone()["c"]
        success_rate = (good / total) if total else None

        # 今日热点 / 本周机会数量（按北京时间日期划分）
        today = db.beijing_today()
        bj_midnight = datetime.now(db.BEIJING).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        day_cutoff = bj_midnight.astimezone(timezone.utc).isoformat()
        hot_today = conn.execute(
            "SELECT COUNT(*) AS c FROM items WHERE status IN ('hot','opportunity') AND collected_at >= ?",
            (day_cutoff,),
        ).fetchone()["c"]
        opp_week = conn.execute(
            "SELECT COUNT(*) AS c FROM items WHERE status='opportunity' AND collected_at >= ?",
            (week_ago,),
        ).fetchone()["c"]

        sources = [dict(r) for r in conn.execute(
            "SELECT * FROM sources ORDER BY display_name"
        ).fetchall()]
        for s in sources:
            s["status_label"] = STATUS_LABEL.get(s["status"], s["status"])

        # 今日/本周摘要
        rep = conn.execute(
            "SELECT * FROM daily_reports WHERE date=?", (today,)
        ).fetchone()
        hot_summary = rep["hot_summary_cn"] if rep else None
        opp_summary = rep["opp_summary_cn"] if rep else None
    finally:
        conn.close()
    return {
        "last_ok": last_ok,
        "success_rate": success_rate,
        "runs_total": total,
        "hot_today": hot_today,
        "opp_week": opp_week,
        "sources": sources,
        "hot_summary": hot_summary,
        "opp_summary": opp_summary,
        "today": today,
    }


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    return templates.TemplateResponse(
        "index.html", {"request": request, "active": "home", **_home_stats()}
    )


@app.get("/hot", response_class=HTMLResponse)
def hot(
    request: Request,
    hours: int = Query(24, ge=1, le=168),
    category: str = Query(""),
    source: str = Query(""),
):
    """24H 热点：默认最近 24 小时热度前 10，可按时间/类别/来源筛选。"""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    # opportunity 条目同时可能是热点，一并纳入
    conds = ["(status='hot' OR status='scored' OR status='opportunity')", "collected_at >= ?"]
    params: list = [cutoff]
    if category:
        conds.append("category = ?")
        params.append(category)
    if source:
        conds.append("source = ?")
        params.append(source)
    q = f"SELECT * FROM items WHERE {' AND '.join(conds)} ORDER BY heat_score DESC LIMIT 50"
    conn = db.get_conn()
    try:
        items = [dict(r) for r in conn.execute(q, params).fetchall()]
        for it in items:
            it["heat_reasons"] = json.loads(it["heat_reasons"] or "{}")
        cats = [r["category"] for r in conn.execute(
            "SELECT DISTINCT category FROM items WHERE category IS NOT NULL ORDER BY category"
        ).fetchall()]
        srcs = [dict(r) for r in conn.execute(
            "SELECT name, display_name FROM sources ORDER BY display_name"
        ).fetchall()]
    finally:
        conn.close()
    return templates.TemplateResponse("hot.html", {
        "request": request, "active": "hot", "items": items[:10] if hours == 24 and not category and not source else items,
        "is_default": hours == 24 and not category and not source,
        "hours": hours, "category": category, "source": source,
        "categories": cats, "srcs": srcs,
    })


@app.get("/opportunities", response_class=HTMLResponse)
def opportunities(request: Request, opp_type: str = Query("")):
    """本周机会：近 7 天机会按评分排序，默认取前 5。"""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    conds = ["status='opportunity'", "collected_at >= ?"]
    params: list = [week_ago]
    if opp_type:
        conds.append("opp_type = ?")
        params.append(opp_type)
    q = f"SELECT * FROM items WHERE {' AND '.join(conds)} ORDER BY opp_score DESC LIMIT 20"
    conn = db.get_conn()
    try:
        items = [dict(r) for r in conn.execute(q, params).fetchall()]
        for it in items:
            it["opp_reasons"] = json.loads(it["opp_reasons"] or "{}")
    finally:
        conn.close()
    return templates.TemplateResponse("opportunities.html", {
        "request": request, "active": "opportunities",
        "items": items[:5] if not opp_type else items,
        "is_default": not opp_type, "opp_type": opp_type,
    })


@app.get("/status", response_class=HTMLResponse)
def status(request: Request):
    """运行状态：信源状态 + 每次更新的记录（新增/去重/失败来源/错误原因）。"""
    conn = db.get_conn()
    try:
        sources = [dict(r) for r in conn.execute(
            "SELECT * FROM sources ORDER BY display_name"
        ).fetchall()]
        for s in sources:
            s["status_label"] = STATUS_LABEL.get(s["status"], s["status"])
        runs = [dict(r) for r in conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 30"
        ).fetchall()]
        for r in runs:
            r["failed_sources"] = json.loads(r["failed_sources"] or "[]")
            r["errors"] = json.loads(r["errors"] or "{}")
    finally:
        conn.close()
    # 日志文件（最新的 5 个）
    log_dir = BASE.parent / "logs"
    log_files = []
    if log_dir.exists():
        for p in sorted(log_dir.glob("daily-*.log"), reverse=True)[:5]:
            log_files.append({"name": p.name,
                              "size": f"{p.stat().st_size // 1024} KB"})
    return templates.TemplateResponse(
        "status.html", {"request": request, "active": "status",
                        "sources": sources, "runs": runs,
                        "notify": _notify.status(),
                        "llm": _llm.usage_report(),
                        "log_files": log_files}
    )


@app.post("/api/refresh")
def api_refresh():
    """手动刷新：阶段二实现采集器后接真实采集。现在如实返回未实现。"""
    return JSONResponse(
        status_code=501,
        content={"status": "not_implemented",
                 "message": "采集模块将在阶段二实现，当前版本暂不支持手动刷新。"},
    )


@app.get("/api/daily-report")
def api_daily_report(date: str = ""):
    """日报 JSON 接口：供定时推送任务读取（阶段五）。

    返回指定日期（北京时间 YYYY-MM-DD，默认今天）的热点 Top10、
    机会 Top5、采集统计。不含敏感信息，可供外部定时任务拉取。
    """
    day = date or db.beijing_today()
    conn = db.get_conn()
    try:
        rep = conn.execute(
            "SELECT * FROM daily_reports WHERE date=?", (day,)).fetchone()
        hot = [dict(r) for r in conn.execute(
            """SELECT id, title_cn, title_orig, url, source, heat_score,
                      confidence, published_at FROM items
               WHERE status IN ('hot','opportunity')
                 AND collected_at >= datetime('now','-1 day')
               ORDER BY heat_score DESC LIMIT 10""").fetchall()]
        opp = [dict(r) for r in conn.execute(
            """SELECT id, title_cn, title_orig, url, source, opp_score,
                      opp_type, published_at FROM items
               WHERE status='opportunity'
                 AND collected_at >= datetime('now','-7 days')
               ORDER BY opp_score DESC LIMIT 5""").fetchall()]
        run = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()

    def _brief(it: dict) -> dict:
        return {
            "title": it["title_cn"] or it["title_orig"],
            "url": it["url"], "source": it["source"],
            "score": it.get("heat_score") or it.get("opp_score"),
            "published_at": db.to_beijing_display(it.get("published_at")),
        }

    return {
        "date": day,
        "hot_summary": rep["hot_summary_cn"] if rep else None,
        "opp_summary": rep["opp_summary_cn"] if rep else None,
        "hot": [_brief(h) for h in hot],
        "opportunities": [_brief(o) for o in opp],
        "last_run": {
            "started_at": db.to_beijing_display(run["started_at"]) if run else None,
            "status": run["status"] if run else None,
            "new_items": run["new_items"] if run else 0,
        },
    }
