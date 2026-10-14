"""SEC EDGAR：官方公开接口（无 key、免费）。

用 browse-edgar 的 Atom 输出取最新 8-K（重大事项申报）。
硬性要求：每次请求带描述性 User-Agent（含联系邮箱），<=10 req/s。
数据为美国联邦公开信息，无版权风险。
"""
from __future__ import annotations

import os

from .base import BaseCollector, SourceResult
from .rss_util import rss_collect

ATOM_8K = ("https://www.sec.gov/cgi-bin/browse-edgar"
           "?action=getcurrent&type=8-K&count=40&output=atom")


class SecEdgarCollector(BaseCollector):
    name = "sec_edgar"
    display_name = "SEC EDGAR"

    def _client(self, extra_headers=None):
        contact = os.environ.get("SEC_CONTACT_EMAIL", "admin@example.com")
        headers = {"User-Agent": f"AI-Opportunity-Radar/1.0 contact:{contact}"}
        if extra_headers:
            headers.update(extra_headers)
        import httpx
        return httpx.Client(headers=headers, timeout=self.timeout,
                            follow_redirects=True)

    def collect(self) -> SourceResult:
        try:
            res = rss_collect(self, ATOM_8K, self.name,
                              category="投资", limit=40)
            res.note = "SEC 官方最新 8-K 申报（Atom）；标题为'公司+表单'合成"
            return res
        except Exception as e:  # noqa: BLE001
            return SourceResult(source=self.name, ok=False, error=str(e))
