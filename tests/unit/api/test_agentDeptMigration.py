# -*- coding: utf-8 -*-
"""用户换部门 → 名下 agent 迁移到新部门组（用户需求 2026-11-12）。

语义：组成员变更（加入/移出部门组）后，该用户名下所有 agent 的部门绑定
跟随解析后的新部门组（resolveUserDepartment 单源）；绑定三处同步
（运行实例 config / workspace 配置文件 / agents.json 登记 config 合并写）
—— 与 update_agent 端点的落盘形态同款。幂等：已在新组的 agent 跳过；
用户无部门组（解析 None/default）不动任何 agent；非该用户的 agent 不碰。
"""

from enum import Enum
from types import SimpleNamespace

import pytest

from neurova.api import agent_access
from neurova.auth.user_group_model import UserGroupType


class _FakeGroup:
    def __init__(self, group_id, name="g", group_type=UserGroupType.CUSTOM, parent=None, members=None):
        # group_type 用真枚举：resolveUserDepartment 按 `== UserGroupType.CUSTOM` 过滤
        # （纯 Enum，字符串字面量 "custom" 不等值——夹具曾因此恒判无部门）。
        self.group_id = group_id
        self.name = name
        self.group_type = group_type
        self.parent_group_id = parent
        self.members = list(members or [])
        # resolveUserDepartment 沿链读这两属性（缺属性=AttributeError→except 回 default）
        self.allowed_categories = []
        self.default_category = None


class _FakeManager:
    """resolveUserDepartment 的最小替身：custom 组链 + 成员表。"""

    def __init__(self, groups):
        self._groups = {g.group_id: g for g in groups}

    def get_groups_for_user(self, username):
        return [g for g in self._groups.values() if username in g.members]

    def get_group(self, group_id):
        return self._groups.get(group_id)


class _FakeRegistry:
    """AgentConfigManager 替身（list/get/update 同签名，dict 基底）。"""

    def __init__(self, records):
        self._records = {r["id"]: r for r in records}
        self.updates = []

    def list_agents(self):
        return [{"id": r["id"]} for r in self._records.values()]

    def get_agent(self, agent_id):
        return self._records.get(agent_id)

    def update_agent(self, agent_id, updates):
        if agent_id not in self._records:
            return False
        self._records[agent_id].update(updates)
        self.updates.append((agent_id, updates))
        return True


@pytest.fixture
def wired(monkeypatch):
    """标准场景：alice 在部门 A（dept-a），名下 agent a1（绑 A）+ a2（未绑）；
    另有 bob 的 agent b1（绑 B2）不可被迁移。"""
    dept_a = _FakeGroup("dept-a", name="部门A", members=["alice"])
    dept_b1 = _FakeGroup("dept-b1", name="部门B1", parent="dept-b-root", members=[])
    dept_b_root = _FakeGroup("dept-b-root", name="部门B", members=[])
    manager = _FakeManager([dept_a, dept_b1, dept_b_root])

    registry = _FakeRegistry([
        {"id": "a1", "owner_user_id": "111", "config": {"group_id": "dept-a", "model": "m1"}},
        {"id": "a2", "owner_user_id": "111", "config": {"model": "m2"}},
        {"id": "b1", "owner_user_id": "222", "config": {"group_id": "dept-b1"}},
    ])

    state_agents = {
        "a1": SimpleNamespace(config=SimpleNamespace(group_id="dept-a", owner_user_id="111")),
        "a2": SimpleNamespace(config=SimpleNamespace(group_id=None, owner_user_id="111")),
        "b1": SimpleNamespace(config=SimpleNamespace(group_id="dept-b1", owner_user_id="222")),
    }

    saved_agents = []
    monkeypatch.setattr(
        "neurova.api.endpoints.agent._save_agent_config",
        lambda agent: saved_agents.append(agent),
        raising=False,
    )

    class _UserRow:
        id = 111
        username = "alice"

    class _UserModel:
        def get_user_by_username(self, username):
            if username == "alice":
                return _UserRow()
            return None

    monkeypatch.setattr(
        "neurova.auth.user_model.UserModel", _UserModel, raising=False)

    return {
        "manager": manager,
        "registry": registry,
        "state_agents": state_agents,
        "saved": saved_agents,
        "dept_a": dept_a,
        "dept_b1": dept_b1,
        "dept_b_root": dept_b_root,
    }


def _fakeDeptRegistry():
    """分类注册表替身（空表）：resolveUserDepartment 的对表步骤走注入而非真单例。"""
    return SimpleNamespace(list=lambda activeOnly=True: [])


def _alice_into_b(wired):
    """把 alice 加入部门 B1（模拟管理员换部门），返回迁移读数。"""
    wired["dept_b1"].members.append("alice")
    wired["dept_a"].members.remove("alice")
    return agent_access.migrateUserAgentsToDept(
        "alice", manager=wired["manager"], registry=wired["registry"],
        state_agents=wired["state_agents"], dept_registry=_fakeDeptRegistry(),
    )


