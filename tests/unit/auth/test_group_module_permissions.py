"""用户组功能模块权限（allowed_modules）闭环测试。

契约（2026-09-05 用户组菜单权限适配）：
1. UserGroup 持久化 allowed_modules / members，旧 JSON（无新字段）可正常加载；
2. UserGroupManager 补齐成员管理三方法（groups_api 原本调用但不存在 → 运行时 500）；
   系统组的 allowed_modules 可设置（运营配置），name/description 仍受保护；
3. groups_api 契约：PUT /{id} 的 allowed_modules 真正落库（原传对象签名错位 →
   自定义组 setattr 污染、系统组静默丢弃）；POST members 走 body{username}
   （原读 Query user_id 与前端断链）；GET /{id}/members 端点存在（原缺失 405）；
4. /auth/me 返回 allowed_modules（所属组并集；不在任何组 → 空数组 = 不限制）。
"""

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault(
    "NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_group_modules_0123456789"
)

from neurova.auth.user_group_model import UserGroup, UserGroupManager

# ---------------------------------------------------------------------------
# 模型层
# ---------------------------------------------------------------------------


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "grpdata"


@pytest.fixture
def manager(data_dir):
    return UserGroupManager(data_dir=str(data_dir))


class TestUserGroupModel:
    def test_allowed_modules_persisted_across_reload(self, manager, data_dir):
        g = manager.create_group(name="受限组", description="")
        manager.set_allowed_modules(g.group_id, ["/chat", "/agent/:id/memory"])

        reloaded = UserGroupManager(data_dir=str(data_dir))
        assert reloaded.get_group(g.group_id).allowed_modules == [
            "/chat",
            "/agent/:id/memory",
        ]

    def test_system_group_allowed_modules_settable(self, manager):
        updated = manager.set_allowed_modules("user", ["/chat"])
        assert updated is not None
        assert manager.get_group("user").allowed_modules == ["/chat"]

    def test_set_allowed_modules_unknown_group_returns_none(self, manager):
        assert manager.set_allowed_modules("group_missing", ["/chat"]) is None

    def test_member_management_roundtrip(self, manager):
        g = manager.create_group(name="成员组", description="")
        assert manager.get_group_members(g.group_id) == []
        assert manager.add_user_to_group("alice", g.group_id) is True
        assert manager.add_user_to_group("alice", g.group_id) is True  # 去重
        assert manager.get_group_members(g.group_id) == ["alice"]
        assert manager.remove_user_from_group("alice", g.group_id) is True
        assert manager.get_group_members(g.group_id) == []
        assert manager.remove_user_from_group("alice", g.group_id) is False

    def test_member_unknown_group_rejected(self, manager):
        assert manager.add_user_to_group("alice", "group_missing") is False

    def test_get_groups_for_user_union(self, manager):
        g1 = manager.create_group(name="a", description="")
        g2 = manager.create_group(name="b", description="")
        manager.set_allowed_modules(g1.group_id, ["/chat"])
        manager.set_allowed_modules(g2.group_id, ["/chat", "/agents"])
        manager.add_user_to_group("bob", g1.group_id)
        manager.add_user_to_group("bob", g2.group_id)

        assert {g.group_id for g in manager.get_groups_for_user("bob")} == {
            g1.group_id,
            g2.group_id,
        }
        assert manager.get_allowed_modules_for_user("bob") == ["/agents", "/chat"]

    def test_user_without_group_unrestricted(self, manager):
        assert manager.get_allowed_modules_for_user("nobody") == []

    def test_group_with_unconfigured_modules_treated_unrestricted(self, manager):
        g = manager.create_group(name="未配置组", description="")
        manager.add_user_to_group("carol", g.group_id)
        # 组未勾选任何模块 → 不限制（向后兼容：旧组全可见）
        assert manager.get_allowed_modules_for_user("carol") == []

    def test_from_dict_legacy_without_new_fields(self):
        legacy = {
            "group_id": "group_x",
            "name": "旧组",
            "description": "",
            "group_type": "custom",
            "permissions": ["user:read"],
            "resource_quota": {"max_agents": 1},
        }
        g = UserGroup.from_dict(legacy)
        assert g.allowed_modules == []
        assert g.members == []


# ---------------------------------------------------------------------------
# groups_api 契约
# ---------------------------------------------------------------------------

from neurova.api.deps import get_current_user
from neurova.api.endpoints import groups_api

MOCK_ADMIN = {"user_id": "1", "username": "adminuser", "role": "admin"}


@pytest.fixture
def client(monkeypatch, manager):
    a = FastAPI()
    a.include_router(groups_api.router, prefix="/api/v1/groups")
    monkeypatch.setattr(groups_api, "get_user_group_manager", lambda: manager)
    a.dependency_overrides[get_current_user] = lambda: MOCK_ADMIN
    with TestClient(a) as c:
        yield c
    a.dependency_overrides.clear()


