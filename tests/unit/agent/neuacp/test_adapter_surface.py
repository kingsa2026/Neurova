# -*- coding: utf-8 -*-
"""G3 适配器方法面收敛：NeuacpMemberSurface 方法级契约（计划文档 G3，D-4 仅外部成员）。

锁定契约：
1. requireCapability：dim 必须在 BOOLEAN_CAPABILITY_DIMS 单源内（拼错 ValueError）；
   caps None（内部 agent / 无名册归属）→ 放行；dims.get(dim) is True → 放行；
   否则 CapabilityNotDeclared（带 dim 属性与安装/改配指引）。
2. NeuacpMemberSurface.forRun(run)：经 get_swarm_manager()._memberExecutorCaps
   解析能力档；None → 不设限面。
3. 方法 ↔ 机制 ↔ 能力维度：
   - steer → steer 队列邮箱（**无能力闸**：邮箱机制不依赖 agent 侧支持）；
   - snapshot → swarm_event_log.readRunEvents 事件账本（无能力维度，读数不设限）；
   - handoffArtifact → manager._buildResumeHandoff 既有交接工件构建
     （跨 executor 时要求 handoff_inject，同 D-B 五结果判定既有条件）；
   - rollback → CheckpointService 最近检查点 + restore_with_rollback 事务化恢复
     （要求 conversation_rollback）；
   - fork → 既有 spawn 派生链 + resumed_from 溯源（要求 fork；候选制+重派路径）；
   - switchModel → catalog.decideProviderTransition 五结果决策的
     switch_model_in_session 分支语义（要求 model_switch_in_session）。
4. 编排层接线：updateSubagent 的 steer 路径与 resumeFinishedRun 的交接工件构建
   改经 surface（源码断言钉住，禁止绕过）。

造数纪律（同 D-B 测试）：run 一律真 SubAgentRun + transitionRun 迁移终态；
能力档一律真 catalog 出口形状；替身只放边界（名册/身份/探测/spawn 协作方）。
"""
import inspect
from unittest.mock import AsyncMock

import pytest

import neurova.agent.neuacp.catalog as neuacp_catalog
from neurova.agent.neuacp.catalog import BOOLEAN_CAPABILITY_DIMS, capabilitiesFor
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SwarmManager,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_event_log import appendRunEvent
from neurova.agent.swarm_support import transitionRun
from neurova.core.steer_queue import get_steer_queue, reset_steer_queue

from neurova.agent.neuacp.adapter_surface import (
    CapabilityNotDeclared,
    NeuacpMemberSurface,
    requireCapability,
)


# ── 边界替身与造数助手（与 test_provider_switch_tenant 同形） ────────────


def patchRoster(monkeypatch, members, tenant="default"):
    import neurova.api.endpoints.teams_api as teams_api

    def _roster(tid):
        return {"id": tid, "name": "测试团队", "tenant_id": tenant,
                "members_detail": members}

    monkeypatch.setattr(teams_api, "getTeamRoster", _roster)


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


def executorMember(uid="ext-1", tool="opencode"):
    return {"user_id": uid, "name": "外部成员", "role": "coder",
            "prompt": "负责编码",
            "executor": {"kind": "acp", "tool": tool,
                         "command": ["echo", tool], "cwd": "."}}


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


@pytest.fixture
def swarm():
    reset_swarm_manager()
    reset_steer_queue()
    yield get_swarm_manager()
    reset_swarm_manager()
    reset_steer_queue()


# ── requireCapability：fail-closed 能力闸单源 ────────────────────────────


