"""TechCrunch：官方 RSS（无认证、免费；须署名+回链，展示时保留原文链接）。

RSS 使用条款：https://techcrunch.com/rss-terms-of-use/
"""
from .base import BaseCollector, SourceResult
from .rss_util import rss_collect


class TechCrunchCollector(BaseCollector):
    name = "techcrunch"
    display_name = "TechCrunch"

    def collect(self) -> SourceResult:
        try:
            res = rss_collect(self, "https://techcrunch.com/feed/",
                              self.name, category="科技", limit=30)
            # 用 RSS 自带的分类微调类别
            return res
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, error=str(e))
