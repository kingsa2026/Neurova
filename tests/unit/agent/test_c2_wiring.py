# -*- coding: utf-8 -*-
"""C2 接线卡：G3 收敛面（NeuacpMemberSurface）四方法接入编排入口。

消解「有面无调用方」缺口——四个方法各自拿到编排入口（工具/端点）：

1. fork：continue_subagent 增可选 ``mode=fork`` → updateSubagent 路由到
   ``surface.fork``：派生新 run（新 member 会话、resumed_from 溯源），原 run
   不叫停不改动；外部成员未声明 fork → 诚实拒绝（CapabilityNotDeclared 文案）；
   内部 agent（caps None）放行。
2. rollback：新工具 ``rollback_subagent`` → SwarmManager.rollbackSubagent →
   ``surface.rollback``：真恢复 member 会话到最近检查点（事务化）；无检查点/
   恢复失败诚实 success=false；未声明 conversation_rollback 拒绝。
3. switchModel：resumeFinishedRun 的切换分支（D-B 五结果决策）改经
   ``surface.switchModel`` 做能力闸+决策（源码断言钉住禁止绕过；D-B 行为零变化）。
4. snapshot：console 子代理事件读面改经 ``surface.snapshot`` 取数（同一账本
   单源，读面换道、响应形状不变）。

schema 增量：continue_subagent.mode 扩到 steer/restart/resume/fork（可选，wire
向后兼容）；rollback_subagent 进注册名册/成员剔除集/不可重放名单/分发表。

造数纪律（同 D-B/G3 测试）：run 一律真 SubAgentRun + transitionRun 迁移终态；
能力档一律真 catalog 出口形状；替身只放边界（名册/身份/探测/spawn 协作方）。
"""
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import neurova.agent.neuacp.catalog as neuacp_catalog
from neurova.agent.neuacp.catalog import capabilitiesFor
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SwarmManager,
    SubAgentRun,
    computeSubagentToolAllowlist,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_support import transitionRun
from neurova.builtin_tools import (
    _BUILTIN_SCHEMAS,
    _NON_REPRODUCIBLE_TOOLS,
    MAIN_AGENT_ONLY_TOOLS,
    get_builtin_tool_params,
    get_registered_tool_names,
)

pytestmark = pytest.mark.timeout(120)


# ── 边界替身与造数助手（与 D-B / G3 测试同形） ───────────────────────────


def patchRoster(monkeypatch, members, tenant="default"):
    import neurova.api.endpoints.teams_api as teams_api

    def _roster(tid):
        return {"id": tid, "name": "测试团队", "tenant_id": tenant,
                "members_detail": members}

    monkeypatch.setattr(teams_api, "getTeamRoster", _roster)


def patchIdentity(monkeypatch, *, tenant="default", user="user-1", admin=False):
    from neurova.core import identity_context

    monkeypatch.setattr(identity_context, "get_request_user_id", lambda: user)
    import neurova.auth.user_group_model as groups

    monkeypatch.setattr(groups, "resolveUserDepartment",
                        lambda username: {"tenant_id": tenant})
    import neurova.agent.approval_chain as approval_chain

    monkeypatch.setattr(approval_chain, "_deciderIsPlatformAdmin",
                        lambda actor: admin)


def patchExternalOn(monkeypatch):
    monkeypatch.setenv("NEUROVA_EXTERNAL_AGENTS_ENABLED", "on")


def patchProbe(monkeypatch, installed=True):
    monkeypatch.setattr(
        neuacp_catalog, "probeToolHealth",
        lambda tool, **kw: {"tool": tool, "installed": installed,
                            "install_hint": "", "version": None, "error": None})


def patchCatalogCaps(monkeypatch, tool, **dims):
    entry = dict(neuacp_catalog.CATALOG.get(tool) or {})
    caps = dict(entry.get("capabilities") or {})
    caps.update(dims)
    entry["capabilities"] = caps
    monkeypatch.setitem(neuacp_catalog.CATALOG, tool, entry)


def acpCaps(**extra):
    caps = capabilitiesFor("opencode")
    caps.update(extra)
    return caps


