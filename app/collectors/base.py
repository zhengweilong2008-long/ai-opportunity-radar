"""采集器基类。

原则（对应需求第 1 节）：
- 只用官方 API / RSS / 公开数据接口及允许的网页访问。
- 礼貌采集：固定 User-Agent、超时、有限重试、请求间隔。
- 不绕过登录、付费墙、验证码、访问限制或使用条款。
- 单个信源失败不影响其他信源（异常在 collect() 内消化为 SourceResult）。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import httpx

# 描述性 UA：SEC EDGAR 等官方接口硬性要求；其他源也建议携带
USER_AGENT = "AI-Opportunity-Radar/1.0 (daily research collector; contact: site admin)"
# 注意：代理环境兼容（no_proxy 里的 [::1] 等）已在 app/__init__.py 统一处理


@dataclass
class RawItem:
    """单个信源吐出的原始条目。只填能拿到的数据，拿不到就留空。"""
    title_orig: str
    url: str
    source: str                      # 与 db.SOURCES 的 name 一致
    published_at: str | None = None  # UTC ISO；未核实则为 None（绝不编造）
    category: str | None = None
    summary_orig: str | None = None
    engagement: dict = field(default_factory=dict)  # 真实互动数据，有才填


@dataclass
class SourceResult:
    source: str
    items: list[RawItem] = field(default_factory=list)
    ok: bool = True
    degraded: bool = False           # 降级运行（如用了备用方案）
    note: str | None = None
    error: str | None = None


class BaseCollector:
    name: str = "base"
    display_name: str = "Base"
    timeout: float = 20.0
    max_retries: int = 2
    retry_backoff: float = 2.0       # 秒，指数退避基数
    polite_delay: float = 0.5        # 每次请求后的礼貌间隔（秒）

    def _client(self, extra_headers: dict | None = None) -> httpx.Client:
        headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
        if extra_headers:
            headers.update(extra_headers)
        return httpx.Client(headers=headers, timeout=self.timeout, follow_redirects=True)

    def fetch(self, url: str, *, headers: dict | None = None,
              params: dict | None = None) -> httpx.Response:
        """带重试的 GET；最终失败抛异常，由 collect() 转为 SourceResult。"""
        last_exc: Exception | None = None
        with self._client(headers) as client:
            for attempt in range(self.max_retries + 1):
                try:
                    resp = client.get(url, params=params)
                    time.sleep(self.polite_delay)
                    if resp.status_code == 429:
                        raise RuntimeError(f"被限流 (429)：{url}")
                    resp.raise_for_status()
                    return resp
                except Exception as exc:  # noqa: BLE001 - 采集错误统一收敛
                    last_exc = exc
                    if attempt < self.max_retries:
                        time.sleep(self.retry_backoff * (attempt + 1))
            raise RuntimeError(f"请求失败（{self.max_retries + 1} 次）：{url}：{last_exc}")

    def collect(self) -> SourceResult:
        """子类实现。必须自己捕获异常并返回 ok=False 的 SourceResult。"""
        raise NotImplementedError
