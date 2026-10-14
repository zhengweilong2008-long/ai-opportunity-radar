"""阶段一（静态站）测试：构建产物完整性检查。"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from markupsafe import escape as html_escape

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

SITE = BASE / "site"


def _read(name: str) -> str:
    p = SITE / name
    assert p.exists(), f"缺少页面文件 {name}"
    return p.read_text(encoding="utf-8")


def test_three_pages_exist():
    for name in ("index.html", "hot.html", "opportunities.html"):
        assert (SITE / name).exists()


def test_css_copied():
    css = SITE / "static" / "style.css"
    assert css.exists() and css.stat().st_size > 1000


def test_no_dynamic_references():
    """静态站不得引用动态路由或 API。"""
    for name in ("index.html", "hot.html", "opportunities.html"):
        html = _read(name)
        assert "/api/" not in html, f"{name} 含有 /api/ 引用"
        assert 'href="/hot"' not in html and 'href="/opportunities"' not in html, \
            f"{name} 含有动态路由链接"
        assert "manualRefresh" not in html, f"{name} 含有手动刷新脚本"


def test_nav_links_static():
    html = _read("index.html")
    assert 'href="hot.html"' in html
    assert 'href="opportunities.html"' in html


def test_hot_has_items_with_required_fields():
    data = json.loads((BASE / "data" / "site-data.json").read_text(encoding="utf-8"))
    html = _read("hot.html")
    items = data["hot"]
    assert len(items) == 10, f"24H 热点应为 10 条，实际 {len(items)} 条"
    for it in items:
        title = it["title_cn"] or it["title_orig"]
        # Jinja2 autoescape 会转义引号等字符，用转义后的文本匹配
        assert title and html_escape(title) in html, f"标题缺失：{title[:30]}"
        assert it["url"].startswith("http"), f"原文链接无效：{it['url'][:40]}"
        assert it["url"] in html
        assert it["score"] is not None


def test_opportunities_has_five():
    data = json.loads((BASE / "data" / "site-data.json").read_text(encoding="utf-8"))
    html = _read("opportunities.html")
    items = data["opportunities"]
    assert len(items) == 5, f"本周机会应为 5 条，实际 {len(items)} 条"
    for it in items:
        title = it["title_cn"] or it["title_orig"]
        assert title and html_escape(title) in html
        assert it["url"] in html
        assert it["score"] is not None


def test_home_has_stats_and_sources():
    html = _read("index.html")
    assert "最近一次成功更新" in html
    assert "各信源运行状态" in html
    assert "最近更新记录" in html
    # 十个信源名称应出现在状态表
    for name in ("GitHub Trending", "Hacker News", "SEC EDGAR"):
        assert name in html, f"首页缺少信源 {name}"


def test_no_fabrication_markers():
    """页面不得出现编造痕迹：空态必须诚实标注。"""
    for name in ("index.html", "hot.html", "opportunities.html"):
        html = _read(name)
        assert "lorem" not in html.lower()
        assert "示例数据" not in html and "模拟数据" not in html


def test_beijing_time_displayed():
    html = _read("index.html")
    # 北京时间日期应出现在页面
    assert re.search(r"20\d{2}-\d{2}-\d{2}", html), "首页缺少北京时间日期"
