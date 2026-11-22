# -*- coding: utf-8 -*-
"""S6 安全响应头移层 + 补全（拍板 D-S4：HSTS 仅 NEUROVA_FORCE_HTTPS=1 时发）。

原缺陷：SecurityHeadersMiddleware 装配在 GlobalAuth/RateLimit **内层**
（add_middleware 先注册=内层），401/429 短路响应根本不经过它——未带 token
打受保护端点的 401 一只安全头都没有。

本卡判据（红→绿）：
① enforce 模式 401 响应必须带全部安全头；
② HSTS 仅当 NEUROVA_FORCE_HTTPS=1 时出现，未设时不得出现；
③ 正常 200 响应同样带头（移层不得丢内层已覆盖的头）。

装配顺序走行为面断言：401 能带头 = SecurityHeaders 已在 GlobalAuth 外层。
应用经生产装配点 `setup_middleware` 构建，不手工重排中间件。
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from neurova.api.middleware import setup_middleware

#: 全量必发安全头期望值（字面量独立于实现，防同源互证）
EXPECTED_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Content-Security-Policy": "frame-ancestors 'none'",
}

HSTS_VALUE = "max-age=31536000; includeSubDomains"


@pytest.fixture
def app():
    """走生产装配 setup_middleware 的最小应用（中间件顺序 = 生产顺序）"""
    app = FastAPI()

    @app.get("/api/v1/secret")
    async def secret():
        return JSONResponse({"ok": True})

    @app.get("/health")
    async def health():
        return JSONResponse({"ok": True})

    setup_middleware(app)
    return app


def _client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


class TestSecurityHeadersOnShortCircuit:
    """401 短路响应也必须带安全头（移层判据）"""

    def testUnauthorizedCarriesAllSecurityHeaders(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        monkeypatch.delenv("NEUROVA_FORCE_HTTPS", raising=False)

        resp = _client(app).get("/api/v1/secret")
        assert resp.status_code == 401
        for name, value in EXPECTED_HEADERS.items():
            assert resp.headers.get(name) == value, f"401 响应缺安全头 {name}"
        assert "Strict-Transport-Security" not in resp.headers

    def testHstsOnlyWhenForceHttps(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")

        monkeypatch.setenv("NEUROVA_FORCE_HTTPS", "1")
        resp = _client(app).get("/api/v1/secret")
        assert resp.status_code == 401
        assert resp.headers.get("Strict-Transport-Security") == HSTS_VALUE

        monkeypatch.delenv("NEUROVA_FORCE_HTTPS", raising=False)
        resp = _client(app).get("/api/v1/secret")
        assert resp.status_code == 401
        assert "Strict-Transport-Security" not in resp.headers


class TestSecurityHeadersOnNormalResponse:
    """200 响应带头（回归保护）"""

    def testOkCarriesAllSecurityHeaders(self, app, monkeypatch):
        monkeypatch.delenv("NEUROVA_GLOBAL_AUTH", raising=False)
        monkeypatch.delenv("NEUROVA_FORCE_HTTPS", raising=False)

        resp = _client(app).get("/health")
        assert resp.status_code == 200
        for name, value in EXPECTED_HEADERS.items():
            assert resp.headers.get(name) == value, f"200 响应缺安全头 {name}"
        assert "Strict-Transport-Security" not in resp.headers
