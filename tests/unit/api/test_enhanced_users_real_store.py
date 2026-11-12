"""enhanced_users_api 接真实用户账本（UserModel/users.db）的咬合守卫。

断点（用户报障 2026-11-12）：该模块 8 端点全读进程内 `_users_store` 假字典——
创建的用户无法登录、改密不影响鉴权、删除的账号照常登录，页面整条写入→读取→
反馈闭环断裂。本文件钉接通后的**真账本咬合**：

- 判据核心：经端点建号/改密后，用**登录链路的同一验密函数**（auth.verify_password
  × UserModel 落库的 password_hash）能/不能通过——不是"库里有一行"而是"判据咬合"。
- 页面契约（EnhancedUserPage）：{items, total} 分页、行键 id(int)、active 布尔、
  导出按钮下载 JSON blob。
- 假面退役钉缺席：GET /{id}（页面零消费）、GET /{id}/quota（假常量）、
  POST /{id}/backup（假备份）；GET /backup 换成真导出（脱敏，无 password_hash）。
- 安全护栏：自删 409（操作者恒为 admin ⇒ 自删禁令同时保住最后一名 admin）、
  重名/重邮箱 409。
"""

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from neurova.api.deps import strictIdentityGate
from neurova.auth.user_model import UserModel


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离双桩：tmp users.db 真账本 + admin 身份门。"""
    import neurova.api.endpoints.auth as auth_ep
    from neurova.api.auth import verify_password

    model = UserModel(db_path=str(tmp_path / "users.db"))
    monkeypatch.setattr(auth_ep, "_user_model", model)

    from neurova.api.endpoints import enhanced_users_api
    from neurova.api.endpoints.settings import router as _unused  # noqa: F401 确保包可达

    app = FastAPI()
    # 与 ENDPOINT_MODULES 同前缀挂载（路由内 path 为空串，裸挂会被 FastAPI 拒）
    app.include_router(enhanced_users_api.router, prefix="/v1/enhanced-users")

    admin = {"user_id": "1", "username": "root-admin", "role": "admin",
             "neuser_id": "1", "tenant_id": "default"}
    app.dependency_overrides[strictIdentityGate] = lambda: admin
    client = TestClient(app)

    # 预置真账本里的操作者账号（id=1，admin）——与身份门 user_id 对齐
    model.create_user("root-admin", "pw-admin-000", role="admin")

    yield {"client": client, "model": model, "verify_password": verify_password}
    monkeypatch.undo()


def _create(client, **over):
    body = {"username": "alice", "email": "alice@x.com", "password": "pw-alice-123",
            "role": "user", "active": True}
    body.update(over)
    return client.post("/v1/enhanced-users", json=body)


class TestCreateBitesRealLedger:
    def test_created_user_exists_with_verified_hash(self, env):
        client, model, verify_password = env["client"], env["model"], env["verify_password"]
        r = _create(client)
        assert r.status_code == 200, r.text
        row = model.get_user_by_username("alice")
        assert row is not None, "端点建号必须落真账本（users.db），不是内存假字典"
        # 判据咬合：登录链路同一验密函数对落库哈希放行
        assert verify_password("pw-alice-123", row.password_hash) is True

    def test_duplicate_username_409(self, env):
        client = env["client"]
        assert _create(client).status_code == 200
        assert _create(client).status_code == 409

    def test_duplicate_email_409(self, env):
        client = env["client"]
        assert _create(client).status_code == 200
        r = _create(client, username="bob")
        assert r.status_code == 409

    def test_inactive_create_lands_disabled_status(self, env):
        client, model = env["client"], env["model"]
        assert _create(client, username="carol", active=False).status_code == 200
        assert model.get_user_by_username("carol").status == "disabled"


class TestListContract:
    def test_paginated_shape_and_sanitize(self, env):
        client, model = env["client"], env["model"]
        for i in range(3):
            _create(client, username=f"u{i}", email=f"u{i}@x.com")
        r = client.get("/v1/enhanced-users", params={"page": 1, "page_size": 2})
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) >= {"items", "total"} and body["total"] >= 3
        assert len(body["items"]) == 2
        item = body["items"][0]
        for key in ("id", "username", "email", "role", "active"):
            assert key in item, f"页面契约字段缺失: {key}"
        assert "password_hash" not in item and "password" not in item, "列表不得回显口令材料"
        assert isinstance(item["id"], int), "行键 id 必须是真账本 int 主键（页面 row-key='id'）"

    def test_search_filters(self, env):
        client = env["client"]
        _create(client, username="wangwei", email="ww@x.com")
        _create(client, username="lilei", email="ll@x.com")
        r = client.get("/v1/enhanced-users", params={"search": "wang"})
        names = [u["username"] for u in r.json()["items"]]
        assert names == ["wangwei"]


class TestUpdateBitesRealLedger:
    def test_update_email_role_active(self, env):
        client, model = env["client"], env["model"]
        _create(client)
        uid = model.get_user_by_username("alice").id
        r = client.put(f"/v1/enhanced-users/{uid}",
                       json={"email": "new@x.com", "role": "editor", "active": False})
        assert r.status_code == 200, r.text
        assert r.json()["active"] is False
        row = model.get_user_by_username("alice")
        assert row.email == "new@x.com" and row.role == "editor" and row.status == "disabled"

    def test_password_reset_takes_effect_on_auth(self, env):
        """断点核心判据：改密必须影响真实鉴权（旧密失效、新密过登录同款验密）。"""
        client, model, verify_password = env["client"], env["model"], env["verify_password"]
        _create(client)
        uid = model.get_user_by_username("alice").id
        old_hash = model.get_user_by_username("alice").password_hash
        r = client.put(f"/v1/enhanced-users/{uid}/password", json={"password": "brand-new-999"})
        assert r.status_code == 200, r.text
        row = model.get_user_by_username("alice")
        assert verify_password("brand-new-999", row.password_hash) is True
        assert verify_password("pw-alice-123", row.password_hash) is False, "旧密码必须失效"
        assert row.password_hash != old_hash

    def test_password_reset_unknown_user_404(self, env):
        client = env["client"]
        assert client.put("/v1/enhanced-users/99999/password",
                          json={"password": "x-1234567"}).status_code == 404


class TestDeleteGuards:
    def test_delete_removes_from_real_ledger(self, env):
        client, model = env["client"], env["model"]
        _create(client)
        uid = model.get_user_by_username("alice").id
        assert client.delete(f"/v1/enhanced-users/{uid}").status_code == 200
        assert model.get_user_by_username("alice") is None

    def test_delete_self_409(self, env):
        """操作者恒为 admin ⇒ 自删禁令同时保住最后一名 admin（无需第二道护栏）。"""
        client = env["client"]
        r = client.delete("/v1/enhanced-users/1")
        assert r.status_code == 409
        # 账号仍在（含预置操作者）
        assert env["model"].get_user_by_username("root-admin") is not None

    def test_delete_self_guard_survives_nonnumeric_sub(self, env, monkeypatch):
        """护栏不得依赖 JWT sub 可整型化——存量令牌 sub 可能是用户名（live-verify 实测旁路）。"""
        from neurova.api.deps import strictIdentityGate as _gate

        client = env["client"]
        # 存量令牌形态：sub=username（非数字），无 neuser_id 兜底
        client.app.dependency_overrides[_gate] = lambda: {
            "user_id": "root-admin", "username": "root-admin", "role": "admin",
            "neuser_id": "", "tenant_id": "default"}
        r = client.delete("/v1/enhanced-users/1")
        assert r.status_code == 409, f"非数字 sub 旁路自删护栏: {r.status_code} {r.text}"
        assert env["model"].get_user_by_username("root-admin") is not None

    def test_delete_unknown_404(self, env):
        assert env["client"].delete("/v1/enhanced-users/424242").status_code == 404


class TestExportSanitized:
    def test_backup_blob_has_no_secret_material(self, env):
        client = env["client"]
        _create(client)
        r = client.get("/v1/enhanced-users/backup")
        assert r.status_code == 200, r.text
        blob = r.content
        assert b"alice" in blob, "导出须含真实用户数据"
        assert b"pw-alice-123" not in blob and b"password_hash" not in blob, \
            "导出不得携带任何口令材料"


class TestRetiredFakeFaces:
    def test_retired_endpoints_absent(self, env):
        """假面退役钉缺席：详情/配额/单体备份三端点页面零消费，直接拔除。"""
        client = env["client"]
        # 详情路径仅剩 DELETE 方法（页面零消费 GET）→ 405 即缺席
        assert client.get("/v1/enhanced-users/1").status_code in (404, 405)
        assert client.get("/v1/enhanced-users/1/quota").status_code in (404, 405)
        assert client.post("/v1/enhanced-users/1/backup").status_code in (404, 405)


class TestAdminGate:
    def test_non_admin_forbidden(self, env, monkeypatch):
        from neurova.api.deps import strictIdentityGate as _gate

        client = env["client"]
        env["client"].app.dependency_overrides[_gate] = lambda: {
            "user_id": "9", "username": "pleb", "role": "user",
            "neuser_id": "9", "tenant_id": "default"}
        assert client.get("/v1/enhanced-users").status_code == 403