def makeRun(sid, *, agent_id="ext-1", team_id="team-1", tenant_id="default",
            member_session_id="msess-1", report="旧产出结论",
            status=SUBAGENT_COMPLETED, caps=None, tool="", model=""):
    run = SubAgentRun(
        subagent_id=sid, agent_id=agent_id, agent_name="外部成员",
        task="旧任务书", origin="chat", session_id="sess-old",
        member_session_id=member_session_id, team_id=team_id,
        tenant_id=tenant_id, report=report,
    )
    if status in (SUBAGENT_RUNNING, SUBAGENT_COMPLETED):
        transitionRun(run, SUBAGENT_RUNNING, cause="test")
    if status == SUBAGENT_COMPLETED:
        transitionRun(run, SUBAGENT_COMPLETED, cause="test")
    if caps is not None:
        run.executor_caps_snapshot = caps
        run.executor_tool = tool
        run.executor_model = model
    return run


def registerRun(swarm, run):
    with swarm._lock:
        swarm._runs[run.subagent_id] = run


def makeStreamAgent(reply="分支完成"):
    """chat 一步完成的假子 Agent（内部成员执行体替身，边界处使用）。"""
    agent = MagicMock()
    agent.config.name = "内部成员"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


def decisionEvent(swarm, sid):
    events = swarm.runEvents(sid).get("events", [])
    matched = [e for e in events if e.get("type") == "resume_decision"]
    assert matched, "resume_decision 事件必须落账"
    return matched[-1]


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


