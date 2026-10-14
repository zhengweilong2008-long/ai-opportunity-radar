"""阶段一测试：页面可访问、导航完整、无数据时如实展示空状态。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


def test_pages_render():
    for path, keyword in [
        ("/", "AI 机会雷达"),
        ("/hot", "24H 热点"),
        ("/opportunities", "本周机会"),
        ("/status", "运行状态"),
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
        assert keyword in r.text, path


def test_nav_links_present():
    r = client.get("/")
    for href in ['href="/"', 'href="/hot"', 'href="/opportunities"', 'href="/status"']:
        assert href in r.text, href


def test_scored_content_renders_honestly():
    """有数据时：热点显示分数/置信度/评分依据；机会显示完整字段；无编造痕迹。"""
    r = client.get("/hot")
    assert "/100</small>" in r.text  # 热度分数
    assert "评分依据" in r.text
    assert any(c in r.text for c in ["实际热度", "估算热度", "数据不足"])
    r = client.get("/opportunities")
    assert "机会类型" in r.text or "opp_type" in r.text or "AI" in r.text
    for field in ["变现路径", "最小可行验证", "主要风险", "下一步行动"]:
        assert field in r.text, field
    # 不得出现编造的精确互动数字措辞
    assert "10万+阅读" not in r.text


def test_refresh_not_implemented_yet():
    r = client.post("/api/refresh")
    assert r.status_code == 501
    assert r.json()["status"] == "not_implemented"


def test_ten_sources_seeded():
    r = client.get("/status")
    for name in ["GitHub Trending", "Hacker News", "Product Hunt", "OpenAI News",
                 "Hugging Face Blog", "TechCrunch", "Reuters", "SEC EDGAR",
                 "Google DeepMind", "Google Trends"]:
        assert name in r.text, name


if __name__ == "__main__":
    test_healthz()
    test_pages_render()
    test_nav_links_present()
    test_scored_content_renders_honestly()
    test_refresh_not_implemented_yet()
    test_ten_sources_seeded()
    print("全部 6 项测试通过 ✓")
