# -*- coding: utf-8 -*-
"""S13 项目/团队/群聊的 agent 工具面——红灯（超越方案 S13 批，波5 会话K）。

四组红灯（方案 S13 节 + 附录 A/B）：
① project_create：agent 发起项目成功——owner=属主用户、initiator=agent 标、
   project_id=room_id 等式成立（创建即建房间）、审计可查、预算入账；
   public 对 agent 拒绝（L2 保留给人）。
② 加人类成员（memberUserIds）触发 L1 ASK——未批准不生效，批准（decide 工具
   路径回灌）后写入；可见性放宽 team 同走 ASK。
③ room_post：非成员被拒；成员发言落房间历史（kind 语义）；限频拦截。
④ 四工具（project_create/project_list/project_detail/room_post）对成员不可见：
   MAIN_AGENT_ONLY_TOOLS 声明 + 执行咽喉成员上下文结构化拒绝。
⑤（波M 移交项①）成员工具面剔除集并集收口：单源于 builtin_tools.MAIN_AGENT_ONLY_TOOLS，
   swarm 自有第二份声明退役；白名单派生期即不含全部成员专属工具。
⑥（波M 移交项②）项目治理 ASK 的房间裁决回灌：房间裁决端点批准后经
   applyProjectGovernanceDecision 生效（成员加入/可见性变更落地），审计带 decided_by_channel。
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_agent_project_tools_0123456789")

import pytest

import neurova.collaboration.collaboration_isolation as isoModule
from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager
from neurova.security.approval_manager import ApprovalManager
from neurova.security.approval_relay import installApprovalRelay

NEW_PROJECT_TOOLS = ("project_create", "project_list", "project_detail", "room_post")


# ── 夹具：数据面互相隔离的临时目录 ──────────────────────────────────


@pytest.fixture
def collab(tmp_path, monkeypatch):
    """项目数据单源：collaboration_isolation 管理器指向临时目录。"""
    mgr = CollaborationIsolationManager(data_dir=str(tmp_path / "collaboration"))
    monkeypatch.setattr(isoModule, "_collaboration_manager", mgr)
    yield mgr
    isoModule.reset_collaboration_manager()


@pytest.fixture
def approvals(tmp_path, monkeypatch):
    """审批链：等待预算置 0（提交即 pending），审批存储指向临时目录。"""
    monkeypatch.setenv("NEUROVA_SWARM_APPROVAL_WAIT_S", "0")
    mgr = ApprovalManager(str(tmp_path / "approval_project"))
    assert installApprovalRelay(mgr) is True
    with patch("neurova.security.approval_manager.get_approval_manager", return_value=mgr):
        yield mgr


@pytest.fixture
def auditDb(tmp_path, monkeypatch):
    """审计单例整体重定向到 tmp_path（写入与查询同落这份）。"""
    import neurova.security.audit_logger as auditModule

    savedInstance = auditModule.AuditLogger._instance
    savedGlobal = auditModule._audit_logger
    auditModule.AuditLogger._instance = None
    auditModule._audit_logger = None
    auditLogger = auditModule.AuditLogger(db_path=str(tmp_path / "audit.db"))
    auditModule._audit_logger = auditLogger
    yield auditLogger
    auditModule.AuditLogger._instance = savedInstance
    auditModule._audit_logger = savedGlobal


class _FakeRepo:
    """房间消息假仓库（RoomStore 注入用，记录 save_message 形参）。"""

    def __init__(self):
        self.rows = []

    def save_message(self, agent_id, session_id, role, content, metadata=None, *, user_id=""):
        self.rows.append({
            "agent_id": agent_id, "session_id": session_id, "role": role,
            "content": content, "metadata": dict(metadata or {}), "user_id": user_id,
        })
        return True

    def get_history(self, agent_id, session_id, max_messages=0):
        return [r for r in self.rows if r["agent_id"] == agent_id and r["session_id"] == session_id]


@pytest.fixture
def roomStore(monkeypatch):
    from neurova.collaboration.room_store import RoomStore

    fake = _FakeRepo()
    monkeypatch.setattr("neurova.collaboration.room_store._store", RoomStore(repo=fake))
    yield fake


@pytest.fixture
def roomBus(monkeypatch):
    """房间广播桩：避免单测触达真实 WS 管理器；落库面由 roomStore 覆盖。"""

    class _StubBus:
        async def publish(self, *args, **kwargs):
            return 0

    monkeypatch.setattr("neurova.collaboration.room_bus.get_room_bus", lambda: _StubBus())


@pytest.fixture
def executor():
    agent = MagicMock()
    agent.current_session_id = "sess-main"
    agent.agent_id = "yi_ling"
    agent._current_user_id = "1001"  # 请求级身份（唯一身份通道的请求边界值）
    agent.config = SimpleNamespace(agent_id="yi_ling", name="主代理", owner_user_id="1001")
    from neurova.tool_executor import ToolExecutor

    return ToolExecutor(agent), agent


@pytest.fixture
def ledgerMock():
    with patch("neurova.collaboration.cost_ledger_integration.on_collaboration_event") as mock:
        yield mock


# ── ① project_create：agent 发起项目（审计可查 + 房间成立 + 入账） ────


class TestProjectCreate:
    @pytest.mark.asyncio
    async def test_agent_creates_project_with_audit_and_room(self, collab, approvals, auditDb,
                                                             roomStore, executor, ledgerMock):
        exe, _ = executor
        result = await exe._execute_project_create({
            "name": "蜂群周报项目",
            "description": "由主代理发起的周报整理项目",
            "visibility": "private",
        })
        assert result.get("success") is True, result
        projectId = result["project_id"]
        assert projectId, "应返回 project_id"
        # 创建即建房间：project_id = room_id 等式成立
        assert result.get("room_id") == projectId
        # owner 记为发起 agent 的属主用户；initiator=agent 标写入项目数据
        project = collab.get_project(projectId)
        assert project is not None, "项目应已落库（collaboration_isolation 单源）"
        assert project.owner_id == "1001"
        assert (project.metadata or {}).get("initiator") == "agent"
        assert (project.metadata or {}).get("initiator_agent_id") == "yi_ling"
        # 发起 agent 自动成为成员（否则 room_post 成员判据会把它挡在门外）
        assert project.is_member("yi_ling")

        # 强制审计可查：按 resource_id=project_id 查到 project_create 台账行
        entries = auditLoggerQuery(auditDb, resource_id=projectId)
        assert any(
            e.action == "project_create" and (e.details or {}).get("initiator") == "agent"
            for e in entries
        ), "审计库必须能查到 agent 发起的项目创建台账"

        # 预算入账：项目创建事件进成本账本出口
        ledgerMock.assert_called_once()
        assert ledgerMock.call_args.args[0] == "project_created"

    @pytest.mark.asyncio
    async def test_public_visibility_reserved_for_human(self, collab, approvals, auditDb, executor):
        exe, _ = executor
        result = await exe._execute_project_create({
            "name": "对外项目", "visibility": "public",
        })
        assert result.get("success") is not True
        assert result.get("code") == "visibility_l2_reserved_for_human"
        assert collab.list_projects() == [], "public 请求不得建出项目"

    @pytest.mark.asyncio
    async def test_missing_name_rejected(self, collab, approvals, auditDb, executor):
        exe, _ = executor
        assert "error" in await exe._execute_project_create({})


def auditLoggerQuery(auditDb, **kwargs):
    return auditDb.query(**kwargs)


# ── ② 加人类成员触发 ASK：未批准不生效，批准后写入 ───────────────────


class TestProjectGovernanceAsk:
    @pytest.mark.asyncio
    async def test_human_member_pending_until_approved(self, collab, approvals, auditDb, executor):
        exe, _ = executor
        result = await exe._execute_project_create({
            "name": "含人类成员项目",
            "description": "agent 拉人入项目",
            "visibility": "private",
            "memberUserIds": ["2002"],
        })
        assert result.get("success") is True, result
        assert result.get("governance_pending") is True, "加人类成员必须触发 L1 ASK"
        assert result.get("request_id"), "应返回审批单 id"
        projectId = result["project_id"]

        project = collab.get_project(projectId)
        assert "2002" not in project.members, "未批准：人类成员不得写入"

        decided = await exe._execute_decide_approval({
            "request_id": result["request_id"], "decision": "approve", "note": "同意加入",
        })
        assert decided.get("success") is True, decided
        project = collab.get_project(projectId)
        assert "2002" in project.members, "批准后人类成员应写入"
        assert project.get_member("2002") is not None

    @pytest.mark.asyncio
    async def test_human_member_rejected_stays_out(self, collab, approvals, auditDb, executor):
        exe, _ = executor
        result = await exe._execute_project_create({
            "name": "驳回项目", "memberUserIds": ["2003"],
        })
        assert result.get("governance_pending") is True
        decided = await exe._execute_decide_approval({
            "request_id": result["request_id"], "decision": "reject",
        })
        assert decided.get("success") is True
        project = collab.get_project(result["project_id"])
        assert "2003" not in project.members, "驳回后人类成员不得写入"

    @pytest.mark.asyncio
    async def test_team_visibility_widening_requires_ask(self, collab, approvals, auditDb, executor):
        exe, _ = executor
        result = await exe._execute_project_create({
            "name": "团队可见项目", "visibility": "team",
        })
        assert result.get("success") is True
        assert result.get("governance_pending") is True, "可见性放宽 team 必须走 L1 ASK"
        project = collab.get_project(result["project_id"])
        assert project.visibility.value == "private", "未批准：可见性保持 private"

        decided = await exe._execute_decide_approval({
            "request_id": result["request_id"], "decision": "approve",
        })
        assert decided.get("success") is True
        project = collab.get_project(result["project_id"])
        assert project.visibility.value == "team", "批准后可见性放宽为 team"


# ── ③ room_post：非成员被拒；成员发言落房间历史；限频 ────────────────


class TestRoomPost:
    @pytest.mark.asyncio
    async def test_non_member_rejected(self, collab, approvals, auditDb, roomStore, executor):
        exe, _ = executor
        # 属主直建项目（agent 不是成员）
        proj = collab.create_project(name="别人的房间", owner_id="1001")
        out = await exe._execute_room_post({
            "project_id": proj.project_id, "message": "路过发言", "kind": "note",
        })
        assert out.get("success") is not True
        assert out.get("code") == "not_room_member"
        assert roomStore.rows == [], "被拒发言不得落库"

    @pytest.mark.asyncio
    async def test_member_post_lands_in_room_history(self, collab, approvals, auditDb,
                                                     roomStore, executor):
        exe, _ = executor
        created = await exe._execute_project_create({"name": "发言项目", "visibility": "private"})
        assert created.get("success") is True
        out = await exe._execute_room_post({
            "project_id": created["project_id"], "message": "第一阶段完成", "kind": "report",
        })
        assert out.get("success") is True, out
        assert out.get("room_id") == created["project_id"]
        assert len(roomStore.rows) == 1
        row = roomStore.rows[0]
        assert row["agent_id"] == created["project_id"], "房间消息以 room_id=project_id 落库"
        assert row["content"] == "第一阶段完成"
        assert row["metadata"].get("sender_type") == "agent"
        assert row["metadata"].get("sender_id") == "yi_ling"
        assert row["metadata"].get("kind") == "report"

    @pytest.mark.asyncio
    async def test_invalid_kind_rejected(self, collab, approvals, auditDb, roomStore, executor):
        exe, _ = executor
        created = await exe._execute_project_create({"name": "kind校验项目"})
        out = await exe._execute_room_post({
            "project_id": created["project_id"], "message": "x", "kind": "spam",
        })
        assert out.get("success") is not True
        assert "kind" in out.get("error", "")

    @pytest.mark.asyncio
    async def test_rate_limit_blocks_flood(self, collab, approvals, auditDb, roomStore,
                                           executor, monkeypatch):
        from neurova.tool_executor import ToolExecutor
        import neurova.tool_executor as teModule

        monkeypatch.setattr(ToolExecutor, "ROOM_POST_RATE_LIMIT_MAX", 2)
        monkeypatch.setattr(teModule, "_roomPostTimestamps", {})
        exe, _ = executor
        created = await exe._execute_project_create({"name": "限频项目"})
        pid = created["project_id"]
        assert (await exe._execute_room_post({"project_id": pid, "message": "1"})).get("success")
        assert (await exe._execute_room_post({"project_id": pid, "message": "2"})).get("success")
        third = await exe._execute_room_post({"project_id": pid, "message": "3"})
        assert third.get("success") is not True
        assert third.get("code") == "rate_limited", "超限发言必须被限频拦截"


# ── ④ 四工具对成员不可见（声明 + 执行咽喉拒绝） ──────────────────────


class TestHiddenFromMembers:
    def test_declared_main_agent_only_and_schemas_registered(self):
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, MAIN_AGENT_ONLY_TOOLS

        for name in NEW_PROJECT_TOOLS:
            assert name in _BUILTIN_SCHEMAS, f"{name} 未注册 schema"
            assert name in MAIN_AGENT_ONLY_TOOLS, f"{name} 未进主 agent 专属声明集"

    def test_reproducible_flags(self):
        from neurova.builtin_tools import is_builtin_tool_reproducible

        assert is_builtin_tool_reproducible("project_create") is False
        assert is_builtin_tool_reproducible("room_post") is False
        assert is_builtin_tool_reproducible("project_list") is True
        assert is_builtin_tool_reproducible("project_detail") is True

    @pytest.mark.asyncio
    async def test_member_context_rejected_at_executor_gate(self, executor):
        """成员上下文（白名单已绑定）调用主 agent 专属工具 → 结构化拒绝。

        用真实成员工具面（computeSubagentToolAllowlist("general")）作白名单——
        声明集收口后白名单派生期已剔除主 agent 专属工具（见
        TestMemberExclusionSingleSource），执行咽喉成员门保留为纵深防御。
        """
        from neurova.agent.swarm import computeSubagentToolAllowlist
        from neurova.core.turn_context import set_subagent_tool_allowlist

        exe, _ = executor
        set_subagent_tool_allowlist(computeSubagentToolAllowlist("general"))
        try:
            out = await exe._execute_single_tool("project_create", {"name": "成员越权"})
            assert out.get("code") == "subagent_tool_not_allowed", out
            out = await exe._execute_single_tool("room_post", {"project_id": "p", "message": "m"})
            assert out.get("code") == "subagent_tool_not_allowed", out
        finally:
            set_subagent_tool_allowlist(None)

    @pytest.mark.asyncio
    async def test_main_agent_context_not_blocked_by_gate(self, collab, approvals, auditDb,
                                                          roomStore, executor):
        """主代理上下文（无白名单）走同一入口 → 不被成员门拦截，正常到达执行体。"""
        exe, _ = executor
        out = await exe._execute_single_tool("project_create", {"name": "主代理建的项目"})
        assert out.get("code") != "subagent_tool_not_allowed", out
        assert out.get("success") is True, out


# ── ⑤ 移交项①（波M）：成员工具面剔除集并集收口单源 ──────────────────


class TestMemberExclusionSingleSource:
    """S13 声明集（MAIN_AGENT_ONLY_TOOLS）与 S10 声明集（MEMBER_EXCLUDED_TOOLS）
    语义同为"成员工具面剔除集"，收口为单一事实源（教义第 6 条）；并集收口后
    白名单派生期即不含全部成员专属工具，执行咽喉成员门降为纵深防御。"""

    def test_union_declared_at_single_source(self):
        import neurova.agent.swarm as swarmModule
        from neurova.builtin_tools import _BUILTIN_SCHEMAS, MAIN_AGENT_ONLY_TOOLS

        assert not hasattr(swarmModule, "MEMBER_EXCLUDED_TOOLS"), (
            "成员工具面剔除集必须单源于 builtin_tools.MAIN_AGENT_ONLY_TOOLS"
            "（swarm 自有第二份声明即教义第 6 条违规）"
        )
        assert MAIN_AGENT_ONLY_TOOLS == frozenset({
            # 递归派生/续跑/裁决/叫停（P3-1 与 H 批先例）
            "spawn_subagent", "continue_subagent", "decide_subagent_approval",
            "cancel_subagent",
            # 团队编排三工具（S10）
            "list_teams", "dispatch_team", "propose_team",
            # 项目/群聊四工具（S13）
            "project_create", "project_list", "project_detail", "room_post",
        }), "剔除集=全部成员专属工具并集（缺一即成员面泄漏）"
        unknown = MAIN_AGENT_ONLY_TOOLS - set(_BUILTIN_SCHEMAS)
        assert not unknown, f"剔除集不得含未注册幻名: {sorted(unknown)}"

    def test_member_allowlist_derivation_excludes_all_main_agent_tools(self):
        """白名单派生期（computeSubagentToolAllowlist）即剔除全部主 agent 专属工具
        ——不得再靠执行咽喉门兜底（S13 移交的并集未收口问题）。"""
        from neurova.builtin_tools import MAIN_AGENT_ONLY_TOOLS
        from neurova.agent.swarm import computeSubagentToolAllowlist

        for subagentType in ("general", "explore"):
            allow = computeSubagentToolAllowlist(subagentType)
            leaked = allow & MAIN_AGENT_ONLY_TOOLS
            assert not leaked, (
                f"{subagentType} 成员工具面仍含主 agent 专属工具: {sorted(leaked)}"
            )


# ── ⑥ 移交项②（波M）：项目治理 ASK 的房间裁决回灌 ───────────────────


class TestRoomAdjudicationOfGovernanceAsk:
    """S13 治理 ASK（人类成员写入/可见性放宽）此前只有 decide_subagent_approval
    工具路径能回灌生效；房间裁决端点（S9）批准后不生效——等待预算耗尽仅记录。
    按 S10 团队沉淀同构补齐：房间裁决批准 → applyProjectGovernanceDecision 回灌。"""

    @pytest.mark.asyncio
    async def test_room_owner_decision_applies_governance(
        self, collab, approvals, auditDb, roomStore, roomBus, executor,
    ):
        from neurova.api.endpoints import collaboration_room_api as roomApi

        exe, _ = executor
        created = await exe._execute_project_create({
            "name": "房间裁决项目",
            "description": "治理 ASK 走房间裁决",
            "visibility": "team",
            "memberUserIds": ["2002"],
        })
        assert created.get("governance_pending") is True, created
        projectId = created["project_id"]
        project = collab.get_project(projectId)
        assert "2002" not in project.members, "未裁决：人类成员不得写入"
        assert project.visibility.value == "private", "未裁决：可见性保持 private"

        # 房间裁决端点：群主（项目 owner=属主用户 1001）显式批准
        res = await roomApi.decide_room_approval(
            projectId, created["request_id"],
            roomApi.ApprovalDecisionBody(decision="approve", note="同意加入并放宽"),
            current_user={"user_id": "1001", "role": "member"},
        )
        data = res["data"]
        assert data.get("success") is True, data
        assert data.get("project_governance_applied", {}).get("applied") is True, (
            "房间裁决批准后必须回灌项目治理申请（applyProjectGovernanceDecision）"
        )

        project = collab.get_project(projectId)
        assert "2002" in project.members, "房间裁决批准后人类成员应写入"
        assert project.visibility.value == "team", "房间裁决批准后可见性应放宽"

        # 审计照 S8 口径：回灌生效行带 decided_by_channel=room
        appliedRows = [
            e for e in auditLoggerQuery(auditDb, resource_id=projectId)
            if e.action == "project_governance_applied"
        ]
        assert appliedRows, "房间裁决回灌必须落审计台账"
        assert appliedRows[-1].details.get("decided_by_channel") == "room", (
            "回灌生效审计须照 S8 口径落 decided_by_channel"
        )

    @pytest.mark.asyncio
    async def test_room_member_rejected_governance_stays_out(
        self, collab, approvals, auditDb, roomStore, roomBus, executor,
    ):
        """房间驳回：快照不生效（成员不写入），登记已清（不复活）。"""
        from neurova.api.endpoints import collaboration_room_api as roomApi

        exe, _ = executor
        created = await exe._execute_project_create({
            "name": "房间驳回项目", "memberUserIds": ["2003"],
        })
        assert created.get("governance_pending") is True
        res = await roomApi.decide_room_approval(
            created["project_id"], created["request_id"],
            roomApi.ApprovalDecisionBody(decision="reject", note="暂不拉人"),
            current_user={"user_id": "1001", "role": "member"},
        )
        assert res["data"].get("success") is True, res
        project = collab.get_project(created["project_id"])
        assert "2003" not in project.members, "房间驳回后人类成员不得写入"