@pytest.fixture()
def checkpointEnv(tmp_path, monkeypatch):
    """检查点/会话落点隔离 + git 身份兜底（与 test_adapter_surface 同纪律）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_SESSIONS_DIR", str(tmp_path / "sessions"))
    for key, val in (("GIT_AUTHOR_NAME", "neurova-test"),
                     ("GIT_AUTHOR_EMAIL", "neurova-test@example.com"),
                     ("GIT_COMMITTER_NAME", "neurova-test"),
                     ("GIT_COMMITTER_EMAIL", "neurova-test@example.com")):
        monkeypatch.setenv(key, val)
    from neurova.session_manager import SessionManager

    SessionManager._instance = None
    yield tmp_path
    SessionManager._instance = None


# ── 1. fork：continue_subagent mode=fork → surface.fork ──────────────────


class TestForkWiring:
    @pytest.mark.asyncio
    async def test_fork_mode_derives_branch_run_and_leaves_original_untouched(
            self, swarm):
        """mode=fork → 真派生新 run：resumed_from 溯源、新 member 会话；
        原 run 不叫停不改动（同对象同状态同产出，仍在册）。"""
        old = makeRun("c2-fork-1", team_id="", member_session_id="msess-f1")
        registerRun(swarm, old)
        agent = makeStreamAgent("分支完成")

        with patch("neurova.api.endpoints.get_agent_instance",
                   return_value=agent):
            result = await swarm.updateSubagent(
                old.subagent_id, "分支任务：换条路试", mode="fork")

        assert result.get("error") is None, result
        assert result.get("rejected") is None, result
        # 新分支 run：溯源指向原 run，member 会话是新的（fork 不复用原会话）
        assert result.get("resumed_from") == old.subagent_id
        assert result.get("subagent_id") != old.subagent_id
        assert result.get("member_session_id") not in (None, "", old.member_session_id)
        assert result.get("status") == "completed"
        # 新 run 在册，且任务书就是分支指令
        branch = swarm._runs.get(result["subagent_id"])
        assert branch is not None
        assert branch.resumed_from == old.subagent_id
        # 原 run 不叫停不改动：同一对象、状态/产出/会话键原样
        assert swarm._runs.get(old.subagent_id) is old
        assert old.status == SUBAGENT_COMPLETED
        assert old.report == "旧产出结论"
        assert old.member_session_id == "msess-f1"

    @pytest.mark.asyncio
    async def test_fork_mode_on_running_run_leaves_it_running(self, swarm, monkeypatch):
        """对进行中的原 run fork：派生分支、原 run 保持运行中不被叫停。"""
        old = makeRun("c2-fork-2", team_id="", status=SUBAGENT_RUNNING,
                      member_session_id="msess-f2")
        registerRun(swarm, old)
        spawnMock = AsyncMock(return_value={"subagent_id": "run-branch",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)

        result = await swarm.updateSubagent(old.subagent_id, "分支任务", mode="fork")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        assert spawnMock.await_args.args[0] == "分支任务"
        assert kwargs.get("resumed_from") == old.subagent_id
        assert kwargs.get("reuse_member_session_id") is None, "fork 不复用原会话"
        # 原 run 仍运行中、未被改动
        assert old.status == SUBAGENT_RUNNING
        assert swarm._runs.get(old.subagent_id) is old

    @pytest.mark.asyncio
    async def test_fork_external_member_undeclared_rejected(self, swarm, monkeypatch):
        """外部成员能力档未声明 fork → 诚实拒绝（CapabilityNotDeclared 文案），不派生。"""
        patchIdentity(monkeypatch)
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [{
            "user_id": "ext-1", "name": "外部成员", "role": "coder",
            "prompt": "负责编码",
            "executor": {"kind": "acp", "tool": "opencode",
                         "command": ["echo", "opencode"], "cwd": "."}}])
        old = makeRun("c2-fork-3", caps=acpCaps(), tool="opencode")  # 保守档：fork False
        registerRun(swarm, old)
        spawnMock = AsyncMock(return_value={"subagent_id": "run-x"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)

        result = await swarm.updateSubagent(old.subagent_id, "分支任务", mode="fork")

        assert result.get("success") is False, result
        assert "fork" in str(result.get("error", "")), result
        assert "能力未声明" in str(result.get("error", "")), result
        assert spawnMock.await_count == 0, "闸拒绝时不得派生"
        assert swarm._runs.get(old.subagent_id) is old

    @pytest.mark.asyncio
    async def test_fork_internal_agent_noneCaps_passes(self, swarm, monkeypatch):
        """内部 agent（caps None）→ 闸放行（不设限惯例，同 C5）。"""
        old = makeRun("c2-fork-4", team_id="")
        registerRun(swarm, old)
        spawnMock = AsyncMock(return_value={"subagent_id": "run-branch",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)

        result = await swarm.updateSubagent(old.subagent_id, "分支任务", mode="fork")

        assert spawnMock.await_count == 1, result
        assert spawnMock.await_args.kwargs.get("resumed_from") == old.subagent_id

    @pytest.mark.asyncio
    async def test_updateSubagent_rejects_unknown_mode(self, swarm):
        """未知 mode → 结构化拒绝（不静默当 steer）。"""
        old = makeRun("c2-fork-5", team_id="")
        registerRun(swarm, old)

        result = await swarm.updateSubagent(old.subagent_id, "x", mode="bogus")
        assert result.get("success") is False
        assert "mode" in str(result.get("error", ""))


# ── 2. rollback：rollback_subagent 工具 → surface.rollback ───────────────


class TestRollbackWiring:
    def test_rollback_restores_member_session_to_latest_checkpoint(
            self, swarm, checkpointEnv):
        """真机制：经 rollbackSubagent 把 member 会话恢复到最近检查点。"""
        from neurova.checkpoints.service import CheckpointService
        from neurova.session_manager import SessionManager

        agentId, memberSession = "c2-rb-agent", "msess-c2rb1"
        sm = SessionManager()
        sm.save_message(agent_id=agentId, session_id=memberSession,
                        role="user", content="第一轮输入")
        service = CheckpointService(agent_id=agentId, debounce_seconds=0)
        ref = service.snapshot_auto(memberSession, {"messages": [
            {"role": "user", "content": "第一轮输入"}]})
        # 检查点之后又推进了一轮（"未来"消息）
        sm.save_message(agent_id=agentId, session_id=memberSession,
                        role="assistant", content="第二轮回复")

        run = makeRun("c2-rb-1", agent_id=agentId, team_id="",
                      member_session_id=memberSession,
                      caps={"conversation_rollback": True})
        registerRun(swarm, run)

        result = swarm.rollbackSubagent(run.subagent_id)

        assert result.get("success") is True, result
        assert result.get("restored_ref") == ref
        assert result.get("pre_restore_ref"), "恢复前必须留 pre-restore 快照"
        history = sm.get_history(agentId, memberSession)
        contents = [str(m.get("content") or "") for m in history]
        assert "第二轮回复" not in contents, "回滚后不得残留检查点之后的轮次"
        assert "第一轮输入" in contents

    def test_rollback_without_checkpoint_honest_failure(self, swarm, checkpointEnv):
        """无检查点可回 → 诚实失败（success=false + 原因），不静默当成功。"""
        run = makeRun("c2-rb-2", agent_id="c2-rb-agent-2", team_id="",
                      member_session_id="msess-none",
                      caps={"conversation_rollback": True})
        registerRun(swarm, run)

        result = swarm.rollbackSubagent(run.subagent_id)

        assert result.get("success") is False
        assert "检查点" in str(result.get("error", ""))

    def test_rollback_undeclared_capability_rejected(self, swarm, checkpointEnv):
        """外部成员未声明 conversation_rollback → 诚实拒绝（能力闸文案）。"""
        run = makeRun("c2-rb-3", caps=acpCaps())  # 保守档：rollback False
        registerRun(swarm, run)

        result = swarm.rollbackSubagent(run.subagent_id)

        assert result.get("success") is False
        assert "conversation_rollback" in str(result.get("error", ""))

    def test_rollback_unknown_id_rejected(self, swarm):
        result = swarm.rollbackSubagent("swarm-nope")
        assert result.get("success") is False
        assert "未找到" in str(result.get("error", ""))

    def test_rollback_tool_schema_registered(self):
        """rollback_subagent 进注册面/成员剔除集/不可重放名单/分发表。"""
        assert "rollback_subagent" in _BUILTIN_SCHEMAS
        assert "rollback_subagent" in get_registered_tool_names()
        assert "rollback_subagent" in MAIN_AGENT_ONLY_TOOLS
        assert "rollback_subagent" in _NON_REPRODUCIBLE_TOOLS
        from neurova.tool_executor import ToolExecutor

        assert "rollback_subagent" in ToolExecutor._builtin_dispatch
        # 成员工具面剔除（主 agent 专属）
        assert "rollback_subagent" not in computeSubagentToolAllowlist("general")
        schema = get_builtin_tool_params("rollback_subagent")
        assert schema is not None
        assert schema["parameters"]["required"] == ["subagent_id"]
        assert "command_id" in schema["parameters"]["properties"]
        assert len(schema["description"]) <= 600, "description 超出全量预算"

    @pytest.mark.asyncio
    async def test_rollback_tool_executor_dispatches(self):
        """工具分发：rollback_subagent → swarm.rollbackSubagent（subagent_id+command_id）。"""
        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(MagicMock())
        fakeSwarm = MagicMock()
        fakeSwarm.rollbackSubagent = MagicMock(return_value={"success": True})
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=fakeSwarm):
            result = await exe._execute_rollback_subagent(
                {"subagent_id": "swarm-x", "command_id": "cmd-rb-1"})

        assert result == {"success": True}
        fakeSwarm.rollbackSubagent.assert_called_once_with(
            "swarm-x", command_id="cmd-rb-1")

    @pytest.mark.asyncio
    async def test_rollback_tool_requires_subagent_id(self):
        from neurova.tool_executor import ToolExecutor

        exe = ToolExecutor(MagicMock())
        result = await exe._execute_rollback_subagent({})
        assert result.get("success") is False
        assert "subagent_id" in str(result.get("error", ""))


# ── 3. switchModel：resumeFinishedRun 切换分支改经 surface.switchModel ────


class TestSwitchModelWiring:
    @pytest.mark.asyncio
    async def test_switch_branch_declared_reaches_switch_model_in_session(
            self, swarm, monkeypatch):
        """D-B 场景复验（经面）：声明 model_switch_in_session → 会话内换模型。"""
        patchIdentity(monkeypatch)
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [{
            "user_id": "ext-1", "name": "外部成员", "role": "coder",
            "prompt": "负责编码",
            "executor": {"kind": "acp", "tool": "opencode",
                         "command": ["echo", "opencode"], "cwd": "."}}])
        patchCatalogCaps(monkeypatch, "opencode", model_switch_in_session=True)
        patchProbe(monkeypatch, True)
        monkeypatch.setattr(SwarmManager, "_resolve_model_name",
                            staticmethod(lambda agent: "model-b"))
        old = makeRun("c2-sw-1", caps=acpCaps(model_switch_in_session=True),
                      tool="opencode", model="model-a")
        registerRun(swarm, old)
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        assert kwargs.get("reuse_member_session_id") == old.member_session_id
        assert result.get("provider_transition") == "switch_model_in_session"
        payload = decisionEvent(swarm, old.subagent_id)["payload"]
        assert payload["decision"] == "switch_model_in_session"
        assert payload["model_changed"] is True

    @pytest.mark.asyncio
    async def test_switch_branch_undeclared_rejects_via_surface(
            self, swarm, monkeypatch):
        """D-B 场景复验（经面）：未声明 → 诚实拒绝，决策事件 reject，不派生。"""
        patchIdentity(monkeypatch)
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [{
            "user_id": "ext-1", "name": "外部成员", "role": "coder",
            "prompt": "负责编码",
            "executor": {"kind": "acp", "tool": "opencode",
                         "command": ["echo", "opencode"], "cwd": "."}}])
        patchProbe(monkeypatch, True)
        monkeypatch.setattr(SwarmManager, "_resolve_model_name",
                            staticmethod(lambda agent: "model-b"))
        old = makeRun("c2-sw-2", caps=acpCaps(), tool="opencode", model="model-a")
        registerRun(swarm, old)
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result.get("success") is False, result
        assert "model_switch_in_session" in str(result.get("error", ""))
        assert spawnMock.await_count == 0
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == "reject"

    def test_resumeFinishedRun_switch_branch_routes_through_surface(self):
        """源码断言：切换分支必须经 surface.switchModel（编排层禁止绕过面自判）。"""
        source = inspect.getsource(SwarmManager.resumeFinishedRun)
        assert "NeuacpMemberSurface" in source
        assert ".switchModel(" in source


# ── 4. snapshot：console 子代理事件读面改经 surface.snapshot ──────────────


class TestSnapshotWiring:
    def test_console_events_endpoint_reads_through_surface(self):
        """源码断言：事件读面必须经 surface.snapshot（同一账本单源，换道不换形）。"""
        from neurova.api.endpoints.console import get_console_subagent_events

        source = inspect.getsource(get_console_subagent_events)
        assert "memberSurface" in source
        assert ".snapshot(" in source
        assert "readRunEvents" not in source, "读面不得绕过收敛面直读账本"

    def test_memberSurface_reads_event_ledger(self, swarm, tmp_path, monkeypatch):
        """memberSurface(sid).snapshot() 与账本同源：真事件真读数。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from neurova.agent.swarm_event_log import appendRunEvent

        run = makeRun("c2-snap-1", team_id="")
        registerRun(swarm, run)
        appendRunEvent(run.subagent_id, "spawned", {"task": "旧任务书"})
        appendRunEvent(run.subagent_id, "terminal", {"status": "completed"})

        events = swarm.memberSurface(run.subagent_id).snapshot()

        types = [e.get("type") for e in events]
        assert "spawned" in types and "terminal" in types

    def test_console_events_endpoint_response_shape_unchanged(
            self, tmp_path, monkeypatch):
        """端到端：GET /console/chat/subagents/{id}/events 响应形状不变
        （code/message/data.subagent_id/count/events），数据经面取得。"""
        monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.deps import get_current_user
        from neurova.api.endpoints import console as console_mod
        from neurova.core import agent_run_store as ars
        from neurova.agent.swarm_event_log import appendRunEvent

        db = tmp_path / "runs.db"
        monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(db))
        monkeypatch.setattr(ars, "_store", None)
        store = ars.AgentRunStore(db)
        monkeypatch.setattr(ars, "_store", store)

        user = {"user_id": "u1", "username": "u1", "role": "user",
                "neuser_id": "u1"}
        app = FastAPI()
        app.include_router(console_mod.router, prefix="/console")
        app.dependency_overrides[get_current_user] = lambda: user
        client = TestClient(app)

        store.intake("sess-c2", "u1", "a1", "任务", subagent_id="run-c2-ev")
        appendRunEvent("run-c2-ev", "spawned", {"task": "旧任务书"})

        resp = client.get("/console/chat/subagents/run-c2-ev/events")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["code"] == 0 and body["message"] == "success"
        data = body["data"]
        assert data["subagent_id"] == "run-c2-ev"
        assert data["count"] == len(data["events"]) == 1
        assert data["events"][0]["type"] == "spawned"
        store.close()
        monkeypatch.setattr(ars, "_store", None)


