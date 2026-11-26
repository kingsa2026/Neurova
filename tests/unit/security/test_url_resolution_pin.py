# -*- coding: utf-8 -*-
"""CORE-20：出网校验必须固定本次连接使用的 IP，不能校验后再次解析。"""

from __future__ import annotations

import socket
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from neurova import http_fetch
from neurova.security.url_guard import PublicUrlResolution, assert_public_url


def testCgnatRangeIsBlocked():
    with pytest.raises(ValueError, match="100.64.0.0/10"):
        assert_public_url("http://100.64.0.1/internal")


def testResolverReturnsValidatedAddressPlan(monkeypatch):
    from neurova.security.url_guard import resolvePublicUrl

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("2606:2800:220:1:248:1893:25c8:1946", port, 0, 0)),
        ],
    )
    plan = resolvePublicUrl("https://public.example:8443/path")
    assert plan.host == "public.example"
    assert plan.port == 8443
    assert plan.addresses == ("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946")


def testResolverRejectsIfAnyDnsAnswerIsPrivate(monkeypatch):
    from neurova.security.url_guard import resolvePublicUrl

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", port)),
        ],
    )
    with pytest.raises(ValueError, match="10.0.0.8"):
        resolvePublicUrl("https://mixed.example/path")


def testConfiguredAllowlistIsHonoredByResolver(monkeypatch):
    from neurova.security.url_guard import resolvePublicUrl

    monkeypatch.setenv("NEUROVA_SSRF_ALLOWLIST", "127.0.0.1")
    plan = resolvePublicUrl("http://127.0.0.1:19528/article")
    assert plan.addresses == ("127.0.0.1",)

    monkeypatch.setenv("NEUROVA_SSRF_ALLOWLIST", "*")
    plan = resolvePublicUrl("http://10.0.0.8:19528/article")
    assert plan.addresses == ("10.0.0.8",)


def testEmptyAddressPlanIsRejectedBeforeAnyConnection(monkeypatch):
    plan = PublicUrlResolution(
        scheme="https", host="public.example", port=443, addresses=(),
    )
    monkeypatch.setattr(
        http_fetch, "_curl_once",
        lambda *args, **kwargs: pytest.fail("空地址计划不得进入 curl"),
    )
    monkeypatch.setattr(
        http_fetch, "_urllib_once",
        lambda *args, **kwargs: pytest.fail("空地址计划不得回退 urllib"),
    )

    with pytest.raises(ValueError, match="地址计划"):
        http_fetch.request_once(
            "https://public.example/path", resolution=plan,
        )


def testFetchBytesRejectsEmptyValidatorPlanBeforeAnyConnection(monkeypatch):
    plan = PublicUrlResolution(
        scheme="https", host="public.example", port=443, addresses=(),
    )
    monkeypatch.setattr(
        http_fetch, "_curl_bytes",
        lambda *args, **kwargs: pytest.fail("空地址计划不得进入 curl"),
    )
    monkeypatch.setattr(
        http_fetch, "_urllib_bytes",
        lambda *args, **kwargs: pytest.fail("空地址计划不得回退 urllib"),
    )

    with pytest.raises(ValueError, match="地址计划"):
        http_fetch.fetch_bytes(
            "https://public.example/path", "Neurova-Test",
            url_validator=lambda url: plan,
        )


def testCurlConnectionPinsResolvedAddressesAndDisablesProxy(monkeypatch):
    from neurova.security.url_guard import PublicUrlResolution

    curl = types.ModuleType("curl_cffi")
    curl.CurlOpt = types.SimpleNamespace(RESOLVE=10204)
    requestsModule = types.ModuleType("curl_cffi.requests")
    calls = []

    class Response:
        status_code = 200
        headers = {}

        def iter_content(self, chunk_size=None):
            yield b"ok"

        def close(self):
            pass

    def request(method, url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    requestsModule.request = request
    curl.requests = requestsModule
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", requestsModule)
    monkeypatch.setattr(http_fetch, "_ascii_ca", lambda: None)
    plan = PublicUrlResolution(
        scheme="https", host="public.example", port=443,
        addresses=("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"),
    )

    result = http_fetch._curl_once(
        "https://public.example/path", "GET", {}, None, 5.0, 1024,
        resolution=plan,
    )

    assert result.content == b"ok"
    assert calls[0][0] == "https://public.example/path"
    options = calls[0][1]["curl_options"][curl.CurlOpt.RESOLVE]
    assert "public.example:443:93.184.216.34" in options
    assert any("2606:2800:220:1:248:1893:25c8:1946" in entry for entry in options)
    assert calls[0][1]["proxies"] == {}


def testFakeIpPlanIsNotDirectConnectable(monkeypatch):
    from neurova.security.url_guard import resolvePublicUrl

    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda host, port, *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("198.18.0.5", port)),
        ],
    )
    plan = resolvePublicUrl("http://public.example/x")
    assert plan.addresses == ("198.18.0.5",)
    assert plan.directConnectable is False


def testDirectEnginesRejectFakeIpPlan(monkeypatch):
    from neurova.security.url_guard import PublicUrlResolution

    plan = PublicUrlResolution(
        scheme="http", host="public.example", port=80,
        addresses=("198.18.0.5",), directConnectable=False,
    )
    with pytest.raises(ValueError, match="fake-ip"):
        http_fetch._urllib_once(
            "http://public.example/x", "GET", {}, None, 3.0, 1024,
            resolution=plan,
        )

    curl = types.ModuleType("curl_cffi")
    curl.requests = types.ModuleType("curl_cffi.requests")
    monkeypatch.setitem(sys.modules, "curl_cffi", curl)
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", curl.requests)
    with pytest.raises(ValueError, match="fake-ip"):
        http_fetch._curl_once(
            "http://public.example/x", "GET", {}, None, 3.0, 1024,
            resolution=plan,
        )


def testHttpsPinnedConnectionKeepsOriginalSni(monkeypatch):
    connected = []
    wrapped = []

    class Sock:
        def setsockopt(self, *args):
            pass

    def create_connection(address, timeout, source_address):
        connected.append(address)
        return Sock()

    class Context:
        def wrap_socket(self, sock, server_hostname):
            wrapped.append(server_hostname)
            return sock

    monkeypatch.setattr(socket, "create_connection", create_connection)
    connection = http_fetch._PinnedHTTPSConnection(
        "public.example", port=443, pinnedAddress="93.184.216.34",
    )
    connection._context = Context()
    connection.connect()

    assert connected == [("93.184.216.34", 443)]
    assert wrapped == ["public.example"]


def testUrllibConnectionPinsNumericAddressButKeepsOriginalHost(monkeypatch):
    from neurova.security.url_guard import PublicUrlResolution

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("Host"))
            body = b"pinned"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        plan = PublicUrlResolution(
            scheme="http", host="public.example", port=port,
            addresses=("127.0.0.1",),
        )
        result = http_fetch._urllib_once(
            f"http://public.example:{port}/path", "GET", {}, None, 3.0, 1024,
            resolution=plan,
        )
        assert result.content == b"pinned"
        assert received == [f"public.example:{port}"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
