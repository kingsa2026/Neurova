"""S1 认证审计接线红绿判据。

断点：`neurova/security/audit_logger.py` 的 log_auth_login / log_auth_logout /
log_role_change 全仓零调用——登录成败/登出/角色变更不入审计（audit_logs）。
本文件钉接线后的**真链路咬合**（真端点 + tmp 真账本 + tmp 真审计库）：

- 错误密码登录 → audit_logs 出现一条 AUTH_FAILED 行（带尝试用户名/来源 IP/UA）；
- 用户不存在的失败登录 → 同样落 AUTH_FAILED，user_id 留空、尝试用户名进 details；
- 正确登录 → AUTH_LOGIN 行；
- 刷新令牌成功/失败 → 沿用 log_auth_login 的既有语义（AUTH_LOGIN / AUTH_FAILED）；
- 登出 → AUTH_LOGOUT 行（user_id 从所撤令牌解析）；
- PUT 改角色 → ROLE_CHANGE 行（old_role 取改前账本行，操作者取 admin 身份门）。

装配方式跟随 tests/unit/api/test_s2_auth_hardening.py（真 auth 路由）与
tests/unit/api/test_enhanced_users_real_store.py（tmp UserModel + 身份门覆写）。
"""

import os
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET", "s1-auth-audit-wiring-0123456789abcdef")

import neurova.security.audit_logger as AUD  # noqa: E402
from neurova.api.auth import create_refresh_token, hash_password  # noqa: E402
from neurova.api.deps import strictIdentityGate  # noqa: E402
from neurova.api.endpoints import auth as AUTH  # noqa: E402
from neurova.api.endpoints import enhanced_users_api  # noqa: E402
from neurova.auth.user_model import UserModel  # noqa: E402
from neurova.security.audit_logger import AuditEventType  # noqa: E402

ADMIN_PW = "Adm-Pw-s1-0001"
MEMBER_PW = "Mem-Pw-s1-0002"


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """真端点 + tmp 真账本 + tmp 真审计库（AuditLogger 类级单例按用例重置）。"""
    model = UserModel(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(AUTH, "_user_model", model)

    # AuditLogger 是类级单例：重置后注入 tmp 审计库，真写真读（不是桩）
    monkeypatch.setattr(AUD.AuditLogger, "_instance", None)
    audit = AUD.AuditLogger(db_path=str(tmp_path / "audit.db"))
    monkeypatch.setattr(AUD, "get_audit_logger", lambda db_path=None: audit)

    app = FastAPI()
    app.include_router(AUTH.router, prefix="/api/v1/auth")
    app.include_router(enhanced_users_api.router, prefix="/v1/enhanced-users")

    suffix = uuid.uuid4().hex[:8]
    adminName = f"s1Adm{suffix}"
    memberName = f"s1Mem{suffix}"
    model.create_user(username=adminName, password_hash=hash_password(ADMIN_PW), role="admin")
    model.create_user(username=memberName, password_hash=hash_password(MEMBER_PW), role="user")

    # admin 身份门覆写（同 test_enhanced_users_real_store：user_id 与账本 id 对齐）
    app.dependency_overrides[strictIdentityGate] = lambda: {
        "user_id": "1", "username": adminName, "role": "admin",
        "neuser_id": "1", "tenant_id": "default",
    }

    with TestClient(app, raise_server_exceptions=False) as client:
        yield {
            "client": client, "model": model, "audit": audit,
            "adminName": adminName, "memberName": memberName,
        }


def _login(client: TestClient, username: str, password: str):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def _memberId(env) -> str:
    return str(env["model"].get_user_by_username(env["memberName"]).id)


class TestLoginAuditWiring:
    def test_wrongPasswordLoginWritesAuthFailedRow(self, env):
        client, audit = env["client"], env["audit"]
        resp = _login(client, env["memberName"], "definitely-wrong-pw")
        assert resp.status_code == 401, resp.text

        rows = audit.query(event_type=AuditEventType.AUTH_FAILED)
        assert len(rows) == 1, f"错误密码登录必须落一条 AUTH_FAILED，实得 {len(rows)}"
        row = rows[0]
        assert row.action == "Login failed"
        assert row.user_id == _memberId(env), "失败审计要能归因到被尝试的账号"
        assert row.details.get("attempted_username") == env["memberName"]
        assert row.ip_address == "testclient", "审计行必须带来源 IP（request.client.host）"
        assert row.user_agent == "testclient", "审计行必须带 User-Agent"

    def test_unknownUserLoginKeepsAttemptedUsernameWithEmptyUserId(self, env):
        client, audit = env["client"], env["audit"]
        resp = _login(client, "ghost-user-s1", "whatever-pw-001")
        assert resp.status_code == 401

        rows = audit.query(event_type=AuditEventType.AUTH_FAILED)
        assert len(rows) == 1, f"用户不存在的登录失败也要落审计，实得 {len(rows)}"
        assert rows[0].user_id == "", "用户不存在时 user_id 不得臆造"
        assert rows[0].details.get("attempted_username") == "ghost-user-s1"

    def test_successfulLoginWritesAuthLoginRow(self, env):
        client, audit = env["client"], env["audit"]
        resp = _login(client, env["memberName"], MEMBER_PW)
        assert resp.status_code == 200, resp.text

        rows = audit.query(event_type=AuditEventType.AUTH_LOGIN)
        assert len(rows) == 1, f"成功登录必须落一条 AUTH_LOGIN，实得 {len(rows)}"
        assert rows[0].action == "Login successful"
        assert rows[0].user_id == _memberId(env)
        assert rows[0].ip_address == "testclient"


class TestRefreshAuditWiring:
    def test_refreshSuccessWritesAuthLoginRow(self, env):
        client, audit = env["client"], env["audit"]
        login = _login(client, env["memberName"], MEMBER_PW)
        assert login.status_code == 200
        refreshToken = login.json()["refresh_token"]

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refreshToken})
        assert resp.status_code == 200, resp.text

        rows = audit.query(event_type=AuditEventType.AUTH_LOGIN)
        assert len(rows) == 2, "登录与刷新成功各落一条 AUTH_LOGIN"
        assert {row.user_id for row in rows} == {_memberId(env)}

    def test_refreshGarbageTokenWritesAuthFailedRow(self, env):
        client, audit = env["client"], env["audit"]
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-jwt-token"})
        assert resp.status_code == 401

        rows = audit.query(event_type=AuditEventType.AUTH_FAILED)
        assert len(rows) == 1, "刷新失败（令牌不可解析）必须落 AUTH_FAILED"
        assert rows[0].user_id == "", "令牌解不出身份时 user_id 留空"

    def test_refreshUnknownUserWritesAuthFailedRowWithTokenAttribution(self, env):
        client, audit = env["client"], env["audit"]
        token = create_refresh_token(data={"sub": "424242", "username": "ghost-user-s1"})
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": token})
        assert resp.status_code == 401

        rows = audit.query(event_type=AuditEventType.AUTH_FAILED)
        assert len(rows) == 1
        assert rows[0].user_id == "424242", "令牌可解时尽力归因（sub）"
        assert rows[0].details.get("attempted_username") == "ghost-user-s1"


