"""RSS/Atom 通用解析工具：多个信源共用。"""
from __future__ import annotations

import calendar
from datetime import datetime, timezone
from urllib.parse import urlparse

import feedparser

from .base import RawItem, SourceResult


def valid_url(url: str | None) -> bool:
    """基本有效性检查：必须 http/https 且有域名（对应需求第 6 节）。"""
    if not url:
        return False
    try:
        p = urlparse(url.strip())
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def feed_date_iso(entry: dict) -> str | None:
    """feedparser 条目时间 -> UTC ISO；无有效时间返回 None（不编造）。"""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            try:
                return datetime.fromtimestamp(
                    calendar.timegm(st), tz=timezone.utc
                ).isoformat()
            except Exception:
                continue
    return None


def rss_collect(collector, url: str, source: str, category: str,
                limit: int = 30, note: str | None = None) -> SourceResult:
    """拉取 RSS/Atom 并转为 RawItem 列表。异常由调用方 collect() 收敛。"""
    resp = collector.fetch(url)
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise RuntimeError(f"RSS 解析失败：{url}：{feed.bozo_exception}")
    items: list[RawItem] = []
    for e in feed.entries[:limit]:
        link = (e.get("link") or "").strip()
        if not valid_url(link):
            continue
        title = (e.get("title") or "").strip()
        if not title:
            continue
        summary = (e.get("summary") or e.get("description") or "").strip()
        items.append(RawItem(
            title_orig=title,
            url=link,
            source=source,
            published_at=feed_date_iso(e),
            category=category,
            summary_orig=summary[:500] if summary else None,
        ))
    return SourceResult(source=source, items=items,
                        note=note or f"RSS: {url}，取 {len(items)} 条")
