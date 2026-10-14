"""GitHub Trending。

主方案：社区 RSS 镜像（已验证可用；GitHub 官方无 Trending 接口）。
降级：官方 Search API（近 7 天创建、按 star 排序的近似）。
注意：镜像不提供"今日新增 star"精确值，不得虚构；互动维度标注估算。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .base import BaseCollector, RawItem, SourceResult
from .rss_util import rss_collect, valid_url

MIRROR = "https://mshibanami.github.io/GitHubTrendingRSS/daily/all.xml"


class GitHubTrendingCollector(BaseCollector):
    name = "github_trending"
    display_name = "GitHub Trending"

    def collect(self) -> SourceResult:
        try:
            res = rss_collect(self, MIRROR, self.name, category="AI", limit=25)
            res.note = "社区 RSS 镜像（GitHub 官方无 Trending 接口）；无精确日增 star 数据"
            return res
        except Exception as e1:
            try:
                return self._via_search_api()
            except Exception as e2:  # noqa: BLE001
                return SourceResult(
                    source=self.name, ok=False,
                    error=f"RSS 镜像失败：{e1}；官方 Search API 降级也失败：{e2}")

    def _via_search_api(self) -> SourceResult:
        since = (datetime.now(timezone.utc) - timedelta(days=7)).strftime("%Y-%m-%d")
        headers = {}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        resp = self.fetch(
            "https://api.github.com/search/repositories",
            headers=headers,
            params={"q": f"created:>{since}", "sort": "stars",
                    "order": "desc", "per_page": 20},
        )
        items: list[RawItem] = []
        for r in resp.json().get("items", []):
            link = r.get("html_url")
            if not valid_url(link):
                continue
            items.append(RawItem(
                title_orig=(r.get("full_name") or "").strip(),
                url=link, source=self.name,
                published_at=r.get("created_at"),
                category="AI",
                summary_orig=(r.get("description") or "")[:500] or None,
                engagement={"stars": r.get("stargazers_count"),
                            "forks": r.get("forks_count"),
                            "language": r.get("language")},
            ))
        return SourceResult(
            source=self.name, items=items, degraded=True,
            note="RSS 镜像不可用，已降级为官方 Search API（近7天按 star 排序，非严格 Trending）")
