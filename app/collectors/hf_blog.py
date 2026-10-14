"""Hugging Face Blog：官方 RSS（无认证、免费）。无互动数据字段。"""
from .base import BaseCollector, SourceResult
from .rss_util import rss_collect


class HFBlogCollector(BaseCollector):
    name = "hf_blog"
    display_name = "Hugging Face Blog"

    def collect(self) -> SourceResult:
        try:
            return rss_collect(self, "https://huggingface.co/blog/feed.xml",
                               self.name, category="AI", limit=20)
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, error=str(e))
