"""评分引擎：热度评分 / 机会评分 / 投资观察评分 + 跨信源事件去重。

核心诚实原则（对应需求第 3、4、5 节）：
- 只用真实可获得的数据；缺数据就降置信度，标注"估算热度"/"数据不足"。
- 绝不伪造浏览量、点赞量、阅读量、估值。
- 未验证的盈利空间绝不写成已验证收入。
- 投资分析缺价格/财务数据时显示"数据不足"，不做收益预测。
"""
from __future__ import annotations

import json
import math
import re
from datetime import datetime, timezone

# ---- 信源可靠性（15 分制）----
SOURCE_RELIABILITY = {
    "sec_edgar": 15,      # 美国官方监管披露
    "deepmind": 13,       # 官方博客
    "openai_news": 12,    # 官方新闻
    "hackernews": 12,     # 社区精选+真实互动
    "techcrunch": 12,     # 主流科技媒体
    "hf_blog": 11,
    "producthunt": 11,
    "github_trending": 10,
    "reuters": 10,        # 经 Google News 间接覆盖，扣减
    "google_trends": 8,   # 搜索量档位，非新闻源
}

STOPWORDS = set("""the a an to of and for with on in at by from is are was were be
been has have had it its this that these those as or vs via new vs s""".split())


def tokenize(title: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def cluster_events(items: list[dict]) -> dict[int, int]:
    """跨信源事件去重：标题 token Jaccard > 0.45 视为同一事件。

    返回 {item_id: cluster_id}。同一事件只保留热度最高的一条展示，
    其余标记 dup_event。注意：同一通稿的转载不计为多个独立信源。
    """
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    toks = {}
    for it in items:
        iid = it["id"]
        parent[iid] = iid
        toks[iid] = tokenize(it.get("title_orig") or "")

    ids = [it["id"] for it in items]
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            a, b = ids[i], ids[j]
            if len(toks[a]) >= 3 and len(toks[b]) >= 3 \
                    and jaccard(toks[a], toks[b]) > 0.45:
                union(a, b)

    clusters: dict[int, int] = {}
    for iid in ids:
        clusters[iid] = find(iid)
    return clusters


def _age_hours(published_at: str | None) -> float | None:
    if not published_at:
        return None
    try:
        dt = datetime.fromisoformat(published_at)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 3600
    except Exception:
        return None


def _engagement_points(source: str, eng: dict) -> tuple[float, str]:
    """互动数据（30 分）：只用真实字段；无数据返回 0 并说明。"""
    if source == "hackernews":
        s, c = eng.get("score") or 0, eng.get("comments") or 0
        if s or c:
            return min(30.0, 12 * math.log10(1 + s) + 6 * math.log10(1 + c)), \
                f"HN {s} 赞/{c} 评论"
    elif source == "producthunt":
        v = eng.get("votes") or 0
        if v:
            return min(30.0, 15 * math.log10(1 + v)), f"PH {v} 票"
    elif source == "github_trending":
        st = eng.get("stars") or 0
        if st:
            return min(30.0, 12 * math.log10(1 + st)), f"GitHub {st} stars（总数）"
    elif source == "google_trends":
        tier = (eng.get("approx_traffic") or "").strip()
        mapping = {"200+": 8, "500+": 12, "1000+": 16,
                   "5000+": 20, "10000+": 24, "50000+": 26}
        if tier in mapping:
            return float(mapping[tier]), f"搜索量档位约 {tier}（非精确值）"
    return 0.0, "无公开互动数据"


def score_heat(item: dict, cluster_sources: int) -> tuple[float, dict, str]:
    """热度评分（满分 100）。返回 (分数, 分项明细, 置信度)。"""
    eng = json.loads(item.get("engagement") or "{}")
    source = item["source"]
    reasons: dict[str, float] = {}

    # 1. 公开互动数据 30 分
    e_pts, e_note = _engagement_points(source, eng)
    reasons["互动数据"] = round(e_pts, 1)

    # 2. 时效性 25 分
    age = _age_hours(item.get("published_at"))
    if age is None:
        reasons["时效性"] = 0.0
        t_note = "发布时间未核实"
    else:
        t_note = f"{age:.1f} 小时前"
        if age <= 6:
            reasons["时效性"] = 25.0
        elif age <= 12:
            reasons["时效性"] = 20.0
        elif age <= 24:
            reasons["时效性"] = 15.0
        elif age <= 48:
            reasons["时效性"] = 10.0
        elif age <= 72:
            reasons["时效性"] = 5.0
        else:
            reasons["时效性"] = 2.0

    # 3. 独立信源数量 20 分（同一通稿转载不重复计）
    _src_pts = {1: 6.0, 2: 12.0, 3: 16.0}
    reasons["独立信源"] = _src_pts.get(cluster_sources,
                                      20.0 if cluster_sources >= 4 else 6.0)

    # 4. 信源可靠性 15 分
    reasons["信源可靠性"] = float(SOURCE_RELIABILITY.get(source, 8))

    # 5. 趋势增长 10 分：无多日时序数据，暂无法评估 -> 0（诚实）
    reasons["趋势增长"] = 0.0

    total = round(sum(reasons.values()), 1)

    # 置信度
    has_eng = e_pts > 0
    has_time = age is not None
    if has_eng and has_time:
        confidence = "实际热度"
    elif has_eng or has_time:
        confidence = "估算热度"
    else:
        confidence = "数据不足"
    detail = {"_说明": f"{e_note}；{t_note}；{cluster_sources} 个独立信源"}
    return total, {**reasons, **detail}, confidence


SOURCE_DEFAULT_CATEGORY = {
    "deepmind": "AI", "openai_news": "AI", "hf_blog": "AI",
    "github_trending": "AI", "sec_edgar": "投资", "producthunt": "创业",
    "google_trends": "市场",
}


AI_KEYWORDS = (" ai", "gpt", "llm", "machine learning", "deep learning",
              "neural", "diffusion", "agent", "openai", "anthropic", "gemini",
              "deepmind", "hugging face", "stable diffusion")


def _has_ai_kw(t: str) -> bool:
    return any(k in t for k in AI_KEYWORDS)


def classify_category(title: str, summary: str | None, source: str = "") -> str:
    """关键词分类（规则版；LLM 接入后可优化）。强信号优先，其次信源默认。"""
    t = f"{title} {(summary or '')}".lower()
    if any(k in t for k in ("8-k", "10-k", "10-q", "stock", "nasdaq", "nyse",
                            "earnings", "ipo", "sec ", "shares", "dividend")):
        return "投资"
    if any(k in t for k in ("funding", "raises", "raised $", "startup",
                            "seed round", "series a", "series b", "launches",
                            "product hunt", "yc ", "y combinator")):
        return "创业"
    if source in SOURCE_DEFAULT_CATEGORY:
        default = SOURCE_DEFAULT_CATEGORY[source]
        # AI 关键词优先于非 AI 的信源默认（如 TechCrunch 的 AI 新闻）
        if default != "AI" and _has_ai_kw(t):
            return "AI"
        return default
    if _has_ai_kw(t):
        return "AI"
    return "科技"


# ---- 机会评分（满分 100，规则版）----

def _has_kw(text: str, kws: list[str]) -> bool:
    t = text.lower()
    return any(k in t for k in kws)


def score_opportunity(item: dict, heat: float) -> tuple[float, dict, dict]:
    """机会评分。返回 (分数, 分项明细, 机会详情字段)。

    规则版给分保守，备注"规则评分，待人工复核"；绝不把理论空间写成已验证收入。
    """
    eng = json.loads(item.get("engagement") or "{}")
    text = f"{item.get('title_orig','')} {item.get('summary_cn') or ''}"
    reasons: dict[str, float] = {}

    # 1. 真实需求证据 25 分：只看真实互动
    s = eng.get("score") or 0
    c = eng.get("comments") or 0
    v = eng.get("votes") or 0
    st = eng.get("stars") or 0
    if s >= 200 or c >= 100 or v >= 800 or st >= 5000:
        reasons["真实需求证据"] = 20.0
        ev_note = "高互动（真实数据）"
    elif s >= 50 or c >= 20 or v >= 200 or st >= 1000:
        reasons["真实需求证据"] = 14.0
        ev_note = "中等互动（真实数据）"
    elif s or c or v or st:
        reasons["真实需求证据"] = 9.0
        ev_note = "有少量互动（真实数据）"
    else:
        reasons["真实需求证据"] = 5.0
        ev_note = "无互动数据，证据不足"

    # 2. 变现路径清晰度 20 分
    if _has_kw(text, ["saas", "subscription", "pricing", "api ", "$", "付费",
                      "monetiz", "revenue"]):
        reasons["变现路径清晰度"] = 14.0
        mo_note = "提及付费/API/订阅模式（待验证）"
    else:
        reasons["变现路径清晰度"] = 6.0
        mo_note = "未提及明确付费模式"

    # 3. 低成本启动适配度 20 分
    if _has_kw(text, ["open source", "open-source", "side project", "indie",
                      "solo", "template", "no-code", "tutorial", "guide",
                      "github"]):
        reasons["低成本启动适配度"] = 16.0
        lc_note = "开源/个人项目属性，启动成本低"
    else:
        reasons["低成本启动适配度"] = 8.0
        lc_note = "未明确低成本属性"

    # 4. 趋势增长潜力 15 分
    cat = item.get("category") or ""
    if cat == "AI":
        reasons["趋势增长潜力"] = 12.0
    elif cat in ("创业", "科技"):
        reasons["趋势增长潜力"] = 9.0
    else:
        reasons["趋势增长潜力"] = 6.0

    # 5. 竞争与差异化 10 分：规则无法判断，如实给保守分
    reasons["竞争与差异化"] = 5.0
    # 6. 个人可执行性 10 分
    if _has_kw(text, ["tutorial", "guide", "open source", "template",
                      "how to", "build"]):
        reasons["个人可执行性"] = 8.0
    else:
        reasons["个人可执行性"] = 5.0

    total = round(sum(reasons.values()), 1)
    detail = {"_说明": f"{ev_note}；{mo_note}；{lc_note}；规则评分，待人工复核"}
    fields = build_opp_fields(item, cat, total)
    return total, {**reasons, **detail}, fields


def build_opp_fields(item: dict, category: str, score: float) -> dict:
    """机会详情字段：中文、谨慎措辞，不承诺收入。"""
    text = f"{item.get('title_orig','')} {item.get('summary_cn') or ''}"
    if category == "投资":
        opp_type = "投资"
    elif category == "创业":
        opp_type = "创业"
    elif category == "AI" or _has_ai_kw(text.lower()):
        opp_type = "AI"
    else:
        # 科技/市场/国际等：按"小本/内容创业"视角归入创业，备注待复核
        opp_type = "创业"
    return {
        "opp_type": opp_type,
        "cost_range": ("预估 ¥0–2,000（主要是个人时间成本；"
                       "域名/服务器等小额支出）"),
        "monetization": ("变现路径待验证：建议先阅读原文确认付费模式，"
                         "再找 3–5 个潜在付费用户访谈。理论上的盈利空间不等于已验证收入。"),
        "mvp_plan": ("最小可行验证（2 周内）：1）用现有工具做出可演示原型；"
                     "2）发到 2–3 个相关社区收集反馈；3）目标拿到 10 条有效用户反馈再决定投入。"),
        "risks": ("主要风险：需求真实性未验证；竞争格局未调研；"
                  "热度不等于付费意愿。"),
        "next_action": ("下一步：读原文抓关键信息 → 列出 3 个最可能付费的人群 → "
                        "做最小原型验证需求。"),
        "_note": f"规则生成（热度 {score} 分），待人工复核",
    }


def score_investment(item: dict) -> tuple[float, dict, str]:
    """投资观察评分（独立）：官方披露30% / 基本面25% / 估值价格风险20% /
    事件催化剂15% / 下行风险10%。缺价格/财务数据 -> 数据不足。"""
    reasons: dict[str, float] = {}
    # 官方披露和证据可靠性 30%
    reasons["官方披露可靠性"] = 28.0  # SEC EDGAR 官方申报
    # 业务基本面与财务状况 25%：8-K Atom 无财务数据
    reasons["基本面财务"] = 5.0
    # 估值与价格风险 20%：无可靠价格数据
    reasons["估值价格风险"] = 0.0
    # 事件催化剂 15%：8-K=重大事项
    reasons["事件催化剂"] = 10.0
    # 下行风险与不确定性 10%
    reasons["下行风险"] = 5.0
    total = round(sum(reasons.values()), 1)
    detail = {"_说明": ("8-K 重大事项申报（官方披露）；缺乏可靠股价与财务数据，"
                        "估值项记 0 分；不构成买入建议，热度不等于买入信号")}
    return total, {**reasons, **detail}, "数据不足"
