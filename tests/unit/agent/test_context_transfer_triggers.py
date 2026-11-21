# -*- coding: utf-8 -*-
"""B2 多触发点卡：上下文传递工件（context_transfer）接入其余编排触发点。

五类型 × 本仓机制 × 接线决策矩阵（可审计产出；权威版在
neurova/agent/context_transfer.py 模块 docstring，此处为测试侧同源摘要）：

- fork：C2 分支派生（continue_subagent mode=fork → surface.fork → spawn 新 run）。
  本卡接线——来源 run 已终态时派生前构建原 run 交接工件（type=fork）inline 随
  分支任务投递、context_transfer 事件留痕；构建失败诚实降级不阻断 fork；
  运行中来源无产出可交接，fork 照常不带工件。
- provider_handoff：D-B 跨 executor 切换（resumeFinishedRun 五结果决策
  create_with_handoff / restart_and_resume → surface.handoffArtifact）。已接
  （B2 既有）——工件经 buildHandoff 物化随新 member 会话任务 inline 投递；
  本卡补断言测试钉住。
- merge_back：候选合入消费子 run 全文 report（无截断）——如实不接（工件不增益）。
- subagent_spawn：spawn 任务书即完整上下文，无"先前上下文"可交接——如实不接。
- subagent_result：完成信封已带全文 report + transcript 指针（无截断）——触发点
  如实不接；类型枚举本身被 B2 续跑衔接工件复用（既有消费点）。

造数纪律（同 C2/D-B 测试）：run 一律真 SubAgentRun + transitionRun 迁移终态；
能力档一律真 catalog 出口形状；替身只放边界（名册/身份/探测/spawn 协作方/
预算抛错）。
"""
from unittest.mock import AsyncMock

import pytest

import neurova.agent.context_transfer as context_transfer
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

pytestmark = pytest.mark.timeout(120)


# ── 边界替身与造数助手（与 C2 / D-B 测试同形） ───────────────────────────


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


def executorMember(uid="ext-1", tool="opencode"):
    return {"user_id": uid, "name": "外部成员", "role": "coder",
            "prompt": "负责编码",
            "executor": {"kind": "acp", "tool": tool,
                         "command": ["echo", tool], "cwd": "."}}


def makeRun(sid, *, agent_id="ext-1", team_id="", tenant_id="default",
            member_session_id="msess-old", report="旧产出结论",
            status=SUBAGENT_COMPLETED, caps=None, tool="", model=""):
    """真 SubAgentRun 按 status 迁移；caps 非空时落 spawn 时刻执行体快照。"""
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


def eventsOf(swarm, sid):
    return swarm.runEvents(sid).get("events", [])


def eventTypes(swarm, sid):
    return [e.get("type") for e in eventsOf(swarm, sid)]


def patchSpawn(swarm, monkeypatch, subagent_id="run-branch"):
    spawnMock = AsyncMock(return_value={"subagent_id": subagent_id,
                                        "status": "pending"})
    monkeypatch.setattr(swarm, "spawn", spawnMock)
    return spawnMock