class TestRequireCapability:
    def test_unknownDim_raisesValueError(self):
        """dim 拼错 → ValueError（防静默把拼错维度当未声明）。"""
        with pytest.raises(ValueError) as exc:
            requireCapability({"fork": True}, "frok")
        assert "BOOLEAN_CAPABILITY_DIMS" in str(exc.value) or "能力维度" in str(exc.value)

    def test_noneCaps_passes_internalAgent(self):
        """caps None（内部 agent / 无名册归属）→ 放行（C5 同惯例：不设限）。"""
        for dim in BOOLEAN_CAPABILITY_DIMS:
            assert requireCapability(None, dim) is None

    def test_declaredTrue_passes(self):
        for dim in BOOLEAN_CAPABILITY_DIMS:
            assert requireCapability({dim: True}, dim) is None

    @pytest.mark.parametrize("declared", [False, None, "missing"])
    def test_notDeclaredTrue_raisesWithDim(self, declared):
        """False / 缺失（键不存在）同义 = 不支持 → CapabilityNotDeclared。"""
        caps = {} if declared == "missing" else {"fork": declared}
        with pytest.raises(CapabilityNotDeclared) as exc:
            requireCapability(caps, "fork")
        assert exc.value.dim == "fork"

    def test_errorCarriesGuidance(self):
        """异常文案带安装/改配指引（点名维度与声明位置）。"""
        with pytest.raises(CapabilityNotDeclared) as exc:
            requireCapability({}, "conversation_rollback")
        text = str(exc.value)
        assert "conversation_rollback" in text
        assert "executor" in text or "能力声明" in text

    def test_nonDictCaps_raises(self):
        """caps 非 dict 非 None（脏数据）→ fail-closed 拒绝，不静默放行。"""
        with pytest.raises(CapabilityNotDeclared):
            requireCapability(["fork"], "fork")


# ── forRun：能力档解析 ───────────────────────────────────────────────────


class TestForRun:
    def test_externalMember_resolvesRosterCaps(self, swarm, monkeypatch):
        """外部成员：能力档来自名册 executor.tool 的目录声明（单一事实源）。"""
        patchRoster(monkeypatch, [executorMember(tool="opencode")])
        run = makeRun("surf-f1")
        registerRun(swarm, run)

        surface = NeuacpMemberSurface.forRun(run)

        assert surface.caps is not None
        assert surface.caps.get("session_reuse") is True  # acp 家目录声明
        assert surface.run is run

    def test_localAgent_noneCaps(self, swarm, monkeypatch):
        """本仓 agent（无名册归属）→ caps None（不设限面）。"""
        patchRoster(monkeypatch, [])
        run = makeRun("surf-f2", team_id="")
        registerRun(swarm, run)

        surface = NeuacpMemberSurface.forRun(run)

        assert surface.caps is None

    def test_rosterVanished_fallsBackToSnapshotCaps(self, swarm, monkeypatch):
        """名册读不到但 run 带快照 → 回落快照能力档（外部成员不被静默放权）。"""
        patchRoster(monkeypatch, [])
        run = makeRun("surf-f3", caps=acpCaps(fork=True), tool="opencode")
        registerRun(swarm, run)

        surface = NeuacpMemberSurface.forRun(run)

        assert surface.caps is not None
        assert surface.caps.get("fork") is True


# ── steer：邮箱机制，无能力闸 ────────────────────────────────────────────


class TestSteer:
    def test_steer_enqueues_evenWhenDimNotDeclared(self, swarm, monkeypatch):
        """能力档全 False（未知工具保守档）也能插话——steer 走邮箱，
        不依赖 agent 侧支持，故不加能力闸（避免既有插话路径被闸死）。"""
        patchRoster(monkeypatch, [executorMember(tool="unknown-agent-x")])
        run = makeRun("surf-s1", member_session_id="msess-steer")
        registerRun(swarm, run)
        surface = NeuacpMemberSurface.forRun(run)
        assert (surface.caps or {}).get("steer") is not True  # 前提：未声明 steer

        delivered = surface.steer("需求变更：只做前半部分")

        assert delivered is True
        assert "需求变更：只做前半部分" in get_steer_queue().drain("msess-steer")

    def test_steer_emptyText_returnsFalse(self, swarm, monkeypatch):
        patchRoster(monkeypatch, [executorMember()])
        run = makeRun("surf-s2", member_session_id="msess-steer2")
        registerRun(swarm, run)

        assert NeuacpMemberSurface.forRun(run).steer("   ") is False


# ── snapshot：事件账本读数，无能力维度 ───────────────────────────────────


class TestSnapshot:
    def test_snapshot_readsRunEventLedger(self, swarm):
        run = makeRun("surf-n1")
        registerRun(swarm, run)
        appendRunEvent(run.subagent_id, "spawned", {"task": "旧任务书"})
        appendRunEvent(run.subagent_id, "terminal", {"status": "completed"})

        events = NeuacpMemberSurface.forRun(run).snapshot()

        assert isinstance(events, list)
        types = [e.get("type") for e in events]
        assert "spawned" in types and "terminal" in types

    def test_snapshot_noEvents_returnsEmptyList(self, swarm):
        # 裸 SubAgentRun（不经 transitionRun——状态迁移本身会落 status_changed
        # 事件），其账本文件不存在 → 空列表。
        run = SubAgentRun(subagent_id="surf-n2-raw", agent_id="ext-1",
                          member_session_id="msess-raw")
        assert NeuacpMemberSurface.forRun(run).snapshot() == []