# ── 5. schema 增量：mode 扩展（可选）+ wire 向后兼容 ──────────────────────


class TestSchemaIncrement:
    def test_continue_subagent_mode_enum_extended_optional(self):
        """mode 增 resume/fork；仍是可选参数（required 不含 mode，wire 兼容）。"""
        schema = get_builtin_tool_params("continue_subagent")
        assert schema is not None
        params = schema["parameters"]
        mode = params["properties"]["mode"]
        assert set(mode["enum"]) == {"steer", "restart", "resume", "fork"}
        assert "mode" not in (params.get("required") or [])

    def test_continue_subagent_required_and_legacy_params_intact(self):
        """既有契约不缩水：required 仍 [subagent_id, message]，legacy 参数仍在。"""
        schema = get_builtin_tool_params("continue_subagent")
        params = schema["parameters"]
        assert sorted(params.get("required") or []) == ["message", "subagent_id"]
        for legacy in ("mode", "background", "command_id", "subagent_id", "message"):
            assert legacy in params["properties"], f"既有参数 {legacy} 被移除"

    def test_continue_mode_description_documents_new_modes(self):
        """模型可见面：mode 描述须写明 fork 分支语义（模型才知道何时用）。"""
        mode = get_builtin_tool_params("continue_subagent")["parameters"][
            "properties"]["mode"]
        assert "fork" in str(mode.get("description", ""))
