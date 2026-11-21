# -*- coding: utf-8 -*-
"""D-B（拍板）：放开非 admin 中途切换 provider，但必须按租户隔离。

- 派生时快照外部成员执行体档案（SubAgentRun.executor_caps_snapshot /
  executor_tool / executor_model），to_dict 带出（新增可选键，契约登记）；
- 续跑按「spawn 时刻快照 vs 名册现值」比较得出 same_executor / model_changed，
  走 decideProviderTransition 五结果决策（reuse / switch_model_in_session /
  restart_and_resume / create_with_handoff / reject）；
- 租户红线（§6.4）：非 admin 跨租户续跑/切换一律结构化拒绝且不泄露目标
  存在性（与「未找到」同形，teams_api 404 同纪律）；admin 豁免但留审计事件；
- 快照缺失的存量 run 按同 executor 同模型处理（向后兼容，C5 原判定不变）。

造数纪律：run 一律真 SubAgentRun + transitionRun 迁移到终态（禁 MagicMock
冒充业务对象）；能力档一律真 catalog 出口形状（capabilitiesFor / CATALOG
条目按需扩展维度）。替身只放在边界：名册读取、身份/admin 解析、which 探测、
spawn 协作方（AsyncMock）。
"""

from unittest.mock import AsyncMock

import pytest

import neurova.agent.neuacp.catalog as neuacp_catalog
from neurova.agent.neuacp.catalog import capabilitiesFor
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SUBAGENT_RUNNING,
    SwarmManager,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_support import transitionRun


# ── 边界替身与造数助手 ────────────────────────────────────────────────


def patchRoster(monkeypatch, members, tenant="default"):
    """名册读取替身：保留 getTeamRoster 真实契约（团队 dict 含 tenant_id）。"""
    import neurova.api.endpoints.teams_api as teams_api

    def _roster(tid):
        return {"id": tid, "name": "测试团队", "tenant_id": tenant,
                "members_detail": members}

    monkeypatch.setattr(teams_api, "getTeamRoster", _roster)


def patchIdentity(monkeypatch, *, tenant="default", user="user-1", admin=False):
    """发起者身份替身：租户（部门根）+ 平台 admin 与否（users 表 role 单源替身）。"""
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
    """which 浅探测替身：返回 probeToolHealth 真实出口形状。"""
    monkeypatch.setattr(
        neuacp_catalog, "probeToolHealth",
        lambda tool, **kw: {"tool": tool, "installed": installed,
                            "install_hint": "", "version": None, "error": None})


def patchCatalogCaps(monkeypatch, tool, **dims):
    """按需给目录条目叠加能力维度（真 CATALOG 条目扩展，monkeypatch.setitem 自动还原）。"""
    entry = dict(neuacp_catalog.CATALOG.get(tool) or {})
    caps = dict(entry.get("capabilities") or {})
    caps.update(dims)
    entry["capabilities"] = caps
    monkeypatch.setitem(neuacp_catalog.CATALOG, tool, entry)


def acpCaps(**extra):
    """真 catalog 出口形状（capabilitiesFor("opencode")）+ 显式维度覆盖。"""
    caps = capabilitiesFor("opencode")
    caps.update(extra)
    return caps


def executorMember(uid="ext-1", tool="opencode"):
    """名册外部成员（executor 配置真 NeuacpExecutorSpec 形状）。"""
    return {"user_id": uid, "name": "外部成员", "role": "coder",
            "prompt": "负责编码",
            "executor": {"kind": "acp", "tool": tool,
                         "command": ["echo", tool], "cwd": "."}}


def finishedRun(sid, *, agent_id="ext-1", team_id="team-1", tenant_id="default",
                member_session_id="msess-old", report="旧产出结论",
                caps=None, tool="", model=""):
    """真 SubAgentRun 经 transitionRun 迁移到 completed 终态；caps 非空时落快照。"""
    run = SubAgentRun(
        subagent_id=sid, agent_id=agent_id, agent_name="外部成员",
        task="旧任务书", origin="chat", session_id="sess-old",
        member_session_id=member_session_id, team_id=team_id,
        tenant_id=tenant_id, report=report,
    )
    transitionRun(run, SUBAGENT_RUNNING, cause="test")
    transitionRun(run, SUBAGENT_COMPLETED, cause="test")
    if caps is not None:
        run.executor_caps_snapshot = caps
        run.executor_tool = tool
        run.executor_model = model
    return run


