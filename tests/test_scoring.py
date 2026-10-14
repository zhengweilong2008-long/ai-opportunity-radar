"""阶段三测试：评分算法与去重（纯逻辑，不依赖外网）。"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.scoring import (classify_category, cluster_events, jaccard,
                         score_heat, score_investment, score_opportunity,
                         tokenize)


def _item(**kw):
    base = {"id": 1, "title_orig": "Test", "source": "hackernews",
            "published_at": None, "engagement": "{}",
            "summary_cn": None, "category": "科技"}
    base.update(kw)
    return base


def test_heat_never_fabricates():
    # 无互动、无时间 -> 分数低且置信度为"数据不足"
    score, reasons, conf = score_heat(_item(), 1)
    assert conf == "数据不足"
    assert reasons["互动数据"] == 0.0
    assert reasons["时效性"] == 0.0
    assert reasons["趋势增长"] == 0.0  # 无时序数据，如实为 0
    assert 0 < score < 40


def test_heat_uses_real_engagement():
    import json
    now = datetime.now(timezone.utc).isoformat()
    it = _item(published_at=now,
               engagement=json.dumps({"score": 300, "comments": 120}))
    score, reasons, conf = score_heat(it, 2)
    assert conf == "实际热度"
    assert reasons["互动数据"] > 20
    assert reasons["时效性"] == 25.0
    assert reasons["独立信源"] == 12.0
    assert score <= 100


def test_heat_recency_decay():
    import json
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    it = _item(published_at=old,
               engagement=json.dumps({"score": 300, "comments": 120}))
    _, reasons, _ = score_heat(it, 1)
    assert reasons["时效性"] == 10.0  # 24-48h 档


def test_cluster_dedups_same_event():
    items = [
        {"id": 1, "title_orig": "OpenAI releases GPT-5 with new reasoning engine"},
        {"id": 2, "title_orig": "OpenAI releases GPT-5 featuring new reasoning engine"},
        {"id": 3, "title_orig": "Local bakery wins award for sourdough"},
    ]
    clusters = cluster_events(items)
    assert clusters[1] == clusters[2]
    assert clusters[1] != clusters[3]


def test_jaccard_basic():
    assert jaccard({"a", "b"}, {"a", "b"}) == 1.0
    assert jaccard({"a"}, {"b"}) == 0.0
    assert tokenize("The Quick, Brown Fox!") == {"quick", "brown", "fox"}


def test_opportunity_is_conservative():
    import json
    it = _item(title_orig="Some random tool",
               engagement=json.dumps({}))
    score, reasons, fields = score_opportunity(it, 50)
    assert score < 70  # 无证据时规则评分保持保守
    assert "待验证" in fields["monetization"] or "未经证实" in fields["monetization"]
    assert "不等于已验证收入" in fields["monetization"] or "不构成" in fields["risks"]
    assert fields["opp_type"] in ("AI", "创业", "投资")


def test_investment_marks_data_insufficient():
    score, reasons, conf = score_investment(_item(source="sec_edgar"))
    assert conf == "数据不足"
    assert reasons["估值价格风险"] == 0.0
    assert "不构成买入建议" in reasons["_说明"]


def test_classify_category():
    assert classify_category("Apple stock rises on earnings", None, "x") == "投资"
    assert classify_category("Startup raises $5M seed round", None, "x") == "创业"
    assert classify_category("New LLM agent framework", None, "x") == "AI"
    assert classify_category("Google DeepMind partners with gov", None, "deepmind") == "AI"
    assert classify_category("Random gadget review", None, "x") == "科技"


if __name__ == "__main__":
    test_heat_never_fabricates()
    test_heat_uses_real_engagement()
    test_heat_recency_decay()
    test_cluster_dedups_same_event()
    test_jaccard_basic()
    test_opportunity_is_conservative()
    test_investment_marks_data_insufficient()
    test_classify_category()
    print("评分测试 8 项通过 ✓")
