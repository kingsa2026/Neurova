# -*- coding: utf-8 -*-
"""safe_fetch——出站 HTTP 的逐跳安全使能层（U2 卡）。

**本模块不是第二个判定源**：SSRF 判定单源是 ``neurova.security.url_guard``
（scheme 白名单 / 私网 / 环回 / link-local / 169.254 元数据 / IPv6 ULA 逐 IP
校验，fail-closed，全仓 13+ 消费方）。引擎单源是 ``neurova.http_fetch``
（curl_cffi TLS 指纹优先、urllib 兜底、单跳不自动跟随）。本模块只做一件事：
把「连接前与**每一跳 redirect** 都强制过 url_guard 单源判定」拧进抓取通路，
并补齐 url_guard 不覆盖的抓取期约束：

- 每跳校验：首跳与每个重定向目标都过 ``assertHopAllowed``——只守首跳 +
  引擎自动跟随 = 可被 302 绕进环回/云元数据（P1-3），此门逐跳复核；
- 流式限量：响应体分块读取，超 ``max_bytes`` 抛 ``PayloadTooLargeError``
  （不静默截断、不把超大体全量吞进内存）；
- 错误日志只到 origin：路径/查询串可能携带凭据，日志一律只记
  ``scheme://host:port``，不落完整 URL；
- ``NEUROVA_SAFE_FETCH_ALLOW_PRIVATE``：默认关。开启后放行私网目标，仅供
  本地测试 / 自托管特殊场景（scheme 校验不随该开关放宽）。

异常契约（全部可识别、可分别处置）：
- ``SSRFBlockedError`` —— 目标被 SSRF 边界拒绝（继承 ValueError，兼容既有
  ``except ValueError`` 消费方）；
- ``PayloadTooLargeError`` —— 响应体超上限（转发引擎层同名异常，单一事实源）；
- ``RedirectLimitExceededError`` —— 重定向跳数超限；
- ``HTTPStatusError`` —— 终态 HTTP >= 400（服务端策略判定，诚实上抛）。

新增出站点一律走本模块（或直接接 url_guard + http_fetch validator 通路）；
直用 requests/httpx/aiohttp/urllib.request 由 ``scripts/check_outbound_fetch.py``
静态扫描拦截。
"""
from __future__ import annotations

import os
import urllib.parse
from typing import Dict, Iterable, Optional

from neurova import http_fetch
from neurova.core.logger import get_logger
from neurova.security.url_guard import PublicUrlResolution, resolvePublicUrl

logger = get_logger(__name__)

DEFAULT_TIMEOUT = http_fetch.DEFAULT_TIMEOUT
DEFAULT_MAX_BYTES = 8 * 1024 * 1024  # 8MB：常规网页/接口响应的安全上界
MAX_REDIRECT_HOPS = http_fetch.MAX_REDIRECT_HOPS
ALLOW_PRIVATE_ENV = "NEUROVA_SAFE_FETCH_ALLOW_PRIVATE"
SENSITIVE_REDIRECT_HEADERS = frozenset({
    "authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key",
})

_TRUE_VALUES = {"1", "true", "yes", "on"}


class SSRFBlockedError(ValueError):
    """目标被 SSRF 边界拒绝（scheme 非法 / 私网 / 环回 / 元数据段 / 解析失败）。"""


class RedirectLimitExceededError(ValueError):
    """重定向跳数超过 MAX_REDIRECT_HOPS：诚实报错，不静默截断链尾。"""


class HTTPStatusError(RuntimeError):
    """终态 HTTP >= 400：服务端策略判定，错误可见（不吞成空响应）。"""

    def __init__(self, status: int, message: str = ""):
        self.status = status
        super().__init__(message or f"HTTP Error {status}")


# PayloadTooLargeError 单源在 http_fetch（引擎层抛出），此处 re-export 供
# 调用方统一从 safe_fetch 取异常面，避免两处 import 路径漂移。
PayloadTooLargeError = http_fetch.PayloadTooLargeError


def privateFetchAllowed() -> bool:
    """NEUROVA_SAFE_FETCH_ALLOW_PRIVATE 是否开启（默认关）。"""
    return os.environ.get(ALLOW_PRIVATE_ENV, "").strip().lower() in _TRUE_VALUES


