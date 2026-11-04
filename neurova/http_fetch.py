"""共享阻塞 HTTP GET 层：curl_cffi 浏览器 TLS 指纹优先，urllib 兜底。

根因：urllib 使用 Python 默认 TLS ClientHello（JA3 指纹特征明显），反爬层
（Cloudflare 等）不看 HTTP 头、直接按握手指纹 403。本层经 curl_cffi 引擎
（curl + browser impersonate）一次升级握手指纹。

约定：
- 仅供线程池内同步调用（P2-11 契约：不得在事件循环直接执行）
- SSRF/协议守卫归调用方（web_reach._http_get_text / rss_read 等咽喉点先行校验）；
  重定向不交引擎自动跟随——本层显式逐跳续抓，每跳回调调用方注入的
  url_validator 复核（P1-3：只守首跳 + 引擎自动跟随 = 可被 302 绕过）；
  未注入 validator 的调用方保持跟随重定向的旧行为，跳数封顶 MAX_REDIRECT_HOPS
- curl_cffi 缺失（ImportError）或连接层故障（curl 56 类引擎抖动）回落 urllib
  一次——保证旧路径能力不降级；HTTP >= 400 是服务端策略判定，不双引擎重复打；
  双引擎均失败抛 curl 第一手错误（不抹除）
- fetch_bytes 返回原始字节（feedparser 等需自行探测编码）；fetch_text 为其
  utf-8 + errors=replace 解码视角
- 调用方 UA 永远原样传递（Jina Reader 等按 UA 识别调用方，层不得替换）；
  impersonate 只对浏览器系（Mozilla 开头）UA 启用，只升级 TLS/H2 握手指纹
  与头部顺序，不接管 UA
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Optional, Tuple

DEFAULT_TIMEOUT = 20.0
MAX_REDIRECT_HOPS = 5
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}

# Windows libcurl 读不了非 ASCII 路径的 CA 文件（curl 77），而 venv 常位于
# 含中文的目录（如 E:\项目\...）。检测后一次性复制到 ASCII 临时目录复用。
_ca_lock = threading.Lock()
_ca_state: Optional[str] = ""  # ""=未检测；None=无需处理；str=ASCII 副本路径


def _ascii_ca() -> Optional[str]:
    """certifi CA 路径含非 ASCII 时复制到可写 ASCII 临时目录，返回该路径。

    返回 None = certifi 默认可用，或找不到 ASCII 可写目录（此时不传 verify，
    让 curl_cffi 自然报错，由 fetch_bytes 的 urllib 兜底链路保证可用性）。
    """
    global _ca_state
    with _ca_lock:
        if _ca_state != "":
            return _ca_state
        try:
            import certifi

            src = certifi.where()
            src.encode("ascii")
            _ca_state = None  # 路径纯 ASCII，默认可用
            return None
        except Exception:
            pass
        roots = [
            os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp"),
            tempfile.gettempdir(),
        ]
        for root in roots:
            try:
                root.encode("ascii")
                dest = os.path.join(root, "neurova-cacert.pem")
                import certifi

                shutil.copyfile(certifi.where(), dest)
                _ca_state = dest
                return dest
            except Exception:
                continue
        _ca_state = None
        return None


class _HttpStatusError(RuntimeError):
    """HTTP >= 400：服务端策略判定（换客户端引擎不改变判决），不做兜底重试"""


class _RedirectLoopError(RuntimeError):
    """重定向跳数超限：诚实报错点名链尾，不静默截断"""


def _redirectLocation(resp) -> Optional[str]:
    """3xx 响应的 Location 头（归一空白）；非 3xx / 无头 / 无该头返回 None。

    引擎响应对象形状不一（curl_cffi 响应、HTTPError、http.client 响应），
    状态码按 status_code / code 两种属性名取，均缺视为非跳转。
    """
    status = getattr(resp, "status_code", None)
    if status is None:
        status = getattr(resp, "code", None)
    if status is None or status not in _REDIRECT_STATUSES:
        return None
    headers = getattr(resp, "headers", None)
    if headers is None:
        return None
    location = headers.get("Location")
    if not location:
        return None
    return str(location).strip() or None


def _curl_bytes(url: str, user_agent: str, timeout: float) -> Optional[Tuple[bytes, Optional[str]]]:
    """经 curl_cffi 单跳抓取（禁自动跟随，跳转交上层循环逐跳处理）。

    未安装返回 None（调用方回落 urllib），网络/HTTP 错误照抛。
    """
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None
    kw = {"timeout": timeout, "headers": {"User-Agent": user_agent}, "allow_redirects": False}
    ca = _ascii_ca()
    if ca:
        kw["verify"] = ca
    if user_agent.startswith("Mozilla"):
        resp = curl_requests.get(url, impersonate="chrome", **kw)
    else:
        resp = curl_requests.get(url, **kw)
    if resp.status_code >= 400:
        raise _HttpStatusError(f"HTTP Error {resp.status_code}")
    return resp.content, _redirectLocation(resp)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """禁自动跟随：3xx 交还上层循环逐跳处理（每跳可复核 SSRF 守卫）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _urllib_bytes(url: str, user_agent: str, timeout: float) -> Tuple[bytes, Optional[str]]:
    """urllib 兜底单跳（同样禁自动跟随）。

    3xx 被 _NoRedirectHandler 转成 HTTPError 抛出，此处归一成 (空体, Location)
    交还上层循环；其余 HTTPError 照抛（错误可见语义不变）。
    """
    req = urllib.request.Request(url, headers={"User-Agent": user_agent})
    opener = urllib.request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.read(), _redirectLocation(resp)
    except urllib.error.HTTPError as e:
        if e.code in _REDIRECT_STATUSES:
            return b"", _redirectLocation(e)
        raise


