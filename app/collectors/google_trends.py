"""Google Trends：官方 Trending Now RSS（geo=US；geo=CN 不可用）。

注意：
- ht:approx_traffic 只是搜索量档位（500+/5000+），不得当精确数字展示。
- 不使用 pytrends 类逆向接口（违反 Google ToS，且其端点已失效）。
"""
from __future__ import annotations

import feedparser

from .base import BaseCollector, RawItem, SourceResult
from .rss_util import feed_date_iso, valid_url

FEED = "https://trends.google.com/trending/rss?geo=US"


class GoogleTrendsCollector(BaseCollector):
    name = "google_trends"
    display_name = "Google Trends"

    def collect(self) -> SourceResult:
        try:
            resp = self.fetch(FEED)
            feed = feedparser.parse(resp.content)
            items: list[RawItem] = []
            for e in feed.entries[:15]:
                title = (e.get("title") or "").strip()
                if not title:
                    continue
                # feedparser 把重复的 ht:news_item 拍平成单值字段
                # （ht_news_item_url / ht_news_item_title / ht_news_item_source）
                link = (e.get("ht_news_item_url") or "").strip()
                if not valid_url(link):
                    continue  # 无有效原文链接则跳过（不编造链接）
                traffic = e.get("ht_approx_traffic")
                traffic = str(traffic).strip() if traffic else None
                news_title = (e.get("ht_news_item_title") or "").strip()
                items.append(RawItem(
                    title_orig=f"趋势：{title}" + (f"（{news_title}）" if news_title else ""),
                    url=link, source=self.name,
                    published_at=feed_date_iso(e),
                    category="市场",
                    summary_orig=news_title or None,
                    engagement={"approx_traffic": traffic},  # 档位，非精确值
                ))
            res = SourceResult(source=self.name, items=items)
            res.note = ("官方 Trending Now RSS（geo=US）；approx_traffic 为搜索量档位"
                        f"，取 {len(items)} 条")
            return res
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, error=str(e))