def eventsOf(swarm, sid):
    return swarm.runEvents(sid).get("events", [])


def decisionEvent(swarm, sid):
    matched = [e for e in eventsOf(swarm, sid) if e.get("type") == "resume_decision"]
    assert matched, "resume_decision 事件必须落账"
    return matched[-1]


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


# ── 契约：快照字段与 to_dict 新增可选键 ───────────────────────────────


class TestSnapshotContract:
    def test_constructorAcceptsSnapshotFields_andToDictCarriesThem(self):
        run = SubAgentRun(
            executor_caps_snapshot={"session_reuse": True},
            executor_tool="opencode",
            executor_model="model-a",
        )
        data = run.to_dict()
        assert data["executor_caps_snapshot"] == {"session_reuse": True}
        assert data["executor_tool"] == "opencode"
        assert data["executor_model"] == "model-a"

    def test_defaultsKeepLegacyShape(self):
        """缺省（存量 run 形态）：快照 None / 标识空串，to_dict 照常带出。"""
        run = SubAgentRun()
        data = run.to_dict()
        assert data["executor_caps_snapshot"] is None
        assert data["executor_tool"] == ""
        assert data["executor_model"] == ""


# ── 五结果决策（快照 vs 名册现值）─────────────────────────────────────


class TestResumeDecisionMatrix:
    def _register(self, swarm, run):
        with swarm._lock:
            swarm._runs[run.subagent_id] = run

    def _patchSpawn(self, swarm, monkeypatch):
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        return spawnMock

    @pytest.mark.asyncio
    async def test_sameExecutorSameModel_reusesMemberSession(self, swarm, monkeypatch):
        """同 executor 同模型 → reuse：member 会话复用（既有行为不回归）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="default")
        patchProbe(monkeypatch, True)
        old = finishedRun("swarm-dba1", caps=acpCaps(), tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        assert kwargs.get("reuse_member_session_id") == old.member_session_id
        assert kwargs.get("resumed_from") == old.subagent_id
        assert result.get("provider_transition") == "reuse"
        payload = decisionEvent(swarm, old.subagent_id)["payload"]
        assert payload["decision"] == "reuse"
        assert payload["same_executor"] is True
        assert payload["model_changed"] is False
        assert payload["tenant_checked"] is True

    @pytest.mark.asyncio
    async def test_modelChanged_declared_switchesModelInSession(self, swarm, monkeypatch):
        """模型变更 + 目标档声明 model_switch_in_session → switch_model_in_session。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="default")
        patchCatalogCaps(monkeypatch, "opencode", model_switch_in_session=True)
        patchProbe(monkeypatch, True)
        # 当前模型名经既有解析链读数：替身只替换模型解析边界
        monkeypatch.setattr(SwarmManager, "_resolve_model_name",
                            staticmethod(lambda agent: "model-b"))
        old = finishedRun("swarm-dba2", caps=acpCaps(), tool="opencode",
                          model="model-a")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        # 会话内换模型：member 会话仍复用（不重开）
        assert kwargs.get("reuse_member_session_id") == old.member_session_id
        assert result.get("provider_transition") == "switch_model_in_session"
        payload = decisionEvent(swarm, old.subagent_id)["payload"]
        assert payload["decision"] == "switch_model_in_session"
        assert payload["same_executor"] is True
        assert payload["model_changed"] is True

    @pytest.mark.asyncio
    async def test_modelChanged_withoutDeclaration_rejectsConservatively(self, swarm, monkeypatch):
        """模型变更但未声明 model_switch_in_session → 保守 reject（不静默复用旧模型会话）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="default")
        patchProbe(monkeypatch, True)
        monkeypatch.setattr(SwarmManager, "_resolve_model_name",
                            staticmethod(lambda agent: "model-b"))
        old = finishedRun("swarm-dba3", caps=acpCaps(), tool="opencode",
                          model="model-a")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result.get("success") is False, result
        assert "model_switch_in_session" in str(result.get("error", ""))
        assert spawnMock.await_count == 0
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == "reject"

    @pytest.mark.asyncio
    async def test_executorChanged_bothHandoff_createWithHandoff(self, swarm, monkeypatch):
        """executor 变更 + 双方声明 handoff_inject → create_with_handoff（重开会话带交接件）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="claude-code")], tenant="default")
        patchCatalogCaps(monkeypatch, "opencode", handoff_inject=True)
        patchCatalogCaps(monkeypatch, "claude-code", handoff_inject=True)
        patchProbe(monkeypatch, True)
        old = finishedRun("swarm-dba4", caps=acpCaps(handoff_inject=True),
                          tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        # 跨执行体：旧 member 会话不复用，续跑 run 重开会话，溯源保留
        assert kwargs.get("reuse_member_session_id") is None
        assert kwargs.get("resumed_from") == old.subagent_id
        assert result.get("provider_transition") == "create_with_handoff"
        payload = decisionEvent(swarm, old.subagent_id)["payload"]
        assert payload["decision"] == "create_with_handoff"
        assert payload["same_executor"] is False

    @pytest.mark.asyncio
    async def test_executorChanged_missingHandoff_rejects(self, swarm, monkeypatch):
        """executor 变更但缺 handoff 声明（目录缺省）→ reject，不派生。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="claude-code")], tenant="default")
        patchProbe(monkeypatch, True)
        old = finishedRun("swarm-dba5", caps=acpCaps(), tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result.get("success") is False, result
        assert "handoff_inject" in str(result.get("error", ""))
        assert spawnMock.await_count == 0
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == "reject"

    @pytest.mark.asyncio
    async def test_targetNotInstalled_rejectsFailClosed(self, swarm, monkeypatch):
        """目标执行体 which 探测未命中 → fail-closed reject（带安装指引）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="default")
        patchProbe(monkeypatch, False)
        old = finishedRun("swarm-dba6", caps=acpCaps(), tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result.get("success") is False, result
        assert "未安装" in str(result.get("error", ""))
        assert spawnMock.await_count == 0
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == "reject"

    @pytest.mark.asyncio
    async def test_targetExecutorRemoved_rejectsHonestly(self, swarm, monkeypatch):
        """名册成员/executor 已移除 → 续跑目标档案不可得，诚实拒绝（不猜）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [], tenant="default")
        old = finishedRun("swarm-dba7", caps=acpCaps(), tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result.get("success") is False, result
        assert "不可得" in str(result.get("error", ""))
        assert spawnMock.await_count == 0


# ── 租户隔离红线（核心安全断言）───────────────────────────────────────


class TestTenantIsolation:
    def _register(self, swarm, run):
        with swarm._lock:
            swarm._runs[run.subagent_id] = run

    def _patchSpawn(self, swarm, monkeypatch):
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        return spawnMock

    @pytest.mark.asyncio
    async def test_crossTenantResume_rejectedWithoutExistenceLeak(self, swarm, monkeypatch):
        """跨租户续跑 → 与「未找到」同形拒绝：不泄露目标存在性与租户细节。"""
        patchIdentity(monkeypatch, tenant="t2")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="t1")
        # run id 刻意不含租户名子串，避免污染「不泄露租户」断言
        old = finishedRun("swarm-runx", tenant_id="t1", caps=acpCaps(),
                          tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result == {"error": f"未找到子 Agent 运行记录: {old.subagent_id}"}, result
        assert "t1" not in str(result) and "t2" not in str(result)
        assert spawnMock.await_count == 0
        assert set(swarm._runs) == {old.subagent_id}, "跨租户续跑不得新增 run"

    @pytest.mark.asyncio
    async def test_teamTenantMismatch_rejectedEvenWhenRunTenantMatches(self, swarm, monkeypatch):
        """目标 agent 配置（团队名册）租户不匹配 → 同样拒绝（红线覆盖 agent 配置面）。"""
        patchIdentity(monkeypatch, tenant="t1")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="t2")
        old = finishedRun("swarm-dbt2", tenant_id="t1", caps=acpCaps(),
                          tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result == {"error": f"未找到子 Agent 运行记录: {old.subagent_id}"}, result
        assert spawnMock.await_count == 0

    @pytest.mark.asyncio
    async def test_adminCrossTenant_allowedWithAuditEvent(self, swarm, monkeypatch):
        """admin 跨租户续跑 → 放行 + 审计事件（resume_cross_tenant_admin）。"""
        patchIdentity(monkeypatch, tenant="t2", admin=True)
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="t1")
        patchProbe(monkeypatch, True)
        old = finishedRun("swarm-dbt3", tenant_id="t1", caps=acpCaps(),
                          tool="opencode", model="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        audit = [e for e in eventsOf(swarm, old.subagent_id)
                 if e.get("type") == "resume_cross_tenant_admin"]
        assert audit, "admin 跨租户豁免必须留审计事件"
        payload = audit[-1]["payload"]
        assert payload["initiator_tenant"] == "t2"
        assert payload["target_tenant"] == "t1"
        assert payload["team_tenant"] == "t1"
        # 决策照常落账（同 executor 同模型 → reuse）
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == "reuse"

    @pytest.mark.asyncio
    async def test_adminCrossTenant_dispatchExempted(self, swarm, monkeypatch):
        """admin 跨租户派活（spawn 侧既有闸）同步豁免——否则续跑放行在派生闸死锁。"""
        patchIdentity(monkeypatch, tenant="t2", admin=True)
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="t1")
        adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
        assert error is None
        assert adapter is not None

    @pytest.mark.asyncio
    async def test_nonAdminCrossTenant_dispatchStillRejected(self, swarm, monkeypatch):
        """非 admin 跨租户派活维持 §6.4 红线（既有行为不回归）。"""
        patchIdentity(monkeypatch, tenant="t2", admin=False)
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="t1")
        adapter, error = swarm._resolveExternalMember("ext-1", "team-1")
        assert adapter is None
        assert "跨租户" in str(error)


# ── 向后兼容：快照缺失的存量 run ──────────────────────────────────────


class TestLegacySnapshotLessRuns:
    def _register(self, swarm, run):
        with swarm._lock:
            swarm._runs[run.subagent_id] = run

    def _patchSpawn(self, swarm, monkeypatch):
        spawnMock = AsyncMock(return_value={"subagent_id": "run-new",
                                            "status": "pending"})
        monkeypatch.setattr(swarm, "spawn", spawnMock)
        return spawnMock

    @pytest.mark.asyncio
    async def test_legacyRun_sessionReuseCaps_reusesAsBefore(self, swarm, monkeypatch):
        """快照缺失 + 目录 session_reuse 档 → 走原同 executor 判定 reuse（兼容）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="opencode")], tenant="default")
        old = finishedRun("swarm-dbl1")  # 不落快照
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        assert (spawnMock.await_args.kwargs
                .get("reuse_member_session_id")) == old.member_session_id
        payload = decisionEvent(swarm, old.subagent_id)["payload"]
        assert payload["decision"] == "reuse"
        assert payload["same_executor"] is True
        assert payload["model_changed"] is False
        assert payload["tenant_checked"] is True

    @pytest.mark.asyncio
    async def test_legacyRun_resumeOnlyCaps_restartAndResume(self, swarm, monkeypatch):
        """快照缺失 + plugin 家 resume 档 → restart_and_resume：重开会话续跑。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(uid="ext-2", tool="zcode")],
                    tenant="default")
        old = finishedRun("swarm-dbl2", agent_id="ext-2")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        assert kwargs.get("reuse_member_session_id") is None
        assert kwargs.get("resumed_from") == old.subagent_id
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == \
            "restart_and_resume"

    @pytest.mark.asyncio
    async def test_legacyRun_conservativeCaps_rejectsAsBefore(self, swarm, monkeypatch):
        """快照缺失 + 未知工具保守档 → C5 原判定 reject（文案与事件不回归）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="unknown-agent-x")],
                    tenant="default")
        old = finishedRun("swarm-dbl3")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert result.get("success") is False, result
        assert "不支持续跑" in str(result.get("error", ""))
        assert spawnMock.await_count == 0
        assert decisionEvent(swarm, old.subagent_id)["payload"]["decision"] == "reject"

    @pytest.mark.asyncio
    async def test_legacyRun_localAgent_noGateProceeds(self, swarm, monkeypatch):
        """快照缺失 + 本仓 agent（无名册归属）→ 不设限走既有续跑链。"""
        patchIdentity(monkeypatch, tenant="default")
        patchRoster(monkeypatch, [], tenant="default")
        old = finishedRun("swarm-dbl4", team_id="")
        self._register(swarm, old)
        spawnMock = self._patchSpawn(swarm, monkeypatch)

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续")

        assert spawnMock.await_count == 1, result
        kwargs = spawnMock.await_args.kwargs
        assert kwargs.get("reuse_member_session_id") == old.member_session_id
        assert kwargs.get("team_id") is None