# ── handoffArtifact：既有交接工件构建 + 跨 executor handoff_inject 闸 ────


class TestHandoffArtifact:
    def test_crossExecutor_declared_buildsArtifact(self, swarm, monkeypatch):
        """跨 executor + 双方声明 handoff_inject → 真出工件（B2 交接机制）。"""
        patchRoster(monkeypatch, [executorMember(tool="claude-code")])
        patchExternalOn(monkeypatch)
        patchCatalogCaps(monkeypatch, "opencode", handoff_inject=True)
        patchCatalogCaps(monkeypatch, "claude-code", handoff_inject=True)
        patchProbe(monkeypatch, True)
        run = makeRun("surf-h1", caps=acpCaps(handoff_inject=True),
                      tool="opencode", model="")
        registerRun(swarm, run)
        surface = NeuacpMemberSurface.forRun(run)

        text, meta = surface.handoffArtifact("衔接后继续")

        assert "续跑衔接" in text
        assert text.endswith("衔接后继续") is False  # 本体是工件，指令由编排层拼
        assert meta.get("handoff_id")
        assert meta.get("transfer_id")

    def test_crossExecutor_missingDeclaration_raises(self, swarm, monkeypatch):
        """跨 executor 但成员能力档未声明 handoff_inject → CapabilityNotDeclared。"""
        patchRoster(monkeypatch, [executorMember(tool="claude-code")])
        patchExternalOn(monkeypatch)
        patchProbe(monkeypatch, True)
        run = makeRun("surf-h2", caps=acpCaps(), tool="opencode", model="")
        registerRun(swarm, run)

        with pytest.raises(CapabilityNotDeclared) as exc:
            NeuacpMemberSurface.forRun(run).handoffArtifact()

        assert exc.value.dim == "handoff_inject"

    def test_sameExecutor_noGate_buildsArtifact(self, swarm, monkeypatch):
        """同 executor 续跑：无跨 executor 闸，工件照常构建（既有行为）。"""
        patchRoster(monkeypatch, [executorMember(tool="opencode")])
        patchExternalOn(monkeypatch)
        patchProbe(monkeypatch, True)
        run = makeRun("surf-h3", caps=acpCaps(), tool="opencode", model="")
        registerRun(swarm, run)

        text, meta = NeuacpMemberSurface.forRun(run).handoffArtifact()

        assert "续跑衔接" in text
        assert meta.get("handoff_id")

    def test_localAgent_noGate_buildsArtifact(self, swarm, monkeypatch):
        """本仓 agent（无快照无名册）→ 不设限，工件照常构建（D-B 兼容）。"""
        run = makeRun("surf-h4", team_id="")
        registerRun(swarm, run)

        text, meta = NeuacpMemberSurface.forRun(run).handoffArtifact()

        assert "续跑衔接" in text


# ── rollback：检查点服务最近检查点事务化恢复 ─────────────────────────────


@pytest.fixture()
def checkpointEnv(tmp_path, monkeypatch):
    """检查点/会话落点隔离 + git 身份兜底（与 test_checkpoints_api 同纪律）。"""
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


