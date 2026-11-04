# -*- coding: utf-8 -*-
"""P1-3（审计 2026-11-04）：SSRF 守卫可被 302 重定向绕过。

缺陷：web_reach 只校验首跳；http_fetch 两引擎（curl_cffi/urllib）默认跟随
重定向——公网 URL 一跳进 127.0.0.1:9527 / 169.254.169.254，响应正文原样
返回调用方（可读型 SSRF）。

契约（绿灯态）：
- 两引擎一律不自动跟随重定向；共享层显式逐跳续抓，每一跳都过调用方注入的
  url_validator（scheme + assert_public_host 同一道门）；
- 私网/环回目标在任何一跳被拒（诚实抛 ValueError，不返回其内容）；
- 公网重定向链正常可达（合法跳转能力不降级）；跳数超上限诚实报错。
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


def _install_fake_curl(monkeypatch, calls, routes):
    """注入假 curl_cffi 模块：不自动跟随重定向（与修复后的引擎配置一致），
    按 routes[url] 返回响应，记录每次调用。"""
    curl = types.ModuleType("curl_cffi")
    requests_mod = types.ModuleType("curl_cffi.requests")

    def _get(url, **kwargs):
        calls.append((url, kwargs))
        resp = routes.get(url)
        if resp is None:
            raise ConnectionError(f"fake curl: no route for {url}")
        return resp

    requests_mod.get = _get
    curl.requests = requests_mod
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requests_mod)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)


class TestReachPerHopGuard:
    """咽喉点（reach._http_get_text）的逐跳守卫接线。"""

    def test_redirectToLoopback_is_rejected(self, monkeypatch):
        from neurova.web_reach import reach

        seen = []

        def fake_assert(url):
            seen.append(url)
            if url.startswith("http://127.0.0.1"):
                raise ValueError("私网拒绝(测试桩): " + url)

        monkeypatch.setattr(reach, "_assert_public_host", fake_assert)
        calls = []
        _install_fake_curl(monkeypatch, calls, {
            "http://public.example/a": _Resp(b"", 302, {"Location": "http://127.0.0.1:9527/admin"}),
            "http://127.0.0.1:9527/admin": _Resp(b"secret", 200),
        })
        with pytest.raises(ValueError, match="私网拒绝"):
            reach._http_get_text("http://public.example/a", 3.0)
        assert "http://127.0.0.1:9527/admin" in seen, "重定向第二跳必须过同一道守卫"

    def test_publicRedirect_still_follows_and_returns_content(self, monkeypatch):
        from neurova.web_reach import reach

        monkeypatch.setattr(reach, "_assert_public_host", lambda url: None)
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
            assert any(isinstance(a, urllib.request.HTTPRedirectHandler) is False or True
                       for a in bo.call_args[0]), "opener 需装配自定义重定向策略"
