"""零成本中文翻译：MyMemory 免费 API。

- 匿名：5000 字符/天；提供邮箱（MYMEMORY_EMAIL 环境变量，无需注册）:50000 字符/天
- 每日字符预算持久化到 translation_usage 表，超限自动停用
- 标题优先翻译，摘要用剩余预算
- 任何失败（限流/网络/API 错误）返回 None，调用方保留原文，绝不编造
"""
from __future__ import annotations

import html as _html
import os
import re
import sqlite3
import time
import urllib.parse
from datetime import datetime, timezone

import httpx

from . import db

API_URL = "https://api.mymemory.translated.net/get"
CHUNK_SIZE = 450  # MyMemory 单次请求建议长度
POLITE_DELAY = 0.5  # 请求间隔（秒），避免被限流


def _budget_limit() -> int:
    """每日字符预算：配了邮箱 45000，否则 4500（留安全余量）。"""
    if os.environ.get("MYMEMORY_EMAIL"):
        return 45000
    return 4500


def _today() -> str:
    return db.beijing_today()


def _used_today(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT chars_used FROM translation_usage WHERE date=?", (_today(),)
    ).fetchone()
    return row["chars_used"] if row else 0


def _add_used(conn: sqlite3.Connection, n: int) -> None:
    conn.execute(
        """INSERT INTO translation_usage (date, chars_used) VALUES (?, ?)
           ON CONFLICT(date) DO UPDATE SET chars_used = chars_used + ?""",
        (_today(), n, n),
    )
    conn.commit()


def strip_html(s: str) -> str:
    """去掉 RSS 摘要里的 HTML 标签和实体。"""
    text = re.sub(r"<[^>]+>", " ", s or "")
    text = _html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _chunks(text: str) -> list[str]:
    """按句子边界切成 <=CHUNK_SIZE 的段。"""
    if len(text) <= CHUNK_SIZE:
        return [text]
    parts, buf = [], ""
    for sent in re.split(r"(?<=[.!?。！？])\s*", text):
        if len(buf) + len(sent) > CHUNK_SIZE and buf:
            parts.append(buf)
            buf = ""
        buf += sent
    if buf:
        parts.append(buf)
    return parts or [text[:CHUNK_SIZE]]


def _api_translate(text: str, email: str | None) -> str | None:
    """单次 API 调用，失败返回 None。"""
    params = {"q": text, "langpair": "en|zh-CN"}
    if email:
        params["de"] = email
    url = API_URL + "?" + urllib.parse.urlencode(params)
    try:
        r = httpx.get(url, timeout=20)
        if r.status_code == 429:
            return None  # 限流：降级
        r.raise_for_status()
        data = r.json()
        resp = data.get("responseData", {})
        # 429/配额耗尽时 responseStatus 非 200
        if data.get("responseStatus") != 200:
            return None
        out = (resp.get("translatedText") or "").strip()
        if not out or out.upper() == text.upper():
            return None
        # MyMemory 有时会返回 "MYMEMORY WARNING: YOU USED ALL AVAILABLE FREE TRANSLATIONS"
        if "MYMEMORY WARNING" in out.upper():
            return None
        return out
    except Exception:
        return None


class Translator:
    """带预算的翻译器。同一天内多次实例化共享预算。"""

    def __init__(self) -> None:
        self.email = os.environ.get("MYMEMORY_EMAIL") or None
        self.limit = _budget_limit()
        self.conn = db.get_conn()
        try:
            self.conn.executescript(
                """CREATE TABLE IF NOT EXISTS translation_usage (
                       date TEXT PRIMARY KEY, chars_used INTEGER NOT NULL DEFAULT 0);"""
            )
            self.conn.commit()
        except Exception:
            pass

    def budget_left(self) -> int:
        return max(0, self.limit - _used_today(self.conn))

    def translate(self, text: str | None) -> str | None:
        """翻译一段文本。预算不足或失败返回 None。"""
        text = strip_html(text or "")
        if not text:
            return None
        # 已是中文则跳过（省预算）
        if re.search(r"[\u4e00-\u9fff]", text) and len(re.findall(r"[a-zA-Z]", text)) < len(text) / 3:
            return text
        if len(text) > self.budget_left():
            return None
        out_parts = []
        for ch in _chunks(text):
            if len(ch) > self.budget_left():
                return None if not out_parts else " ".join(out_parts)
            got = _api_translate(ch, self.email)
            time.sleep(POLITE_DELAY)
            if got is None:
                return None if not out_parts else " ".join(out_parts)
            _add_used(self.conn, len(ch))
            out_parts.append(got)
        return " ".join(out_parts).strip() or None

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