class TestRollback:
    def test_rollback_restoresLatestCheckpoint(self, swarm, checkpointEnv):
        """真机制：CheckpointService 快照 → rollback 恢复 member 会话到最近检查点。"""
        from neurova.checkpoints.service import CheckpointService
        from neurova.session_manager import SessionManager

        agentId, memberSession = "surf-agent", "msess-rb1"
        sm = SessionManager()
        sm.save_message(agent_id=agentId, session_id=memberSession,
                        role="user", content="第一轮输入")
        service = CheckpointService(agent_id=agentId, debounce_seconds=0)
        ref = service.snapshot_auto(memberSession, {"messages": [
            {"role": "user", "content": "第一轮输入"}]})
        # 检查点之后又推进了一轮（"未来"消息）
        sm.save_message(agent_id=agentId, session_id=memberSession,
                        role="assistant", content="第二轮回复")

        run = makeRun("surf-rb1", agent_id=agentId,
                      member_session_id=memberSession,
                      caps={"conversation_rollback": True})
        registerRun(swarm, run)

        result = NeuacpMemberSurface.forRun(run).rollback()

        assert result.get("success") is True, result
        assert result.get("restored_ref") == ref
        history = sm.get_history(agentId, memberSession)
        contents = [str(m.get("content") or "") for m in history]
        assert "第二轮回复" not in contents, "回滚后不得残留检查点之后的轮次"
        assert "第一轮输入" in contents

    def test_rollback_withoutDeclaration_raises(self, swarm, checkpointEnv):
        run = makeRun("surf-rb2", caps=acpCaps())  # 保守档：rollback False

        with pytest.raises(CapabilityNotDeclared) as exc:
            NeuacpMemberSurface.forRun(run).rollback()

        assert exc.value.dim == "conversation_rollback"

    def test_rollback_noCheckpoint_honestError(self, swarm, checkpointEnv):
        """无检查点可回 → 诚实失败（不静默当成功）。"""
        run = makeRun("surf-rb3", agent_id="surf-agent-2",
                      member_session_id="msess-none",
                      caps={"conversation_rollback": True})
        registerRun(swarm, run)

        result = NeuacpMemberSurface.forRun(run).rollback()

        assert result.get("success") is False
        assert "检查点" in str(result.get("error", ""))

    def test_rollback_internalAgent_noneCaps_passesGate(self, swarm, checkpointEnv):
        """内部 agent（caps None）→ 闸放行，机制照走（不设限惯例）。"""
        from neurova.checkpoints.service import CheckpointService
        from neurova.session_manager import SessionManager

        agentId, memberSession = "surf-agent-3", "msess-rb4"
        sm = SessionManager()
        sm.save_message(agent_id=agentId, session_id=memberSession,
                        role="user", content="首条")
        CheckpointService(agent_id=agentId, debounce_seconds=0).snapshot_auto(
            memberSession, {"messages": [{"role": "user", "content": "首条"}]})

        run = makeRun("surf-rb4", agent_id=agentId, team_id="",
                      member_session_id=memberSession)
        registerRun(swarm, run)

        result = NeuacpMemberSurface.forRun(run).rollback()

        assert result.get("success") is True, result


# ── fork：候选制+重派路径（spawn 派生链 + resumed_from 溯源） ─────────────


