"""Product Hunt：官方 GraphQL v2。

需要用户手动申请免费 Developer Token：
  https://www.producthunt.com/v2/oauth/applications 创建应用后生成，
  填入环境变量 PH_TOKEN。未配置时本信源自动降级跳过（不编造数据）。
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .base import BaseCollector, RawItem, SourceResult
from .rss_util import valid_url

ENDPOINT = "https://api.producthunt.com/v2/api/graphql"
QUERY = """query($after: DateTime, $before: DateTime) {
  posts(first: 20, postedAfter: $after, postedBefore: $before, order: RANKING) {
    edges { node {
      name tagline description votesCount commentsCount website url postedAt
      topics(first: 3) { edges { node { name } } }
    } }
  }
}"""


class ProductHuntCollector(BaseCollector):
    name = "producthunt"
    display_name = "Product Hunt"

    def collect(self) -> SourceResult:
        token = os.environ.get("PH_TOKEN")
        if not token:
            return SourceResult(
                source=self.name, ok=False, degraded=True,
                error="未配置 PH_TOKEN：需用户在 producthunt.com/v2/oauth/applications "
                      "手动创建免费 Developer Token 后填入环境变量；本轮跳过该信源")
        try:
            now = datetime.now(timezone.utc)
            variables = {"after": (now - timedelta(hours=36)).isoformat(),
                         "before": now.isoformat()}
            with self._client({"Authorization": f"Bearer {token}"}) as client:
                resp = client.post(ENDPOINT,
                                   json={"query": QUERY, "variables": variables})
                resp.raise_for_status()
                data = resp.json()
            if data.get("errors"):
                raise RuntimeError(f"GraphQL 错误：{data['errors']}")
            items: list[RawItem] = []
            edges = data["data"]["posts"]["edges"]
            for edge in edges:
                n = edge["node"]
                link = n.get("website") or n.get("url")
                if not valid_url(link):
                    continue
                topics = [t["node"]["name"]
                          for t in (n.get("topics") or {}).get("edges", [])]
                items.append(RawItem(
                    title_orig=f"{n.get('name','')}: {n.get('tagline','')}".strip(": "),
                    url=link, source=self.name,
                    published_at=n.get("postedAt"),
                    category="创业",
                    summary_orig=(n.get("description") or n.get("tagline") or "")[:500] or None,
                    engagement={"votes": n.get("votesCount"),
                                "comments": n.get("commentsCount"),
                                "topics": topics},
                ))
            return SourceResult(
                source=self.name, items=items,
                note=f"官方 GraphQL v2，近 36h 取 {len(items)} 条")
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, error=str(e))