def originOf(url: str) -> str:
    """日志安全视图：只到 origin（scheme://host:port），不带路径/查询串。"""
    parsed = urllib.parse.urlparse(str(url or ""))
    return f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else str(url or "")


def _originTuple(url: str):
    parsed = urllib.parse.urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        port = None
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        port or (443 if parsed.scheme.lower() == "https" else 80),
    )


def assertHopAllowed(
    url: str, *, trusted_hosts: Optional[Iterable[str]] = None,
) -> PublicUrlResolution:
    """逐跳 SSRF 门，并返回本次连接必须使用的已验证地址计划。"""
    try:
        return resolvePublicUrl(
            url, allow_private=privateFetchAllowed(), trusted_hosts=trusted_hosts,
        )
    except ValueError as e:
        raise SSRFBlockedError(str(e)) from e


class SafeFetchResponse:
    """safe_fetch 终态响应（3xx 已逐跳走完；4xx/5xx 已在上层转 HTTPStatusError）。"""

    def __init__(self, status: int, headers: Dict[str, str], content: bytes, url: str):
        self.status = status
        self.headers = headers  # 键统一小写
        self.content = content
        self.url = url  # 末跳 URL

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self):
        import json

        return json.loads(self.text)

    def __repr__(self) -> str:  # 防止 repr 把完整 URL 带进日志
        return f"<SafeFetchResponse {self.status} {originOf(self.url)} {len(self.content)}B>"


def safe_fetch(
    url: str,
    *,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    data: Optional[bytes] = None,
    timeout: float = DEFAULT_TIMEOUT,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> SafeFetchResponse:
    """SSRF 安全门内的出站 HTTP 请求（阻塞式，线程池内调用）。

    连接前与每一跳 redirect 都过 ``assertHopAllowed``；响应体流式读取并
    强制 ``max_bytes`` 上限；HTTP >= 400 抛 ``HTTPStatusError``；目标非法
    抛 ``SSRFBlockedError``；失败日志只到 origin。
    """
    current = str(url or "")
    current_method = (method or "GET").upper()
    current_data = data
    for hop in range(MAX_REDIRECT_HOPS + 1):
        try:
            resolution = assertHopAllowed(current)
        except SSRFBlockedError as e:
            logger.warning("safe_fetch 拒绝出站请求 origin=%s hop=%d 原因=%s",
                           originOf(current), hop, e)
            raise
        try:
            hop_result = http_fetch.request_once(
                current, method=current_method, headers=headers, data=current_data,
                timeout=timeout, max_bytes=max_bytes, resolution=resolution,
            )
        except Exception as e:
            # 只记异常类名：异常 message 可能内嵌完整 URL（含查询串凭据）
            logger.warning("safe_fetch 请求失败 origin=%s hop=%d 原因=%s",
                           originOf(current), hop, type(e).__name__)
            raise
        location = hop_result.location
        if 300 <= hop_result.status < 400 and location:
            if hop >= MAX_REDIRECT_HOPS:
                raise RedirectLimitExceededError(
                    f"重定向超过 {MAX_REDIRECT_HOPS} 跳仍未到终址"
                    f"（链尾 origin: {originOf(current)}）"
                )
            # 301/302/303 改写为 GET；307/308 保持方法与请求体
            if hop_result.status not in (307, 308):
                current_method = "GET"
                current_data = None
            next_url = urllib.parse.urljoin(current, location)
            if _originTuple(next_url) != _originTuple(current):
                headers = {
                    key: value for key, value in (headers or {}).items()
                    if key.lower() not in SENSITIVE_REDIRECT_HEADERS
                }
            current = next_url
            continue
        if hop_result.status >= 400:
            logger.warning("safe_fetch 收到错误状态 origin=%s status=%d",
                           originOf(current), hop_result.status)
            raise HTTPStatusError(hop_result.status)
        return SafeFetchResponse(
            status=hop_result.status,
            headers=hop_result.headers,
            content=hop_result.content,
            url=current,
        )
    raise RedirectLimitExceededError(
        f"重定向超过 {MAX_REDIRECT_HOPS} 跳仍未到终址（链尾 origin: {originOf(current)}）"
    )