class TestFork:
    def _patchSpawn(self, swarm, monkeypatch):
        spawnMock = AsyncMock(return_value={"subagent_id": "run-fork",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        return spawnMock

    @pytest.mark.asyncio
    async def test_fork_declared_spawnsBranchRun(self, swarm, monkeypatch):
        """声明 fork → 经既有 spawn 派生新 run（resumed_from 溯源、新 member 会话）。"""
        run = makeRun("surf-k1", team_id="", caps={"fork": True})
        registerRun(swarm, run)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await NeuacpMemberSurface.forRun(run).fork("分支任务：换条路试")

        assert spawnMock.await_count == 1
        kwargs = spawnMock.await_args.kwargs
        # task 与 resumeFinishedRun 同形：位置实参（首参）
        assert spawnMock.await_args.args[0] == "分支任务：换条路试"
        assert kwargs.get("agent_id") == run.agent_id
        assert kwargs.get("resumed_from") == run.subagent_id
        assert kwargs.get("reuse_member_session_id") is None, "fork 是新分支，不复用原会话"
        assert result == {"subagent_id": "run-fork", "status": "pending"}

    @pytest.mark.asyncio
    async def test_fork_withoutDeclaration_raises(self, swarm, monkeypatch):
        run = makeRun("surf-k2", team_id="", caps=acpCaps())  # 保守档：fork False
        registerRun(swarm, run)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        with pytest.raises(CapabilityNotDeclared) as exc:
            await NeuacpMemberSurface.forRun(run).fork("分支任务")

        assert exc.value.dim == "fork"
        assert spawnMock.await_count == 0, "闸拒绝时不得派生"

    @pytest.mark.asyncio
    async def test_fork_internalAgent_noneCaps_passesGate(self, swarm, monkeypatch):
        """内部 agent（caps None）→ 放行（不设限惯例，同 C5）。"""
        run = makeRun("surf-k3", team_id="")
        registerRun(swarm, run)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        await NeuacpMemberSurface.forRun(run).fork("分支任务")

        assert spawnMock.await_count == 1


# ── switchModel：五结果决策 switch_model_in_session 分支语义 ─────────────


class TestSwitchModel:
    def _declareSwitch(self, monkeypatch):
        patchRoster(monkeypatch, [executorMember(tool="opencode")])
        patchExternalOn(monkeypatch)
        patchCatalogCaps(monkeypatch, "opencode", model_switch_in_session=True)
        patchProbe(monkeypatch, True)
        monkeypatch.setattr(SwarmManager, "_resolve_model_name",
                            staticmethod(lambda agent: "model-b"))

    def test_switchModel_declared_decisionReached(self, swarm, monkeypatch):
        """声明 model_switch_in_session + 名册现值模型=请求模型 → 决策成立。"""
        self._declareSwitch(monkeypatch)
        run = makeRun("surf-m1", caps=acpCaps(model_switch_in_session=True),
                      tool="opencode", model="model-a")
        registerRun(swarm, run)

        result = NeuacpMemberSurface.forRun(run).switchModel("model-b")

        assert result.get("success") is True, result
        assert result.get("decision") == "switch_model_in_session"
        assert result.get("reuse_member_session") is True
        assert result.get("target_model") == "model-b"

    def test_switchModel_withoutDeclaration_raises(self, swarm, monkeypatch):
        """未声明 model_switch_in_session → CapabilityNotDeclared（保守，不静默复用）。"""
        patchRoster(monkeypatch, [executorMember(tool="opencode")])
        patchExternalOn(monkeypatch)
        patchProbe(monkeypatch, True)
        monkeypatch.setattr(SwarmManager, "_resolve_model_name",
                            staticmethod(lambda agent: "model-b"))
        run = makeRun("surf-m2", caps=acpCaps(), tool="opencode", model="model-a")
        registerRun(swarm, run)

        with pytest.raises(CapabilityNotDeclared) as exc:
            NeuacpMemberSurface.forRun(run).switchModel("model-b")

        assert exc.value.dim == "model_switch_in_session"

    def test_switchModel_unknownTargetModel_rejectsHonestly(self, swarm, monkeypatch):
        """请求模型 ≠ 名册现值模型 → 诚实拒绝（本仓机制只认名册现值，无运行期 setter）。"""
        self._declareSwitch(monkeypatch)
        run = makeRun("surf-m3", caps=acpCaps(model_switch_in_session=True),
                      tool="opencode", model="model-a")
        registerRun(swarm, run)

        result = NeuacpMemberSurface.forRun(run).switchModel("model-z")

        assert result.get("success") is False
        assert "model-z" in str(result.get("error", ""))

    def test_switchModel_rosterUnavailable_rejectsHonestly(self, swarm, monkeypatch):
        """名册/执行体档案不可得 → 诚实拒绝（不猜）。"""
        patchRoster(monkeypatch, [])
        run = makeRun("surf-m4", caps=acpCaps(model_switch_in_session=True),
                      tool="opencode", model="model-a")
        registerRun(swarm, run)

        result = NeuacpMemberSurface.forRun(run).switchModel("model-b")

        assert result.get("success") is False
        assert result.get("error")


# ── 编排层接线：禁止绕过收敛面（源码断言） ──────────────────────────────


class TestOrchestrationWiring:
    def test_updateSubagent_steerPath_usesSurface(self):
        """updateSubagent 的 steer 路径必须经 NeuacpMemberSurface（禁直捅队列）。"""
        source = inspect.getsource(SwarmManager._updateSubagentInner)
        assert "NeuacpMemberSurface" in source
        assert "forRun" in source
        assert ".steer(" in source
        assert "get_steer_queue().push" not in source, "编排层不得绕过收敛面直写队列"

    def test_resumeFinishedRun_handoff_usesSurface(self):
        """resumeFinishedRun 的交接工件构建必须经 surface.handoffArtifact。"""
        source = inspect.getsource(SwarmManager.resumeFinishedRun)
        assert ".handoffArtifact(" in source
        # 只禁直呼调用形态（self._buildResumeHandoff(...)）；注释里的实现名不算绕过。
        assert "self._buildResumeHandoff(" not in source, "编排层不得绕过收敛面直建工件"
