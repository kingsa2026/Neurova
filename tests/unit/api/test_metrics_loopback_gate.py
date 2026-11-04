# -*- coding: utf-8 -*-
"""P2-1（审计 2026-11-04）裁定实施：/metrics 与 /health/detailed 限环回。

缺陷：enforce 模式下这两条路径在 PUBLIC_EXACT_PATHS 全白名单——容器绑
0.0.0.0 时外部匿名可读路径级调用量/时延。

裁定（2026-11-04）：限环回——容器/本机 healthcheck（都在容器内＝环回）
照常匿名读；非环回匿名访问按未鉴权处理（持凭证仍可读）。
/global_auth 中间件为纯 ASGI，直接以真中间件 + 注入 scope 的 client 地址验证。
"""
import asyncio
import unittest.mock as _mock

import pytest

from neurova.api.global_auth import (
    LOOPBACK_ONLY_PUBLIC_PATHS,
    GlobalAuthMiddleware,
    MODE_ENFORCE,
    reset_shadow_audit,
)


class _StubApp:
    """白名单放行后的下游替身：记录命中并回 200（只关心鉴权判决，不关心业务）。"""

    def __init__(self):
        self.reached = []

    async def __call__(self, scope, receive, send):
        self.reached.append(scope["path"])
        await send({"type": "http.response.start", "status": 200,
                    "headers": [(b"content-type", b"application/json")]})
        await send({"type": "http.response.body", "body": b"{}"})


def _call(middleware, path, client_addr, method="GET"):
    """直驱纯 ASGI 中间件，返回 (status, 最后命中的下游路径或 None)。"""
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "method": method, "path": path,
        "headers": [(b"host", b"test")], "client": client_addr,
        "query_string": b"",
    }
    asyncio.run(middleware(scope, receive, send))
    status = next((m["status"] for m in sent if m["type"] == "http.response.start"), None)
    return status, (middleware.app.reached[-1] if middleware.app.reached else None)


@pytest.fixture()
def mw():
    return GlobalAuthMiddleware(_StubApp())


@pytest.fixture(autouse=True)
def enforce_mode(monkeypatch):
    monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", MODE_ENFORCE)
    reset_shadow_audit()


class TestLoopbackOnlyPaths:
    def test_metrics_still_listed_as_loopback_public(self):
        assert {"/metrics", "/health/detailed"} <= LOOPBACK_ONLY_PUBLIC_PATHS

    def test_metrics_external_anonymous_is_401(self, mw):
        status, reached = _call(mw, "/metrics", ("10.0.0.5", 51000))
        assert status == 401, f"外部匿名可读 /metrics（下游被命中: {reached}）"
        assert reached is None, "401 时不得放行到下游"

    def test_metrics_loopback_anonymous_reaches_app(self, mw):
        status, reached = _call(mw, "/metrics", ("127.0.0.1", 51000))
        assert status == 200
        assert reached == "/metrics", "容器内/本机 healthcheck 必须照常匿名可读"

    def test_health_detailed_external_anonymous_is_401(self, mw):
        status, _ = _call(mw, "/health/detailed", ("192.168.1.9", 51000))
        assert status == 401

    def test_metrics_external_with_credentials_passes(self):
        """限环回只收匿名面：持有效凭证的外部读不受影响。"""
        stub = _StubApp()
        mw = GlobalAuthMiddleware(stub)
        with _mock.patch("neurova.api.global_auth.authenticateRequest",
                         return_value={"user_id": "op", "role": "admin"}):
            status, reached = _call(mw, "/metrics", ("10.0.0.5", 51000))
        assert status == 200 and reached == "/metrics", "持凭证外部读不得被限环回误伤"

    def test_health_stays_fully_public(self, mw):
        status, reached = _call(mw, "/health", ("10.0.0.5", 51000))
        assert status == 200 and reached == "/health", "/health 是 healthcheck 面，保持全公开"


class TestOffModeUnchanged:
    def test_off_mode_still_inert(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "off")
        mw = GlobalAuthMiddleware(_StubApp())
        status, reached = _call(mw, "/metrics", ("10.0.0.5", 51000))
        assert status == 200 and reached == "/metrics", "off 默认零行为变化（契约不回退）"
