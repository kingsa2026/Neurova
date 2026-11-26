# -*- coding: utf-8 -*-
"""CORE-20 R5：MCP 长连接传输固定已验证 IP，禁止校验后再次解析。"""

from __future__ import annotations

import asyncio
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from neurova.knowledge import mcp_source
from neurova.security.mcp_transport import pinnedMcpTransport
from neurova.security.url_guard import PublicUrlResolution


def testPinnedTransportKeepsHostAndUsesResolvedAddress():
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            received.append(self.headers.get("Host"))
            body = b"mcp-ok"
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
        transport = pinnedMcpTransport(plan)

        async def fetch():
            import httpx2

            async with httpx2.AsyncClient(transport=transport, trust_env=False) as client:
                response = await client.get(f"http://public.example:{port}/mcp")
                return response.status_code, response.text

        status, body = asyncio.run(fetch())
        assert status == 200
        assert body == "mcp-ok"
        assert received == [f"public.example:{port}"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.asyncio
async def testOpenSourceSessionRejectsPrivateBeforeTransport(monkeypatch):
    def forbiddenTransport(_resolution):
        pytest.fail("私网 endpoint 不得进入传输层")

    class ForbiddenHttpx:
        class AsyncClient:
            async def __aenter__(self):
                raise AssertionError("私网 endpoint 不得创建 HTTP 客户端")

            async def __aexit__(self, *args):
                return False

    monkeypatch.setitem(sys.modules, "httpx", ForbiddenHttpx)
    monkeypatch.setattr(mcp_source, "pinnedMcpTransport", forbiddenTransport, raising=False)

    with pytest.raises(ValueError, match="127.0.0.1"):
        async with mcp_source.openSourceSession({"endpoint": "http://127.0.0.1:9000/mcp"}):
            pass


class _Context:
    def __init__(self, value):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["http", "sse"])
async def testToolLayerMcpUsesPinnedTransport(monkeypatch, transport):
    import httpx2
    from neurova.security import mcp_transport
    from neurova.tool_layers import mcp_client

    captured = {}
    sentinelTransport = object()
    session = SimpleNamespace(initialize=AsyncMock())

    class FakeClient:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    def fake_streamable(url, *, http_client):
        captured["http_client"] = http_client
        return _Context((object(), object()))

    def fake_sse(url, **kwargs):
        captured["sse_kwargs"] = kwargs
        factory = kwargs["httpx_client_factory"]
        captured["http_client"] = factory()
        return _Context((object(), object()))

    monkeypatch.setattr(mcp_transport, "pinnedMcpTransport", lambda resolution: sentinelTransport)
    monkeypatch.setattr(httpx2, "AsyncClient", FakeClient)
    monkeypatch.setattr(mcp_client, "_SDK_AVAILABLE", True)
    monkeypatch.setattr(mcp_client, "ClientSession", lambda *args: _Context(session))
    monkeypatch.setattr(mcp_client, "streamable_http_client", fake_streamable)
    monkeypatch.setattr(mcp_client, "sse_client", fake_sse)

    client = mcp_client.MCPToolClient()
    result = await client._open_session(
        "srv", {"transport": transport, "url": "http://1.2.3.4/mcp", "headers": {}},
    )

    assert result is session
    assert captured["transport"] is sentinelTransport
    assert captured["trust_env"] is False

