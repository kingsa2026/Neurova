# -*- coding: utf-8 -*-
"""U2 卡：SSRF 防护收敛为专用 safe-fetch 模块（先红后绿）。

红灯事实（迁移前）：直连 127.0.0.1 / 169.254.169.254 与「公网 302 跳私网」
经旧出站路径（裸 urllib / aiohttp 自动跟随重定向）当前**成功**——知识导入
_fetch_url 用裸 urlopen 跟随重定向、persist_media 用 aiohttp 仅首跳校验。

绿灯契约（本文件逐条钉住）：
- safe_fetch 连接前与**每一跳 redirect** 都过同一道 SSRF 门（私网/环回/
  link-local/169.254 元数据/IPv6 ULA 全拒），拒因以可识别异常 SSRFBlockedError
  暴露（继承 ValueError，兼容既有 except ValueError 消费方）；
- 响应体流式读取 + max_bytes 体积上限（超限 PayloadTooLargeError，不静默截断）；
- 失败日志只到 origin（scheme://host:port），不带完整 URL（路径/查询串可能
  含凭据）；
- NEUROVA_SAFE_FETCH_ALLOW_PRIVATE 环境变量默认关；开启后放行私网目标
  （仅供本地测试 / 自托管特殊场景），scheme 校验不放宽；
- 重定向跳数封顶，超限诚实报错；公网重定向链正常可达（能力不降级）。
"""
from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from neurova import http_fetch
from neurova.security import safe_fetch
from neurova.security.safe_fetch import (
    PayloadTooLargeError,
    RedirectLimitExceededError,
    SSRFBlockedError,
    safe_fetch as safe_fetch_fn,
)


# ── 引擎桩：替换 http_fetch.request_once，按 routes 返回单跳响应 ──────────

class _Hop:
    def __init__(self, status=200, content=b"", headers=None, location=None):
        self.status = status
        self.content = content
        self.headers = headers or {}
        self.location = location


def _install_fake_engine(monkeypatch, calls, routes, error=None):
    def fake_request_once(url, *, method="GET", headers=None, data=None,
                          timeout=None, max_bytes=None, user_agent=None):
        calls.append({"url": url, "method": method, "headers": headers,
                      "data": data, "max_bytes": max_bytes})
        if error is not None:
            raise error
        hop = routes.get(url)
        if hop is None:
            raise ConnectionError(f"fake engine: no route for {url}")
        if max_bytes is not None and len(hop.content) > max_bytes:
            # 与真实引擎（http_fetch._readCapped）同契约：超上限诚实拒绝
            raise http_fetch.PayloadTooLargeError(f"响应体超过上限 {max_bytes} 字节")
        return http_fetch.HopResult(status=hop.status, headers=dict(hop.headers),
                                    content=hop.content, location=hop.location)

    monkeypatch.setattr(http_fetch, "request_once", fake_request_once)


# ── 直连私网/环回/元数据/ULA：连接前拒绝 ─────────────────────────────────

class TestDirectTargetsRejected:
    @pytest.mark.parametrize("url", [
        "http://127.0.0.1:9527/admin",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.1.2.3/internal",
        "http://172.16.0.5/",
        "http://192.168.1.1/router",
        "http://0.0.0.0/",
    ])
    def test_privateV4Literal_rejected(self, url):
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn(url, timeout=3.0)

    @pytest.mark.parametrize("url", [
        "http://[::1]:9527/",
        "http://[fc00::1]/internal",   # IPv6 ULA
        "http://[fe80::1]/",           # IPv6 link-local
    ])
    def test_privateV6Literal_rejected(self, url):
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn(url, timeout=3.0)

    @pytest.mark.parametrize("url", [
        "http://localhost:8975/",
        "http://sub.localhost/",
    ])
    def test_localhostHostname_rejected(self, url):
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn(url, timeout=3.0)

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
    ])
    def test_nonHttpScheme_rejected(self, url):
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn(url, timeout=3.0)

    def test_missingHost_rejected(self):
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn("http:///no-host", timeout=3.0)

    def test_blockedError_isValueError(self):
        """可识别异常同时兼容既有 `except ValueError` 消费方。"""
        assert issubclass(SSRFBlockedError, ValueError)


# ── 每一跳 redirect 都过同一道门（P1-3 场景在统一门上复验） ──────────────

class TestPerHopRedirectGuard:
    def test_publicRedirectToLoopback_blockedBeforeSecondRequest(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "http://public.example/a": _Hop(302, location="http://127.0.0.1:9527/admin"),
            "http://127.0.0.1:9527/admin": _Hop(200, b"secret"),
        })
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn("http://public.example/a", timeout=3.0)
        assert len(calls) == 1, "第二跳必须在连接前被拒，不得发出对环回的请求"
        assert calls[0]["url"] == "http://public.example/a"

    def test_publicRedirectToMetadata_blocked(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "http://public.example/a": _Hop(302, location="http://169.254.169.254/latest/meta-data/"),
        })
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn("http://public.example/a", timeout=3.0)
        assert len(calls) == 1

    def test_publicRedirectChain_stillFollows(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "http://public.example/a": _Hop(302, location="https://public2.example/b"),
            "https://public2.example/b": _Hop(200, "跳转后正文".encode("utf-8")),
        })
        resp = safe_fetch_fn("http://public.example/a", timeout=3.0)
        assert resp.status == 200
        assert resp.text == "跳转后正文"
        assert len(calls) == 2, "合法公网重定向链两跳两次显式请求"

    def test_redirectHopsCapped_honestError(self, monkeypatch):
        calls = []
        routes = {f"https://hop{i}.example/x": _Hop(302, location=f"https://hop{i + 1}.example/x")
                  for i in range(8)}
        _install_fake_engine(monkeypatch, calls, routes)
        with pytest.raises(RedirectLimitExceededError):
            safe_fetch_fn("https://hop0.example/x", timeout=3.0)
        assert len(calls) <= safe_fetch.MAX_REDIRECT_HOPS + 1, "跳数必须有上限"

    def test_relativeRedirectLocation_resolved(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "https://public.example/a": _Hop(302, location="/next"),
            "https://public.example/next": _Hop(200, b"arrived"),
        })
        resp = safe_fetch_fn("https://public.example/a", timeout=3.0)
        assert resp.content == b"arrived"
        assert calls[1]["url"] == "https://public.example/next"


