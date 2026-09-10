"""
S-08 收口：全局鉴权白名单机制测试

审计原判：app.py 无全局 dependencies，是否鉴权靠每个端点手写，新端点默认裸奔。
本机制提供三态开关（NEUROVA_GLOBAL_AUTH）：
- off（默认，未设置）: 完全惰性，零行为变化（只提升不下降）
- shadow: 非白名单路径的匿名访问按路径去重记 INFO 日志（调用面审计取证）
- enforce: 非白名单路径必须持有效 Bearer JWT / X-Service-Token，否则 401

鉴权判定复用 neurova.api.auth（verify_access_token / 服务令牌契约），单一事实源。
"""

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.testclient import TestClient

from neurova.api.global_auth import (
    GlobalAuthMiddleware,
    PUBLIC_EXACT_PATHS,
    get_global_auth_mode,
    is_public_path,
    reset_shadow_audit,
    shadow_audit_paths,
)


@pytest.fixture
def app():
    """含受保护路由与公共路由的最小应用"""
    app = FastAPI()

    @app.get("/api/v1/secret")
    async def secret():
        return JSONResponse({"ok": True})

    @app.get("/health")
    async def health():
        return JSONResponse({"ok": True})

    app.add_middleware(GlobalAuthMiddleware)
    return app


def _client(app) -> TestClient:
    return TestClient(app, raise_server_exceptions=False)


# ─────── 白名单定义 ───────


class TestPublicPathRegistry:
    """公共路径白名单注册表"""

    def test_auth_flow_paths_are_public(self):
        """登录/注册/引导状态等首启链路必须公开"""
        required = {
            "/api/v1/auth/login",
            "/api/v1/auth/refresh",
            "/api/v1/auth/register",
            "/api/v1/auth/register/send-code",
            "/api/v1/auth/register/verify-code",
            "/api/v1/auth/setup-status",
            "/api/v1/auth/recover-password",
        }
        assert required <= PUBLIC_EXACT_PATHS

    def test_health_and_ops_are_public(self):
        """健康检查/指标/状态/前端错误上报必须公开"""
        required = {
            "/health",
            "/health/detailed",
            "/metrics",
            "/api/v1/status",
            "/api/v1/frontend/errors",
        }
        assert required <= PUBLIC_EXACT_PATHS

    def test_is_public_path_exact_match(self):
        assert is_public_path("/health") is True
        assert is_public_path("/api/v1/auth/login") is True

    def test_is_public_path_not_prefix_match(self):
        """精确匹配不做前缀扩散：/healthXXX 与 /api/v1/auth/login-evil 不公开"""
        assert is_public_path("/healthXXX") is False
        assert is_public_path("/api/v1/auth/login-evil") is False

    def test_protected_path_is_not_public(self):
        assert is_public_path("/api/v1/secret") is False
        assert is_public_path("/api/v1/auth/me") is False


# ─────── 三态行为 ───────


class TestOffMode:
    """off（默认）：完全惰性"""

    def test_unset_env_defaults_to_off(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_GLOBAL_AUTH", raising=False)
        assert get_global_auth_mode() == "off"

    def test_off_mode_allows_anonymous(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "off")
        resp = _client(app).get("/api/v1/secret")
        assert resp.status_code == 200


class TestShadowMode:
    """shadow：放行 + 匿名访问按路径去重取证"""

    def test_shadow_allows_anonymous(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "shadow")
        resp = _client(app).get("/api/v1/secret")
        assert resp.status_code == 200

    def test_shadow_dedupes_anonymous_hits(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "shadow")
        reset_shadow_audit()
        client = _client(app)
        client.get("/api/v1/secret")
        client.get("/api/v1/secret")
        client.get("/api/v1/secret")
        recorded = shadow_audit_paths()
        assert recorded == ["/api/v1/secret"]
        reset_shadow_audit()


class TestEnforceMode:
    """enforce：默认拒绝，白名单与有效凭证放行"""

    def test_enforce_rejects_anonymous(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        resp = _client(app).get("/api/v1/secret")
        assert resp.status_code == 401
        body = resp.json()
        assert body["code"] == "AUTH_FAILED"

    def test_enforce_rejects_invalid_token(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        resp = _client(app).get(
            "/api/v1/secret", headers={"Authorization": "Bearer not-a-jwt"}
        )
        assert resp.status_code == 401

    def test_enforce_accepts_valid_token(self, app, monkeypatch):
        from neurova.api.auth import create_access_token

        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        token = create_access_token({"sub": "user-1", "username": "u", "role": "user"})
        resp = _client(app).get(
            "/api/v1/secret", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200

    def test_enforce_public_path_stays_open(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        client = _client(app)
        assert client.get("/health").status_code == 200

    def test_enforce_options_preflight_passes(self, app, monkeypatch):
        """CORS 预检必须在鉴权前放行"""
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        client = _client(app)
        resp = client.options("/api/v1/secret")
        assert resp.status_code < 500

    def test_enforce_service_token_passes(self, app, monkeypatch):
        """X-Service-Token 机器调用方与 get_current_user_or_service 同契约"""
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", "svc-secret")
        resp = _client(app).get(
            "/api/v1/secret", headers={"X-Service-Token": "svc-secret"}
        )
        assert resp.status_code == 200

    def test_enforce_service_token_mismatch_rejected(self, app, monkeypatch):
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        monkeypatch.setenv("NEUROVA_SERVICE_TOKEN", "svc-secret")
        resp = _client(app).get(
            "/api/v1/secret", headers={"X-Service-Token": "wrong"}
        )
        assert resp.status_code == 401

    def test_enforce_websocket_scope_not_blocked(self, app, monkeypatch):
        """WS 握手不走 HTTP 中间件拒绝（scope type=websocket 直接透传）"""
        monkeypatch.setenv("NEUROVA_GLOBAL_AUTH", "enforce")
        # 中间件对 websocket scope 透传：直接用 scope 断言
        import asyncio

        from neurova.api.global_auth import GlobalAuthMiddleware as M

        forwarded = []

        async def dummy_app(scope, receive, send):
            forwarded.append(scope["type"])

        mw = M(dummy_app)
        scope = {"type": "websocket", "path": "/ws/abc", "headers": []}

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            pass

        asyncio.run(mw(scope, receive, send))
        assert forwarded == ["websocket"]
