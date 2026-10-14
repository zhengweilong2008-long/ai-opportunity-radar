"""app 包初始化：代理环境兼容性修复（所有入口共用）。"""

import os


def _sanitize_proxy_env() -> None:
    """兼容某些开发/代理环境：httpx 无法解析 no_proxy 里的带括号 IPv6
    条目（如 [::1]），会报 `Invalid port` 导致所有请求失败。
    这里只剔除这类条目，不影响代理本身的使用。"""
    for key in ("no_proxy", "NO_PROXY"):
        val = os.environ.get(key)
        if val and "[" in val:
            os.environ[key] = ",".join(p for p in val.split(",") if "[" not in p)


_sanitize_proxy_env()