# ── 响应体流式读取 + 体积上限 ────────────────────────────────────────────

class TestBodySizeCap:
    def test_bodyOverMaxBytes_rejected(self, monkeypatch):
        calls = []
        big = b"x" * (1024 * 1024)
        _install_fake_engine(monkeypatch, calls, {
            "https://public.example/big": _Hop(200, big),
        })
        with pytest.raises(PayloadTooLargeError):
            safe_fetch_fn("https://public.example/big", timeout=3.0, max_bytes=1024)

    def test_bodyWithinCap_returnedFully(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "https://public.example/ok": _Hop(200, b"hello-bytes"),
        })
        resp = safe_fetch_fn("https://public.example/ok", timeout=3.0, max_bytes=1024)
        assert resp.content == b"hello-bytes"

    def test_maxBytesPassedToEngine(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "https://public.example/ok": _Hop(200, b"hi"),
        })
        safe_fetch_fn("https://public.example/ok", timeout=3.0, max_bytes=4096)
        assert calls[0]["max_bytes"] == 4096

    def test_engineReadCapped_streams_and_enforces(self):
        """引擎层流式读取核心：分块读入，超上限即刻拒绝（不整体吞内存）。"""
        class _Chunked:
            def __init__(self, payload, size):
                self._payload, self._size, self._pos = payload, size, 0

            def read(self, n=-1):
                if self._pos >= len(self._payload):
                    return b""
                chunk = self._payload[self._pos:self._pos + self._size]
                self._pos += self._size
                return chunk

        reader = _Chunked(b"a" * 5000, 1024)
        assert http_fetch._readCapped(reader, 8192) == b"a" * 5000
        with pytest.raises(PayloadTooLargeError):
            http_fetch._readCapped(_Chunked(b"a" * 5000, 1024), 1024)


# ── NEUROVA_SAFE_FETCH_ALLOW_PRIVATE 放行门（默认关） ────────────────────

class TestAllowPrivateEnv:
    def test_envOff_loopbackStillBlocked(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_SAFE_FETCH_ALLOW_PRIVATE", raising=False)
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn("http://127.0.0.1:8975/", timeout=3.0)

    @pytest.mark.parametrize("value", ["1", "true", "YES", "on"])
    def test_envOn_loopbackAllowed(self, monkeypatch, value):
        monkeypatch.setenv("NEUROVA_SAFE_FETCH_ALLOW_PRIVATE", value)
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "http://127.0.0.1:8975/": _Hop(200, b"local-ok"),
        })
        resp = safe_fetch_fn("http://127.0.0.1:8975/", timeout=3.0)
        assert resp.content == b"local-ok"

    def test_envOn_schemeStillEnforced(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_SAFE_FETCH_ALLOW_PRIVATE", "1")
        with pytest.raises(SSRFBlockedError):
            safe_fetch_fn("file:///etc/passwd", timeout=3.0)


# ── 失败日志只到 origin，不带完整 URL ────────────────────────────────────

class TestErrorLogOriginOnly:
    def test_ssrfBlockLog_hasOriginNotFullUrl(self, monkeypatch, caplog):
        with caplog.at_level(logging.WARNING, logger="neurova.security.safe_fetch"):
            with pytest.raises(SSRFBlockedError):
                safe_fetch_fn("http://127.0.0.1:9527/admin?token=SECRET", timeout=3.0)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "token=SECRET" not in text, "日志不得携带完整 URL（查询串含敏感参数）"
        assert "/admin" not in text, "日志不得携带路径"
        assert "127.0.0.1" in text, "日志应指到 origin（scheme://host）"

    def test_transportErrorLog_hasOriginNotFullUrl(self, monkeypatch, caplog):
        calls = []
        _install_fake_engine(monkeypatch, calls, {},
                             error=ConnectionError("boom http://public.example/a?token=SECRET"))
        with caplog.at_level(logging.WARNING, logger="neurova.security.safe_fetch"):
            with pytest.raises(ConnectionError):
                safe_fetch_fn("http://public.example/a?token=SECRET", timeout=3.0)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "token=SECRET" not in text
        assert "http://public.example" in text


# ── 响应形状与请求参数透传 ───────────────────────────────────────────────

class TestRequestShape:
    def test_methodHeadersData_passedThrough(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "https://public.example/api": _Hop(200, b'{"ok": true}'),
        })
        resp = safe_fetch_fn(
            "https://public.example/api", method="POST",
            headers={"User-Agent": "Neurova-Test/1.0", "X-Trace": "t1"},
            data=b"payload", timeout=7.0, max_bytes=2048,
        )
        call = calls[0]
        assert call["method"] == "POST"
        assert call["headers"]["X-Trace"] == "t1"
        assert call["data"] == b"payload"
        assert resp.status == 200
        assert resp.json() == {"ok": True}

    def test_responseText_utf8Replace(self, monkeypatch):
        calls = []
        _install_fake_engine(monkeypatch, calls, {
            "https://public.example/bin": _Hop(200, b"\xff\xfeabc"),
        })
        resp = safe_fetch_fn("https://public.example/bin", timeout=3.0)
        assert "abc" in resp.text
