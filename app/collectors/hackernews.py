"""Hacker News：官方 Firebase API（无认证、免费，专为程序化访问设计）。

字段：title / url / time(Unix秒) / score(真实点赞) / descendants(真实评论数)。
"""
from __future__ import annotations

from datetime import datetime, timezone

from .base import BaseCollector, RawItem, SourceResult
from .rss_util import valid_url

BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsCollector(BaseCollector):
    name = "hackernews"
    display_name = "Hacker News"
    polite_delay = 0.3  # item 请求较多，间隔小一点但保持礼貌

    def collect(self) -> SourceResult:
        try:
            ids = self.fetch(f"{BASE}/topstories.json").json()[:30]
            items: list[RawItem] = []
            for story_id in ids:
                try:
                    it = self.fetch(f"{BASE}/item/{story_id}.json").json()
                except Exception:
                    continue  # 单条失败跳过，不影响其他
                if not it or it.get("type") != "story":
                    continue
                title = (it.get("title") or "").strip()
                link = it.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
                if not title or not valid_url(link):
                    continue
                ts = it.get("time")
                pub = (datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                       if ts else None)
                items.append(RawItem(
                    title_orig=title, url=link, source=self.name,
                    published_at=pub, category="科技",
                    engagement={"score": it.get("score"),
                                "comments": it.get("descendants")},
                ))
            return SourceResult(
                source=self.name, items=items,
                note=f"官方 Firebase API，topstories 取 {len(items)} 条")
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, error=str(e))
