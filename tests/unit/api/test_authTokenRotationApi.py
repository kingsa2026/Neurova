"""API-03（审计 2026-11-25 批次 C）认证令牌组红绿判据。

审计发现（docs/05-reports/全仓逐文件审计报告_2026-11-25.md API-03）：
- refresh 签发新 refresh 但不撤旧 refresh（不轮换）→ 泄露的 refresh 可反复续签；
- logout 只撤 access，不撤 refresh；
- 黑名单查询异常返回 False（fail-open）→ 黑名单故障时已撤销 token 也放行；
- `verify_refresh_token` 不查黑名单（access 侧查）。

判据走真链路：真 auth 路由 + tmp 真账本（UserModel）+ tmp 真黑名单库（SQLite），
TestClient 打真端点；密钥经 `tests/auth_headers.pinJwtSecret()` 对齐（不绕身份门）。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import auth as AUTH
from neurova.auth.user_model import UserModel
from tests.auth_headers import pinJwtSecret

USERNAME = "alice"
PASSWORD = "Alice-Pw-123456"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """真 auth 路由 + tmp 真账本 + tmp 真黑名单库的最小可跑环境。"""
    pinJwtSecret()
    model = UserModel(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(AUTH, "_user_model", model)
    # 黑名单库落点改到本档临时目录：判据之间互不串库（生产取数口不变）
    monkeypatch.setattr(auth_mod, "_BLACKLIST_DB_PATH", str(tmp_path / "auth_blacklist.db"))

    from neurova.api.auth import hash_password

    model.create_user(
        username=USERNAME, password_hash=hash_password(PASSWORD), role="user"
    )

    app = FastAPI()
    app.include_router(AUTH.router, prefix="/api/v1/auth")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield {"client": client, "model": model}


def _login(env) -> dict:
    resp = env["client"].post(
        "/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert resp.status_code == 200, resp.text
    return _tokens(resp)


def _tokens(resp) -> dict:
    body = resp.json()
    return body.get("data") or body


def _breakBlacklist(monkeypatch):
    """把黑名单持久层打成不可用（判据面故障注入）。"""

    def _boom():
        raise RuntimeError("blacklist db unavailable")

    monkeypatch.setattr(auth_mod, "_blacklist_conn", _boom, raising=True)


class TestRefreshRotation:
    """refresh 必须轮换：旧 refresh 用过一次即撤销，重放拒绝。"""

    def test_oldRefreshTokenRejectedAfterRotation(self, env):
        tokens = _login(env)
        first = env["client"].post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert first.status_code == 200, first.text

        replay = env["client"].post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert replay.status_code == 401, (
            f"已轮换的旧 refresh 重放必须被拒（泄露的 refresh 不得反复续签）："
            f"{replay.status_code} {replay.text}"
        )

    def test_newRefreshTokenUsableAfterRotation(self, env):
        tokens = _login(env)
        first = env["client"].post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert first.status_code == 200, first.text
        newRefresh = _tokens(first)["refresh_token"]

        second = env["client"].post(
            "/api/v1/auth/refresh", json={"refresh_token": newRefresh}
        )
        assert second.status_code == 200, (
            f"轮换后新 refresh 必须可用：{second.status_code} {second.text}"
        )


class TestLogoutRevokesRefresh:
    """logout 必须同撤 refresh：只撤 access 等于给 refresh 留后门。"""

    def test_logoutWithRefreshTokenRevokesIt(self, env):
        tokens = _login(env)
        logout = env["client"].post(
            "/api/v1/auth/logout",
            json={"refresh_token": tokens["refresh_token"]},
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert logout.status_code == 200, logout.text

        refreshed = env["client"].post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refreshed.status_code == 401, (
            f"登出撤掉的 refresh 不得再续签：{refreshed.status_code} {refreshed.text}"
        )

    def test_logoutStillRevokesAccessWithoutBody(self, env):
        """回归护栏：不带 body 的旧客户端登出仍撤 access（契约不回退）。"""
        tokens = _login(env)
        logout = env["client"].post(
            "/api/v1/auth/logout",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert logout.status_code == 200, logout.text

        me = env["client"].get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me.status_code == 401, (
            f"登出后原 access 必须失效：{me.status_code} {me.text}"
        )


class TestBlacklistFailClosed:
    """黑名单判据面故障必须 fail-closed（显式 503），禁止吞异常放行。"""

    def test_blacklistOutageFailsClosedOnProtectedEndpoint(self, env, monkeypatch):
        tokens = _login(env)
        _breakBlacklist(monkeypatch)
        me = env["client"].get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert me.status_code == 503, (
            f"黑名单故障时已验证请求不得放行（fail-open 即撤销承诺失效）："
            f"{me.status_code} {me.text}"
        )

    def test_blacklistOutageFailsClosedOnRefresh(self, env, monkeypatch):
        tokens = _login(env)
        _breakBlacklist(monkeypatch)
        refreshed = env["client"].post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
        assert refreshed.status_code == 503, (
            f"黑名单故障时 refresh 判据不得按'未登记'放行："
            f"{refreshed.status_code} {refreshed.text}"
        )

    def test_verifyRefreshTokenHonorsBlacklist(self, env):
        """`verify_refresh_token` 与 access 侧同守一份撤销单源。"""
        tokens = _login(env)
        auth_mod.blacklist_token(tokens["refresh_token"])
        assert auth_mod.verify_refresh_token(tokens["refresh_token"]) is None, (
            "已撤销的 refresh 经 verify_refresh_token 必须判无效"
        )

    def test_blacklistOutageDoesNotLeakThroughVerifyRefresh(self, env, monkeypatch):
        tokens = _login(env)
        _breakBlacklist(monkeypatch)
        with pytest.raises(Exception) as excinfo:
            auth_mod.verify_refresh_token(tokens["refresh_token"])
        assert not isinstance(excinfo.value, type(None))
        assert "503" in str(getattr(excinfo.value, "status_code", "")) or getattr(
            excinfo.value, "status_code", None
        ) == 503, (
            f"黑名单故障必须显式失败（fail-closed），不得按未登记返回有效：{excinfo.value!r}"
        )
