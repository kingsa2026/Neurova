# -*- coding: utf-8 -*-
"""agent 部门绑定与跨部门使用门契约（specs/2026-11-07 批 D）。

红灯判据（设计 §2.6，T-D 严格绑定已裁）：
- AgentConfig 带 group_id 字段；
- agentDeptRootById：运行实例/中枢登记取 group_id → 沿 parent 链上溯部门根；
  非部门组绑定/组缺失/解析异常 → None（不设门，缺配不锁人）；
- chat 部门门：admin 不设门；agent 未绑部门不设门；说话人部门根 ≠ agent 部门根
  （含无部门用户用部门 agent）→ 拒绝文案；同根放行；
- 渠道租户对账：配置 tenant ≠ 属主部门根 → 以属主部门根为准；
  属主无部门（default）→ 保留渠道配置（不猜，行为不变）。
"""

import pytest


def testAgentConfigHasGroupId():
    from neurova.agent_core import AgentConfig

    cfg = AgentConfig(workspace_path=".", group_id="group_x")
    assert cfg.group_id == "group_x"
    default_cfg = AgentConfig(workspace_path=".")
    assert default_cfg.group_id is None


def testAgentDeptRootWalksParentChain(monkeypatch, tmp_path):
    import neurova.api.agent_access as agent_access
    from neurova.auth.user_group_model import UserGroupManager

    mgr = UserGroupManager(data_dir=str(tmp_path))
    root = mgr.create_group("研发中心", "", group_type="custom")
    child = mgr.create_group("前端组", "", group_type="custom", parent_group_id=root.group_id)

    monkeypatch.setattr("neurova.api.agent_access.get_agent_instance", lambda _id: None, raising=False)

    class _Reg:
        def get_agent(self, _id):
            return {"group_id": child.group_id}

    monkeypatch.setattr(
        "neurova.api.endpoints.agent.get_agent_config_manager", lambda: _Reg(), raising=False
    )
    monkeypatch.setattr(
        "neurova.auth.user_group_model.get_user_group_manager", lambda: mgr
    )
    assert agent_access.agentDeptRootById("agent_a") == root.group_id


def testAgentDeptRootNoneForNonDeptOrMissing(monkeypatch):
    import neurova.api.agent_access as agent_access

    monkeypatch.setattr("neurova.api.agent_access.get_agent_instance", lambda _id: None, raising=False)

    class _Reg:
        def get_agent(self, _id):
            return {"group_id": "group_missing"}

    monkeypatch.setattr(
        "neurova.api.endpoints.agent.get_agent_config_manager", lambda: _Reg(), raising=False
    )
    # 组不存在 → 不设门
    assert agent_access.agentDeptRootById("agent_a") is None

    class _RegSystem:
        def get_agent(self, _id):
            return {"group_id": "user"}  # 系统组不是部门

    monkeypatch.setattr(
        "neurova.api.endpoints.agent.get_agent_config_manager", lambda: _RegSystem(), raising=False
    )
    monkeypatch.setattr(
        "neurova.auth.user_group_model.get_user_group_manager",
        lambda: _MgrWithSystem(),
    )
    assert agent_access.agentDeptRootById("agent_a") is None


class _MgrWithSystem:
    """只带系统组的极简管理器替身。"""

    class _G:
        group_id = "user"
        group_type = None  # 非 CUSTOM
        parent_group_id = None

    def get_group(self, gid):
        return self._G() if gid == "user" else None


def testChatDeptGate(monkeypatch):
    from neurova.api.endpoints.chat import _deptGate

    monkeypatch.setattr(
        "neurova.api.agent_access.agentDeptRootById", lambda agent_id: "dept_root" if agent_id == "bound" else None
    )
    # admin 不设门
    assert _deptGate("bound", {"role": "admin", "tenant_id": "other"}) is None
    # agent 未绑部门不设门
    assert _deptGate("free", {"role": "user", "tenant_id": "other"}) is None
    # 同根放行
    assert _deptGate("bound", {"role": "user", "tenant_id": "dept_root"}) is None
    # 跨部门（含无部门用户用部门 agent）→ 拒绝文案
    assert _deptGate("bound", {"role": "user", "tenant_id": "other_dept"}) is not None
    assert _deptGate("bound", {"role": "user", "tenant_id": "default"}) is not None


def testChannelTenantReconcilesToOwnerDeptRoot(monkeypatch):
    import neurova.api.agent_access as agent_access

    monkeypatch.setattr("neurova.api.agent_access.agentOwnerById", lambda _id: "42")
    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment",
        lambda username, **kw: {"tenant_id": "dept_root", "group_id": "g", "allowed_categories": [], "restricted": False, "default_category": None},
    )

    class _Row:
        username = "alice"

    class _UM:
        def get_user_by_id(self, uid):
            return _Row()

    monkeypatch.setattr("neurova.auth.user_model.UserModel", _UM)
    # 配置租户 ≠ 属主部门根 → 对账为属主部门根
    assert agent_access.agentOwnerDeptRootById("agent_a") == "dept_root"

    # 属主无部门（default）→ 返回 default，渠道对账侧据此保留配置（行为不变）
    monkeypatch.setattr(
        "neurova.auth.user_group_model.resolveUserDepartment",
        lambda username, **kw: {"tenant_id": "default", "group_id": None, "allowed_categories": [], "restricted": False, "default_category": None},
    )
    assert agent_access.agentOwnerDeptRootById("agent_a") == "default"