class TestLogoutAuditWiring:
    def test_logoutWritesAuthLogoutRow(self, env):
        client, audit = env["client"], env["audit"]
        login = _login(client, env["memberName"], MEMBER_PW)
        assert login.status_code == 200
        accessToken = login.json()["access_token"]

        resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {accessToken}"})
        assert resp.status_code == 200, resp.text

        rows = audit.query(event_type=AuditEventType.AUTH_LOGOUT)
        assert len(rows) == 1, f"登出必须落一条 AUTH_LOGOUT，实得 {len(rows)}"
        assert rows[0].user_id == _memberId(env)
        assert rows[0].action == "User logged out"
        assert rows[0].ip_address == "testclient"


class TestRoleChangeAuditWiring:
    def test_putRoleChangeWritesRoleChangeRow(self, env):
        client, model, audit = env["client"], env["model"], env["audit"]
        uid = model.get_user_by_username(env["memberName"]).id

        resp = client.put(f"/v1/enhanced-users/{uid}", json={"role": "editor"})
        assert resp.status_code == 200, resp.text
        assert model.get_user_by_id(uid).role == "editor", "角色必须真改到账本"

        rows = audit.query(event_type=AuditEventType.ROLE_CHANGE)
        assert len(rows) == 1, f"改角色必须落一条 ROLE_CHANGE，实得 {len(rows)}"
        row = rows[0]
        assert row.resource_type == "user"
        assert row.resource_id == str(uid)
        assert row.details == {"old_role": "user", "new_role": "editor"}, "old_role 必须取改前账本行"
        assert row.user_id == "1", "操作者必须是 admin 身份门标识"

    def test_putWithoutRoleFieldWritesNoRoleChangeRow(self, env):
        client, model, audit = env["client"], env["model"], env["audit"]
        uid = model.get_user_by_username(env["memberName"]).id

        resp = client.put(f"/v1/enhanced-users/{uid}", json={"email": "moved@x.com"})
        assert resp.status_code == 200, resp.text
        assert audit.query(event_type=AuditEventType.ROLE_CHANGE) == [], "未改角色不得产生 ROLE_CHANGE"