def _fetch_once(url: str, user_agent: str, timeout: float) -> Tuple[bytes, Optional[str]]:
    """单跳双引擎：curl_cffi 优先，ImportError/引擎故障回落 urllib 一次。"""
    try:
        result = _curl_bytes(url, user_agent, timeout)
    except _HttpStatusError:
        raise
    except ImportError:
        return _urllib_bytes(url, user_agent, timeout)
    except Exception as curl_err:
        try:
            return _urllib_bytes(url, user_agent, timeout)
        except Exception:
            raise curl_err
    return result if result is not None else _urllib_bytes(url, user_agent, timeout)


def fetch_bytes(
    url: str,
    user_agent: str,
    timeout: float = DEFAULT_TIMEOUT,
    url_validator: Optional[Callable[[str], None]] = None,
) -> bytes:
    """阻塞 GET 返回原始字节（curl_cffi 优先，urllib 兜底链见模块 docstring）。

    url_validator：可选逐跳复核回调（P1-3）。传入时每一跳（含首跳）请求前
    调用，SSRF 守卫即以同一道门覆盖全部跳；不传保持跟随重定向的旧行为。
    """
    current = url
    hops = 0
    while True:
        if url_validator is not None:
            url_validator(current)
        content, location = _fetch_once(current, user_agent, timeout)
        if location is None:
            return content
        if hops >= MAX_REDIRECT_HOPS:
            raise _RedirectLoopError(
                f"重定向超过 {MAX_REDIRECT_HOPS} 跳仍未到终址（链尾: {current} → {location}）"
            )
        hops += 1
        current = urllib.parse.urljoin(current, location)


def fetch_text(
    url: str,
    user_agent: str,
    timeout: float = DEFAULT_TIMEOUT,
    url_validator: Optional[Callable[[str], None]] = None,
) -> str:
    """阻塞 GET 返回 UTF-8 文本（fetch_bytes 链 + utf-8 errors=replace 解码）。"""
    return fetch_bytes(url, user_agent, timeout, url_validator=url_validator).decode(
        "utf-8", errors="replace"
    )