class TestGroupsApiModules:
    def test_create_group_with_allowed_modules(self, client, manager):
        r = client.post(
            "/api/v1/groups",
            json={"name": "市场组", "allowed_modules": ["/marketplace", "/benchmark"]},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["allowed_modules"] == ["/marketplace", "/benchmark"]
        assert body["group_id"]

    def test_list_groups_returns_allowed_modules(self, client, manager):
        g = manager.create_group(name="清单组", description="")
        manager.set_allowed_modules(g.group_id, ["/chat"])
        r = client.get("/api/v1/groups")
        assert r.status_code == 200
        matched = [x for x in r.json() if x["group_id"] == g.group_id]
        assert matched and matched[0]["allowed_modules"] == ["/chat"]

    def test_put_allowed_modules_persists(self, client, manager):
        g = manager.create_group(name="编辑组", description="旧描述")
        r = client.put(
            f"/api/v1/groups/{g.group_id}",
            json={"description": "新描述", "allowed_modules": ["/agents"]},
        )
        assert r.status_code == 200, r.text
        assert r.json()["allowed_modules"] == ["/agents"]
        # 真正落库（原实现传对象给 update_group → 静默丢失）
        assert manager.get_group(g.group_id).allowed_modules == ["/agents"]
        assert manager.get_group(g.group_id).description == "新描述"
        # 名字未传时不被污染
        assert manager.get_group(g.group_id).name == "编辑组"

    def test_put_allowed_modules_on_system_group(self, client, manager):
        r = client.put("/api/v1/groups/user", json={"allowed_modules": ["/chat"]})
        assert r.status_code == 200, r.text
        assert r.json()["allowed_modules"] == ["/chat"]
        assert manager.get_group("user").allowed_modules == ["/chat"]

    def test_add_member_by_username_body(self, client, manager):
        g = manager.create_group(name="成员API组", description="")
        r = client.post(
            f"/api/v1/groups/{g.group_id}/members", json={"username": "alice"}
        )
        assert r.status_code == 200, r.text
        assert manager.get_group_members(g.group_id) == ["alice"]

    def test_get_members_endpoint(self, client, manager):
        g = manager.create_group(name="成员列表组", description="")
        manager.add_user_to_group("alice", g.group_id)
        r = client.get(f"/api/v1/groups/{g.group_id}/members")
        assert r.status_code == 200, r.text
        assert r.json() == [{"id": "alice", "username": "alice"}]

    def test_remove_member(self, client, manager):
        g = manager.create_group(name="移除组", description="")
        manager.add_user_to_group("alice", g.group_id)
        r = client.delete(f"/api/v1/groups/{g.group_id}/members/alice")
        assert r.status_code == 200, r.text
        assert manager.get_group_members(g.group_id) == []


# ---------------------------------------------------------------------------
# /auth/me 返回 allowed_modules
# ---------------------------------------------------------------------------

from neurova.api.auth import create_access_token
from neurova.api.endpoints import auth as auth_endpoint


@pytest.fixture
def me_client():
    a = FastAPI()
    a.include_router(auth_endpoint.router, prefix="/api/v1/auth")
    return TestClient(a)


def _token(username: str, role: str = "user") -> str:
    return create_access_token(
        data={
            "sub": "2",
            "username": username,
            "neuser_id": "2",
            "user_id": "2",
            "role": role,
        }
    )


class TestMeAllowedModules:
    def test_me_returns_union_of_groups(self, monkeypatch, manager, me_client):
        g = manager.create_group(name="限制组", description="")
        manager.set_allowed_modules(g.group_id, ["/chat"])
        manager.add_user_to_group("alice", g.group_id)
        monkeypatch.setattr(
            "neurova.auth.user_group_model.get_user_group_manager", lambda: manager
        )
        r = me_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {_token('alice')}"}
        )
        assert r.status_code == 200, r.text
        assert r.json()["allowed_modules"] == ["/chat"]

    def test_me_user_without_group_returns_empty(self, monkeypatch, manager, me_client):
        monkeypatch.setattr(
            "neurova.auth.user_group_model.get_user_group_manager", lambda: manager
        )
        r = me_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {_token('nobody')}"}
        )
        assert r.status_code == 200
        assert r.json()["allowed_modules"] == []

    def test_me_manager_failure_still_ok(self, monkeypatch, me_client):
        def _boom():
            raise RuntimeError("service down")

        monkeypatch.setattr(
            "neurova.auth.user_group_model.get_user_group_manager", _boom
        )
        r = me_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {_token('alice')}"}
        )
        # 权限计算失败不影响 /auth/me 本身（fail-open，前端视为不限制）
        assert r.status_code == 200
        assert r.json()["allowed_modules"] == []
