"""Reuters：无合规免费官方接口（robots.txt 明确禁止自动化采集，RSS 需登录）。

合规替代：Google News 官方 RSS 间接覆盖 site:reuters.com 近 24h。
本信源恒为降级状态，网站状态页如实标注"间接覆盖"。
"""
from .base import BaseCollector, SourceResult
from .rss_util import rss_collect

# Google 自有公开 RSS 服务，非逆向接口
GN_REUTERS = ("https://news.google.com/rss/search"
              "?q=site%3Areuters.com+when%3A1d&hl=en-US&gl=US&ceid=US%3Aen")


class ReutersCollector(BaseCollector):
    name = "reuters"
    display_name = "Reuters"

    def collect(self) -> SourceResult:
        try:
            res = rss_collect(self, GN_REUTERS, self.name,
                              category="国际", limit=20)
            res.degraded = True
            res.note = ("Reuters 无合规免费官方接口；经 Google News RSS 间接覆盖 "
                        "site:reuters.com 近 24h（状态页标注'间接覆盖'）")
            return res
        except Exception as e:  # noqa: BLE001
            return SourceResult(
                source=self.name, ok=False,
                error=f"Reuters 无官方接口；Google News 间接覆盖也失败：{e}")