class TestMigrateUserAgentsToDept:
    def test_switch_dept_migrates_all_owned_agents(self, wired):
        """红灯判据本体：换部门后名下所有 agent 三处同步迁到新部门组。"""
        readout = _alice_into_b(wired)

        assert readout["new_group_id"] == "dept-b1"
        migrated = {m["agent_id"]: m for m in readout["migrated"]}
        assert set(migrated) == {"a1", "a2"}, (
            f"迁移面不全：{sorted(migrated)}——名下 agent 有遗漏")
        assert migrated["a1"]["from"] == "dept-a" and migrated["a1"]["to"] == "dept-b1"
        assert migrated["a2"]["from"] is None

        # 三处同步：实例 config / 配置文件 / 登记合并写
        assert wired["state_agents"]["a1"].config.group_id == "dept-b1"
        assert wired["state_agents"]["a2"].config.group_id == "dept-b1"
        assert len(wired["saved"]) == 2, (
            f"配置文件落盘次数不对：{len(wired['saved'])}")
        assert wired["saved"][0] is wired["state_agents"]["a1"], (
            "配置文件落盘没落到被迁移的 agent 上")
        reg_updates = dict(wired["registry"].updates)
        # 登记合并写：group_id 进 config 子字典，model 不丢
        a1_cfg = reg_updates["a1"]["config"]
        assert a1_cfg["group_id"] == "dept-b1" and a1_cfg["model"] == "m1", (
            f"登记合并写丢了其他键：{a1_cfg}")

    def test_bobs_agents_untouched(self, wired):
        """越权防线：非该用户的 agent 纹丝不动。"""
        _alice_into_b(wired)
        assert wired["registry"].get_agent("b1")["config"]["group_id"] == "dept-b1"
        assert wired["state_agents"]["b1"].config.group_id == "dept-b1"

    def test_idempotent_second_run_migrates_nothing(self, wired):
        _alice_into_b(wired)
        again = agent_access.migrateUserAgentsToDept(
            "alice", manager=wired["manager"], registry=wired["registry"],
            state_agents=wired["state_agents"], dept_registry=_fakeDeptRegistry(),
        )
        assert again["migrated"] == [], "重复迁移非幂等"
        assert again["new_group_id"] == "dept-b1"

    def test_no_department_user_untouched(self, wired):
        """无部门组（解析 None）不动任何 agent——语义钉死：解析不出就不猜。"""
        wired["dept_a"].members.remove("alice")  # 无主组
        readout = agent_access.migrateUserAgentsToDept(
            "alice", manager=wired["manager"], registry=wired["registry"],
            state_agents=wired["state_agents"], dept_registry=_fakeDeptRegistry(),
        )
        assert readout["new_group_id"] is None
        assert readout["migrated"] == []
        assert wired["state_agents"]["a1"].config.group_id == "dept-a"

    def test_unknown_username_untouched(self, wired):
        """不存在的用户：部门解析先决（无部门先于查表）→ no_department，不动任何 agent。

        两个 reason（no_department/user_not_found）都不改变行为——判据是"不动"，
        reason 只承载读数细分。
        """
        readout = agent_access.migrateUserAgentsToDept(
            "ghost", manager=wired["manager"], registry=wired["registry"],
            state_agents=wired["state_agents"], dept_registry=_fakeDeptRegistry(),
        )
        assert readout["migrated"] == []
        assert readout.get("reason") == "no_department"
        assert wired["state_agents"]["a1"].config.group_id == "dept-a"


class TestMemberChangeEndpointsTrigger:
    def test_add_member_triggers_migration(self, monkeypatch):
        """接线格：加入部门组成功后迁移被以该 username 触发。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import neurova.api.endpoints.groups_api as groups_api
        from neurova.api.deps import strictIdentityGate

        calls = []
        # 端点内是 lazy import（`from neurova.api.agent_access import ...` 每次现取
        # 模块属性）——patch 真源模块属性，patch groups_api 侧无效。
        monkeypatch.setattr(agent_access, "migrateUserAgentsToDept",
                            lambda username, **kw: calls.append(username) or {"migrated": []})
        manager = SimpleNamespace(
            get_group=lambda gid: SimpleNamespace(group_id=gid),
            add_user_to_group=lambda u, g: True,
        )
        monkeypatch.setattr(groups_api, "_require_manager", lambda: manager)

        app = FastAPI()
        app.include_router(groups_api.router, prefix="/groups")
        # 401 源是 require_admin 闭包内 Depends(strictIdentityGate)（Bearer 校验）——
        # override 其本体（闭包引用同一对象）；override require_admin 工厂无效，
        # 路由在 import 时已固化 check_role 闭包。
        app.dependency_overrides[strictIdentityGate] = lambda: {
            "user_id": "1", "username": "admin", "role": "admin"}
        client = TestClient(app)

        r = client.post("/groups/dept-b1/members", json={"username": "alice"})
        assert r.status_code == 200, r.text
        assert calls == ["alice"], (
            f"加入部门组后迁移未被触发：{calls}")

    def test_remove_member_triggers_migration(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import neurova.api.endpoints.groups_api as groups_api
        from neurova.api.deps import strictIdentityGate

        calls = []
        monkeypatch.setattr(agent_access, "migrateUserAgentsToDept",
                            lambda username, **kw: calls.append(username) or {"migrated": []})
        manager = SimpleNamespace(
            get_group=lambda gid: SimpleNamespace(group_id=gid),
            remove_user_from_group=lambda u, g: True,
        )
        monkeypatch.setattr(groups_api, "_require_manager", lambda: manager)

        app = FastAPI()
        app.include_router(groups_api.router, prefix="/groups")
        app.dependency_overrides[strictIdentityGate] = lambda: {
            "user_id": "1", "username": "admin", "role": "admin"}
        client = TestClient(app)

        r = client.delete("/groups/dept-a/members/alice")
        assert r.status_code == 200, r.text
        assert calls == ["alice"], f"移出部门组后迁移未被触发：{calls}"