@pytest.fixture
def swarm(tmp_path, monkeypatch):
    """事件/回执落点隔离到 tmp_path（不污染仓库 data 目录）。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


# ── 1. fork 触发点：派生前构建原 run 交接工件（type=fork） ────────────────


class TestForkTrigger:
    @pytest.mark.asyncio
    async def test_fork_finished_source_carries_handoff_artifact_in_task(
            self, swarm, monkeypatch):
        """终态来源 fork：分支任务 = 交接工件 inline 前缀（含原任务书与产出，
        标明非用户输入）+ 分支指令；溯源 resumed_from 保留。"""
        old = makeRun("b2-fork-1", member_session_id="msess-b2f1")
        registerRun(swarm, old)
        spawnMock = patchSpawn(swarm, monkeypatch)

        result = await swarm.updateSubagent(
            old.subagent_id, "分支任务：换个思路推进", mode="fork")

        assert result.get("error") is None, result
        assert result.get("rejected") is None, result
        assert spawnMock.await_count == 1, result
        branchTask = spawnMock.await_args.args[0]
        # inline 投递的工件前缀（非用户输入声明 + 原任务书 + 原产出）
        assert "上下文交接" in branchTask, branchTask
        assert "非用户输入" in branchTask, branchTask
        assert "旧任务书" in branchTask, branchTask
        assert "旧产出结论" in branchTask, branchTask
        # 分支指令仍在（工件是前缀，不是替换）
        assert "分支任务：换个思路推进" in branchTask, branchTask
        assert spawnMock.await_args.kwargs.get("resumed_from") == old.subagent_id

    @pytest.mark.asyncio
    async def test_fork_logs_context_transfer_event_with_fork_type(
            self, swarm, monkeypatch):
        """终态来源 fork：context_transfer 事件落 H-4 账本，type=fork、
        delivery=inline、transfer_id/handoff_id 可审计。"""
        old = makeRun("b2-fork-2", member_session_id="msess-b2f2")
        registerRun(swarm, old)
        patchSpawn(swarm, monkeypatch)

        result = await swarm.updateSubagent(old.subagent_id, "分支任务", mode="fork")

        assert result.get("error") is None, result
        matched = [e for e in eventsOf(swarm, old.subagent_id)
                   if e.get("type") == "context_transfer"]
        assert matched, "context_transfer 事件必须落账"
        payload = matched[-1].get("payload", {})
        assert payload.get("type") == "fork", payload
        assert payload.get("delivery") == "inline", payload
        assert payload.get("transfer_id"), payload
        assert payload.get("handoff_id"), payload
        assert payload.get("strategy") == "delta_since_last_seen", payload

    @pytest.mark.asyncio
    async def test_fork_running_source_keeps_plain_task_without_artifact(
            self, swarm, monkeypatch):
        """运行中来源 fork（C2 既有约束：不叫停不改动）：无终态产出可交接，
        分支任务保持原样（不假装带了工件），也无 context_transfer 事件。"""
        old = makeRun("b2-fork-3", status=SUBAGENT_RUNNING,
                      member_session_id="msess-b2f3")
        registerRun(swarm, old)
        spawnMock = patchSpawn(swarm, monkeypatch)

        result = await swarm.updateSubagent(old.subagent_id, "分支任务", mode="fork")

        assert spawnMock.await_count == 1, result
        assert spawnMock.await_args.args[0] == "分支任务", "运行中来源不带工件前缀"
        assert "上下文交接" not in spawnMock.await_args.args[0]
        types = eventTypes(swarm, old.subagent_id)
        assert "context_transfer" not in types, types
        assert "context_transfer_failed" not in types, types
        assert old.status == SUBAGENT_RUNNING, "原 run 不被改动"

    @pytest.mark.asyncio
    async def test_fork_handoff_budget_failure_degrades_honestly_without_blocking(
            self, swarm, monkeypatch):
        """工件构建预算超限（ContextHandoffBudgetError）→ 诚实降级：不阻断
        fork（分支照常派生、任务不带工件），context_transfer_failed 留痕。"""
        old = makeRun("b2-fork-4", member_session_id="msess-b2f4")
        registerRun(swarm, old)
        spawnMock = patchSpawn(swarm, monkeypatch)

        def _budgetBoom(*args, **kwargs):
            raise context_transfer.ContextHandoffBudgetError(
                "上下文窗口放不下交接内容：窗口余量 -5 tokens，"
                "低于交接下限 1024 tokens（宁可失败，不静默截断）。")

        monkeypatch.setattr(context_transfer, "buildHandoff", _budgetBoom)

        result = await swarm.updateSubagent(old.subagent_id, "分支任务", mode="fork")

        # fork 不被工件失败阻断：分支照常派生，任务原样（不静默截断也不假装带件）
        assert spawnMock.await_count == 1, result
        assert spawnMock.await_args.args[0] == "分支任务", "降级时任务不带残缺工件"
        assert spawnMock.await_args.kwargs.get("resumed_from") == old.subagent_id
        # 诚实留痕：context_transfer_failed 事件带原因
        failed = [e for e in eventsOf(swarm, old.subagent_id)
                  if e.get("type") == "context_transfer_failed"]
        assert failed, "工件构建失败必须落 context_transfer_failed 事件"
        assert "预算" in str(failed[-1].get("payload", {}).get("reason", "")) or \
            "tokens" in str(failed[-1].get("payload", {}).get("reason", "")), failed[-1]


# ── 2. provider_handoff 触发点：D-B create_with_handoff 走 context_transfer ──


class TestProviderHandoffTrigger:
    @pytest.mark.asyncio
    async def test_create_with_handoff_task_carries_context_transfer_artifact(
            self, swarm, monkeypatch):
        """D-B create_with_handoff：交接工件确实经 context_transfer 构建——
        续跑任务含 inline 工件前缀（原产出全文随行）+ 续跑指令，原 run 落
        context_transfer 事件（type=subagent_result，B2 既有登记类型）。"""
        patchIdentity(monkeypatch, tenant="default")
        patchExternalOn(monkeypatch)
        patchRoster(monkeypatch, [executorMember(tool="claude-code")],
                    tenant="default")
        patchCatalogCaps(monkeypatch, "opencode", handoff_inject=True)
        patchCatalogCaps(monkeypatch, "claude-code", handoff_inject=True)
        patchProbe(monkeypatch, True)
        old = makeRun("b2-ph-1", team_id="team-1",
                      caps=acpCaps(handoff_inject=True), tool="opencode",
                      model="")
        registerRun(swarm, old)
        spawnMock = patchSpawn(swarm, monkeypatch, subagent_id="run-new")

        result = await swarm.resumeFinishedRun(old.subagent_id, "继续排查")

        assert result.get("provider_transition") == "create_with_handoff", result
        assert spawnMock.await_count == 1, result
        task = spawnMock.await_args.args[0]
        assert "上下文交接" in task, task
        assert "非用户输入" in task, task
        assert "旧产出结论" in task, "原产出须经工件随行（重开会话不丢）"
        assert "继续排查" in task, "续跑指令仍在"
        matched = [e for e in eventsOf(swarm, old.subagent_id)
                   if e.get("type") == "context_transfer"]
        assert matched, "context_transfer 事件必须落账"
        payload = matched[-1].get("payload", {})
        assert payload.get("type") == "subagent_result", payload
        assert payload.get("delivery") == "inline", payload

    def test_resume_handoff_builds_through_context_transfer_module(self):
        """源码断言：续跑工件构建走 context_transfer 单一实现（登记/预算/
        inline 投递经本模块，编排层不自建第二份）。"""
        import inspect

        source = inspect.getsource(SwarmManager._buildResumeHandoff)
        assert "buildHandoff" in source
        assert "renderInlinePrefix" in source
        assert "markDelivery" in source
        assert "ContextTransfer(" in source


# ── 3. 触发点矩阵存在性（可审计产出钉在工件模块 docstring） ───────────────


class TestTriggerMatrixDocumented:
    def test_transfer_type_matrix_documented_in_module_docstring(self):
        """工件模块 docstring 必须写明五类型 × 触发点接线矩阵（每类给决策
        与理由），作为本卡可审计产出的事实源。"""
        doc = context_transfer.__doc__ or ""
        for transferType in context_transfer.TRANSFER_TYPES:
            assert transferType in doc, f"矩阵缺少类型 {transferType}"
        for keyword in ("如实不接", "create_with_handoff", "inline", "fork"):
            assert keyword in doc, f"矩阵缺少决策说明关键词：{keyword}"
