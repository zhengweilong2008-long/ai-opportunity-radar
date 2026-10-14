"""阶段二测试：采集器契约（不依赖外网，用 fixture 验证解析/校验逻辑）。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db
from app.collectors import COLLECTORS, BaseCollector
from app.collectors.base import RawItem, SourceResult
from app.collectors.rss_util import feed_date_iso, rss_collect, valid_url


def test_all_ten_registered():
    expected = {"github_trending", "hackernews", "producthunt", "openai_news",
                "hf_blog", "techcrunch", "reuters", "sec_edgar",
                "deepmind", "google_trends"}
    assert set(COLLECTORS.keys()) == expected, set(COLLECTORS.keys())


def test_valid_url():
    assert valid_url("https://example.com/a")
    assert valid_url("http://example.com/")
    assert not valid_url("")
    assert not valid_url(None)
    assert not valid_url("javascript:alert(1)")
    assert not valid_url("ftp://example.com/x")
    assert not valid_url("not a url")


def test_feed_date_iso():
    # RFC822 -> UTC ISO
    entry = {"published_parsed": time.strptime("Wed, 14 Oct 2026 11:00:00 +0000",
                                               "%a, %d %b %Y %H:%M:%S %z")}
    iso = feed_date_iso(entry)
    assert iso.startswith("2026-10-14T11:00:00+00:00"), iso
    # 无时间 -> None（不编造）
    assert feed_date_iso({}) is None


def test_rss_collect_parses_real_feed():
    """用一段真实 RSS 文本验证解析（离线）。"""
    xml = """<?xml version="1.0"?><rss version="2.0"><channel>
    <title>T</title>
    <item><title>Hello</title><link>https://example.com/1</link>
    <pubDate>Wed, 14 Oct 2026 11:00:00 +0000</pubDate>
    <description>desc</description></item>
    <item><title>Bad link</title><link>javascript:x</link></item>
    <item><title></title><link>https://example.com/3</link></item>
    </channel></rss>"""

    class FakeCollector(BaseCollector):
        name = "fake"

        def fetch(self, url, **kw):
            class R:
                content = xml.encode()
            return R()

    res = rss_collect(FakeCollector(), "https://example.com/feed", "fake", "AI")
    assert res.ok and len(res.items) == 1
    it = res.items[0]
    assert it.title_orig == "Hello"
    assert it.url == "https://example.com/1"
    assert it.published_at.startswith("2026-10-14T11:00:00")


def test_source_result_failure_shape():
    r = SourceResult(source="x", ok=False, error="boom")
    assert r.items == [] and r.error == "boom"


def test_save_items_dedups_by_url():
    db.init_db()
    items = [{"title_orig": "t", "url": "https://example.com/dedup-test",
              "source": "hackernews"}]
    n1, d1 = db.save_items(items)
    n2, d2 = db.save_items(items)
    assert (n1, d1) == (1, 0) and (n2, d2) == (0, 1)
    # 清理测试数据
    conn = db.get_conn()
    conn.execute("DELETE FROM items WHERE url='https://example.com/dedup-test'")
    conn.commit()
    conn.close()


def test_rawitem_engagement_defaults_empty():
    it = RawItem(title_orig="t", url="https://example.com/", source="x")
    assert it.engagement == {} and it.published_at is None


if __name__ == "__main__":
    test_all_ten_registered()
    test_valid_url()
    test_feed_date_iso()
    test_rss_collect_parses_real_feed()
    test_source_result_failure_shape()
    test_save_items_dedups_by_url()
    test_rawitem_engagement_defaults_empty()
    print("采集器单元测试 7 项通过 ✓")
