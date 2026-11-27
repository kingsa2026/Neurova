# -*- coding: utf-8 -*-
"""P1-3（审计 2026-11-04）：SSRF 守卫可被 302 重定向绕过。

缺陷：web_reach 只校验首跳；http_fetch 两引擎（curl_cffi/urllib）默认跟随
重定向——公网 URL 一跳进 127.0.0.1:9527 / 169.254.169.254，响应正文原样
返回调用方（可读型 SSRF）。

契约（绿灯态，U2 收敛后）：
- 出站抓取统一走 neurova.security.safe_fetch 单门：两引擎一律不自动跟随
  重定向，safe_fetch 显式逐跳续抓，每一跳（含首跳）都过 assertHopAllowed
  （scheme + url_guard 单源判定）；
- 私网/环回目标在任何一跳被拒（诚实抛 SSRFBlockedError，不返回其内容）；
- 公网重定向链正常可达（合法跳转能力不降级）；跳数超上限诚实报错。
本文件保留共享层 fetch_bytes/fetch_text 的 validator 注入口回归；
reach 咽喉点的逐跳行为迁移到 safe_fetch 门上复验。
"""
import io
import sys
import types
import urllib.error
from unittest.mock import patch

import pytest

from neurova import http_fetch


class _Resp:
    def __init__(self, content=b"", status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def iter_content(self, chunk_size=None):
        yield self.content

    def close(self):
        pass


def _install_fake_curl(monkeypatch, calls, routes):
    """注入假 curl_cffi 模块：不自动跟随重定向（与修复后的引擎配置一致），
    按 routes[url] 返回响应，记录每次调用。"""
    curl = types.ModuleType("curl_cffi")
    curl.CurlOpt = types.SimpleNamespace(RESOLVE=10204)
    requests_mod = types.ModuleType("curl_cffi.requests")

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        resp = routes.get(url)
        if resp is None:
            raise ConnectionError(f"fake curl: no route for {url}")
        return resp

    def _request(method, url, **kwargs):
        return _get(url, **kwargs)

    requests_mod.get = _get
    requests_mod.request = _request
    curl.requests = requests_mod
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests_mod)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)


class TestReachPerHopGuard:
    """咽喉点（reach._http_get_text）经 safe_fetch 单门的逐跳守卫。"""

    def test_redirectToLoopback_is_rejected(self, monkeypatch):
        from neurova.security import safe_fetch as safe_fetch_mod
        from neurova.security.url_guard import PublicUrlResolution
        from neurova.web_reach import reach

        seen = []

        def fake_resolver(url, *args, **kwargs):
            from urllib.parse import urlparse

            seen.append(url)
            parsed = urlparse(url)
            if parsed.hostname == "127.0.0.1":
                raise ValueError("私网拒绝(测试桩): " + url)
            return PublicUrlResolution(
                scheme=parsed.scheme, host=parsed.hostname,
                port=parsed.port or 80, addresses=("93.184.216.34",),
            )

        monkeypatch.setattr(safe_fetch_mod, "resolvePublicUrl", fake_resolver)
        calls = []
        _install_fake_curl(monkeypatch, calls, {
            "http://public.example/a": _Resp(b"", 302, {"Location": "http://127.0.0.1:9527/admin"}),
            "http://127.0.0.1:9527/admin": _Resp(b"secret", 200),
        })
        with pytest.raises(ValueError, match="私网拒绝"):
            reach._http_get_text("http://public.example/a", 3.0)
        assert "http://127.0.0.1:9527/admin" in seen, "重定向第二跳必须过同一道守卫"
        assert len(calls) == 1, "第二跳必须在连接前被拒，不得发出对环回的请求"

    def test_publicRedirect_still_follows_and_returns_content(self, monkeypatch):
        from neurova.security import safe_fetch as safe_fetch_mod
        from neurova.security.url_guard import PublicUrlResolution
        from neurova.web_reach import reach

        def fake_resolver(url, *args, **kwargs):
            from urllib.parse import urlparse

            parsed = urlparse(url)
            return PublicUrlResolution(
                scheme=parsed.scheme, host=parsed.hostname,
                port=parsed.port or (443 if parsed.scheme == "https" else 80),
                addresses=("93.184.216.34",),
            )

        monkeypatch.setattr(safe_fetch_mod, "resolvePublicUrl", fake_resolver)
        calls = []
        _install_fake_curl(monkeypatch, calls, {
            "http://public.example/a": _Resp(b"", 302, {"Location": "https://public2.example/b"}),
            "https://public2.example/b": _Resp("跳转后正文".encode("utf-8"), 200),
        })
        text = reach._http_get_text("http://public.example/a", 3.0)
        assert text == "跳转后正文"
        assert len(calls) == 2, "两跳两次显式请求"
        for _url, kwargs in calls:
            assert kwargs.get("allow_redirects") is False, "引擎不得自动跟随（守卫要插到跳间）"


