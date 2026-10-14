"""数据库层：SQLite。

约定（对应需求第 6 节"时间与数据规则"）：
- 库里所有时间统一存 UTC 的 ISO 字符串。
- 展示时一律转北京时间（Asia/Shanghai）。
- 没有核实的发布时间保持 NULL，展示为"时间未核实"，绝不编造精确时间。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "radar.db"
BEIJING = ZoneInfo("Asia/Shanghai")

# 十个信源：阶段二逐个实现采集器
SOURCES = [
    ("github_trending", "GitHub Trending", "https://github.com/trending"),
    ("hackernews", "Hacker News", "https://news.ycombinator.com/"),
    ("producthunt", "Product Hunt", "https://www.producthunt.com/"),
    ("openai_news", "OpenAI News", "https://openai.com/news/"),
    ("hf_blog", "Hugging Face Blog", "https://huggingface.co/blog"),
    ("techcrunch", "TechCrunch", "https://techcrunch.com/"),
    ("reuters", "Reuters", "https://www.reuters.com/"),
    ("sec_edgar", "SEC EDGAR", "https://www.sec.gov/edgar/search/"),
    ("deepmind", "Google DeepMind", "https://deepmind.google/"),
    ("google_trends", "Google Trends", "https://trends.google.com/trends/"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    name TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending/ok/degraded/failed
    last_run_at TEXT,                        -- UTC ISO
    last_success_at TEXT,                    -- UTC ISO
    items_collected INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title_orig TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    published_at TEXT,          -- UTC ISO；未核实则为 NULL
    collected_at TEXT NOT NULL, -- UTC ISO
    category TEXT,              -- AI/创业/投资/科技/政策/市场
    title_cn TEXT,
    summary_cn TEXT,
    summary_orig TEXT,          -- 英文原文摘要（RSS 描述，阶段三新增）
    engagement TEXT,            -- JSON：真实互动数据（有才填，无则为 NULL）
    heat_score REAL,            -- 0-100
    heat_reasons TEXT,          -- JSON：各项得分明细
    confidence TEXT NOT NULL DEFAULT '数据不足',  -- 实际热度/估算热度/数据不足
    opp_score REAL,             -- 0-100
    opp_reasons TEXT,           -- JSON
    opp_type TEXT,              -- AI/创业/投资
    cost_range TEXT,            -- 预估启动成本区间
    monetization TEXT,          -- 变现路径
    mvp_plan TEXT,              -- 最小可行验证方案
    risks TEXT,                 -- 主要风险
    next_action TEXT,           -- 建议下一步行动
    status TEXT NOT NULL DEFAULT 'raw'  -- raw/scored/hot/opportunity/invest_watch
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,   -- UTC ISO
    finished_at TEXT,           -- UTC ISO
    status TEXT NOT NULL,       -- running/success/partial/failed
    new_items INTEGER NOT NULL DEFAULT 0,
    deduped_count INTEGER NOT NULL DEFAULT 0,
    failed_sources TEXT,        -- JSON 数组
    errors TEXT,                -- JSON
    note TEXT
);
CREATE TABLE IF NOT EXISTS daily_reports (
    date TEXT PRIMARY KEY,      -- YYYY-MM-DD（北京时间日期）
    hot_summary_cn TEXT,
    opp_summary_cn TEXT,
    created_at TEXT NOT NULL    -- UTC ISO
);
CREATE TABLE IF NOT EXISTS llm_usage (
    date TEXT PRIMARY KEY,      -- YYYY-MM-DD（北京时间日期）
    calls INTEGER NOT NULL DEFAULT 0,
    cost_cny_est REAL NOT NULL DEFAULT 0
);
"""


def get_conn() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """建表 + 预置十个信源（幂等，可重复执行）。"""
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        for name, display, url in SOURCES:
            conn.execute(
                "INSERT OR IGNORE INTO sources (name, display_name, url) VALUES (?, ?, ?)",
                (name, display, url),
            )
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """轻量迁移：给已存在的表补上新增列（初学者友好的简单方案）。"""
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(items)").fetchall()}
    if "engagement" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN engagement TEXT")
    if "summary_orig" not in cols:
        conn.execute("ALTER TABLE items ADD COLUMN summary_orig TEXT")
        # 回填：旧版本把英文摘要误存入 summary_cn，搬回 summary_orig。
        # title_cn 从未被填充过（LLM 默认关闭），所以 summary_cn 里全是英文，可安全搬移。
        conn.execute(
            """UPDATE items SET summary_orig = summary_cn, summary_cn = NULL
               WHERE summary_cn IS NOT NULL AND title_cn IS NULL"""
        )


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def to_beijing_display(iso_str: str | None) -> str:
    """UTC ISO -> 北京时间 'YYYY-MM-DD HH:MM'；缺失/非法返回'时间未核实'。"""
    if not iso_str:
        return "时间未核实"
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(BEIJING).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return "时间未核实"


def beijing_today() -> str:
    return datetime.now(BEIJING).strftime("%Y-%m-%d")


# ---- 采集运行记录（阶段二/四使用）----

def start_run() -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            (utcnow_iso(),),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def finish_run(run_id: int, status: str, new_items: int, deduped: int,
               failed_sources: list, errors: dict, note: str | None = None) -> None:
    import json as _json
    conn = get_conn()
    try:
        conn.execute(
            """UPDATE runs SET finished_at=?, status=?, new_items=?, deduped_count=?,
               failed_sources=?, errors=?, note=? WHERE id=?""",
            (utcnow_iso(), status, new_items, deduped,
             _json.dumps(failed_sources, ensure_ascii=False),
             _json.dumps(errors, ensure_ascii=False), note, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def update_source(name: str, status: str, items_collected: int = 0,
                  error: str | None = None) -> None:
    """更新信源状态；status 成功时同步 last_success_at。"""
    conn = get_conn()
    try:
        if status == "ok":
            conn.execute(
                """UPDATE sources SET status=?, last_run_at=?, last_success_at=?,
                   items_collected=items_collected + ?, last_error=? WHERE name=?""",
                (status, utcnow_iso(), utcnow_iso(), items_collected, error, name),
            )
        else:
            conn.execute(
                "UPDATE sources SET status=?, last_run_at=?, last_error=? WHERE name=?",
                (status, utcnow_iso(), error, name),
            )
        conn.commit()
    finally:
        conn.close()


def save_items(items: list[dict]) -> tuple[int, int]:
    """保存原始条目，按 URL 去重。返回 (新增数, 去重跳过数)。"""
    import json as _json
    new_count, deduped = 0, 0
    conn = get_conn()
    try:
        for it in items:
            try:
                conn.execute(
                    """INSERT INTO items
                       (title_orig, url, source, published_at, collected_at, category,
                        summary_orig, engagement, status)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'raw')""",
                    (it["title_orig"], it["url"], it["source"],
                     it.get("published_at"), utcnow_iso(),
                     it.get("category"), it.get("summary_orig"),
                     _json.dumps(it.get("engagement") or {}, ensure_ascii=False)
                     if it.get("engagement") else None),
                )
                new_count += 1
            except Exception:  # URL 唯一冲突等 -> 计为去重
                deduped += 1
        conn.commit()
    finally:
        conn.close()
    return new_count, deduped
