"""采集器包：每个信源一个模块，统一注册到 COLLECTORS。"""
from .base import BaseCollector, RawItem, SourceResult
from .deepmind import DeepMindCollector
from .github_trending import GitHubTrendingCollector
from .google_trends import GoogleTrendsCollector
from .hackernews import HackerNewsCollector
from .hf_blog import HFBlogCollector
from .openai_news import OpenAINewsCollector
from .producthunt import ProductHuntCollector
from .reuters import ReutersCollector
from .sec_edgar import SecEdgarCollector
from .techcrunch import TechCrunchCollector

COLLECTORS: dict[str, BaseCollector] = {}
for _cls in (GitHubTrendingCollector, HackerNewsCollector, ProductHuntCollector,
              OpenAINewsCollector, HFBlogCollector, TechCrunchCollector,
              ReutersCollector, SecEdgarCollector, DeepMindCollector,
              GoogleTrendsCollector):
    _inst = _cls()
    COLLECTORS[_inst.name] = _inst

__all__ = ["BaseCollector", "RawItem", "SourceResult", "COLLECTORS"]