class TestWebFetchToolPerHopGuard:
    """工具咽喉点必须把逐跳 validator 接到共享抓取层。"""

    @pytest.mark.asyncio
    async def test_webFetchUsesAddressPlanForFirstRequest(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "neurova.security.url_guard.socket.getaddrinfo",
            lambda host, port, *args, **kwargs: [
                (2, 1, 6, "", ("93.184.216.34", port)),
            ],
        )
        calls = []
        _install_fake_curl(monkeypatch, calls, {
            "https://public.example/a": _Resp(b"<p>pinned</p>", 200),
        })
        executor = ToolExecutor.__new__(ToolExecutor)

        result = await executor._execute_web_fetch({"url": "https://public.example/a"})

        assert result["content"] == "pinned"
        assert len(calls) == 1
        options = calls[0][1].get("curl_options")
        assert options, "web_fetch 必须把 URL 校验返回的地址计划传到连接引擎"

    @pytest.mark.asyncio
    async def test_redirect_to_loopback_is_rejected_before_second_request(self, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        monkeypatch.setattr(
            "neurova.security.url_guard.socket.getaddrinfo",
            lambda host, port, *args, **kwargs: [
                (2, 1, 6, "", ("93.184.216.34", port)),
            ],
        )
        calls = []
        _install_fake_curl(monkeypatch, calls, {
            "https://public.example/a": _Resp(
                b"", 302, {"Location": "http://127.0.0.1:9527/admin"}
            ),
            "http://127.0.0.1:9527/admin": _Resp(b"secret", 200),
        })
        executor = ToolExecutor.__new__(ToolExecutor)

        result = await executor._execute_web_fetch({"url": "https://public.example/a"})

        assert "error" in result, result
        assert "127.0.0.1" in result["error"]
        assert len(calls) == 1, "私网第二跳必须在连接前被拒绝"
        assert "secret" not in result.get("content", "")


class TestSharedLayerHopLoop:
    """共享层 fetch_bytes/fetch_text 的逐跳循环与 validator 注入口。"""

    def test_validator_blocks_private_hop(self, monkeypatch):
        calls = []
        _install_fake_curl(monkeypatch, calls, {
            "https://public.example/a": _Resp(b"", 302, {"Location": "http://127.0.0.1/x"}),
            "http://127.0.0.1/x": _Resp(b"secret", 200),
        })

        def validator(url):
            if url.startswith("http://127.0.0.1"):
                raise ValueError("私网目标拒绝: " + url)

        with pytest.raises(ValueError, match="私网目标拒绝"):
            http_fetch.fetch_bytes("https://public.example/a", "Mozilla/5.0", 5, url_validator=validator)

    def test_hop_cap_raises_honestly(self, monkeypatch):
        calls = []
        routes = {f"https://hop{i}.example/x": _Resp(b"", 302, {"Location": f"https://hop{i + 1}.example/x"})
                  for i in range(7)}
        _install_fake_curl(monkeypatch, calls, routes)
        with pytest.raises(Exception, match="重定向"):
            http_fetch.fetch_bytes("https://hop0.example/x", "Mozilla/5.0", 5)
        assert len(calls) <= 6, "跳数必须有上限，不得无限跟随"

    def test_urllib_fallback_redirect_not_followed(self, monkeypatch):
        """urllib 引擎同样不自动跟随：3xx 以 HTTPError 形态交还循环逐跳处理。"""
        calls = []
        _install_fake_curl(monkeypatch, calls, {})  # curl 全路由未命中 → 走 urllib
        http_error = urllib.error.HTTPError(
            "https://public.example/a", 302, "Found",
            {"Location": "http://127.0.0.1/x"}, io.BytesIO(b""),
        )

        class _FakeOpener:
            def open(self, req, timeout=None):
                raise http_error

        with patch("urllib.request.build_opener", return_value=_FakeOpener()) as bo:
            with pytest.raises(Exception):
                http_fetch.fetch_bytes(
                    "https://public.example/a", "Mozilla/5.0", 5,
                    url_validator=lambda u: (_ for _ in ()).throw(ValueError("私网: " + u))
                    if u.startswith("http://127.0.0.1") else None,
                )
            assert bo.called, "urllib 路径必须经禁跟随 opener"
            assert any(
                isinstance(handler, http_fetch._NoRedirectHandler)
                for handler in bo.call_args[0]
            ), "opener 需装配自定义重定向策略"
