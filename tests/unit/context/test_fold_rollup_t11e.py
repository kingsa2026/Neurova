# -*- coding: utf-8 -*-
"""T-11e rollup 后台化：每轮摘要 LLM 调用 ≤1、失败不推进覆盖账、回退等式（Issue #90）。

## 根因（不是"少一次重试"）

工单 §12.7 判据 6 要求「每轮新增摘要 LLM 调用 ≤ 1 次（rollup 走后台）」。
改前折叠路径把这个上界打穿在**失败形状**上：

`compact_window` 的收敛保证是「摘要失败 → 丢最旧一条重试，上限 `_SUMMARY_MAX_RETRIES`=3」。
它本身是压缩器级契约（对直接调用者有意义），但编排器的折叠路径**把整段重试
连同递进折叠循环一起放在了关键路径上** —— 实测：摘要器恒失败时单轮 `build_context`
发起 **4 次** LLM 调用，而成功形状只要 1 次。失败越多、调用越多，正是判据 6
要挡住的那条曲线。

同时，工单 §12.5 第 4 条把「rollup 用 `asyncio.ensure_future` 发后不管」明列为假实现
（现成反例 `openai_loop.py:492/555`：异常无人 await）。所以"把重试挪到后台"不能
只是换个地方 fire-and-forget —— 后台必须**自己 await 并记账**，失败要可读。

## 本票契约

1. **每轮上界**：折叠路径每轮至多 1 次摘要 LLM 调用（重试与递进共用同一个
   调用预算），失败时视图沿用既有静态桩语义；
2. **后台补做**：失败批次交给 `ContextRollupWorker`，它串行、有界、**持有并 await
   自己的任务**（不是发后不管），成功才写层节点；失败不推进覆盖账；
3. **可读**：`get_context_health()["fold_rollup"]` 给出
   `dispatched / succeeded / failed / in_flight / dropped / last_error`；
4. **回退等式**：`NEUROVA_CONTEXT_ROLLUP=0` 时不启动 worker，折叠行为逐字等价于本票之前。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.context.pool_models import ContextSource


def _agent(agentId: str = "a-t11e"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = agentId
    return agent


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("NEUROVA_CONTEXT_ROLLUP", raising=False)
    yield


def _longRound(i: int, chars: int = 400):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


def _orchestrator(agentId: str = "a-t11e", budget: int = 600):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id="sess-t11e"
    )
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0
    return orch


async def _build(orch, history, user_input="继续"):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
        )


def _layerNodes(orch):
    return [
        c
        for c in orch.context_pool.get_contexts()
        if c.source == ContextSource.SUMMARY
        and (c.metadata or {}).get("covers")
    ]


class TestPerTurnSummaryBudget:
    """判据 6 前半：每轮新增摘要 LLM 调用 ≤ 1 次。"""

    @pytest.mark.asyncio
    async def test_failing_summarizer_costs_one_call_per_turn(self):
        """摘要器恒失败时，单轮不得发起 >1 次 LLM 调用（改前实测 4 次）。

        改前形态：压缩器的「丢最旧一条重试（上限 3）」+ 递进折叠循环整段跑在
        关键路径上，失败形状下把单轮调用放大到 4 次（1 + 3 次重试）。
        """
        orch = _orchestrator()
        calls = {"n": 0}

        async def flaky(dropped, previous_summary=""):
            calls["n"] += 1
            return None

        orch._window_summarizer = flaky
        await _build(orch, [_longRound(i) for i in range(30)])

        assert calls["n"] <= 1, (
            f"单轮发起了 {calls['n']} 次摘要 LLM 调用（判据 6 上界 = 1）："
            "失败重试仍跑在关键路径上，rollup 没有后台化"
        )

    @pytest.mark.asyncio
    async def test_success_path_still_costs_exactly_one_call(self):
        """成功形状仍是 1 次：上界收紧不得把正常路径的摘要也省掉。"""
        orch = _orchestrator()
        calls = {"n": 0}

        async def summ(dropped, previous_summary=""):
            calls["n"] += 1
            return f"第{calls['n']}代摘要：覆盖 {len(dropped)} 条"

        orch._window_summarizer = summ
        await _build(orch, [_longRound(i) for i in range(30)])

        assert calls["n"] == 1, f"成功形状应恰好 1 次摘要调用，实得 {calls['n']}"
        assert _layerNodes(orch), (
            "成功形状的层节点没有落进池 —— 收紧上界把索引也一起省掉了"
        )


class TestBackgroundRollup:
    """判据 6 中段：失败批次由后台 worker 补做，且**不是**发后不管。"""

    @pytest.mark.asyncio
    async def test_failed_batch_is_retried_off_the_critical_path(self):
        """失败批次交后台补做：视图轮内零重试，worker 成功后才出现层节点。"""
        orch = _orchestrator()
        state = {"fail": True, "calls": 0}

        async def flaky(dropped, previous_summary=""):
            state["calls"] += 1
            if state["fail"]:
                return None
            return f"补做摘要：覆盖 {len(dropped)} 条"

        orch._window_summarizer = flaky
        history = [_longRound(i) for i in range(30)]
        in_turn = state["calls"]
        await _build(orch, history)
        in_turn = state["calls"] - in_turn
        assert in_turn <= 1, f"关键路径仍付了 {in_turn} 次调用"

        worker = orch.foldRollupWorker()
        assert worker is not None, "折叠失败没有落点：rollup worker 未装配（断点）"
        readout = orch.get_context_health()["fold_rollup"]
        assert readout["dispatched"] >= 1, (
            f"失败批次没有被交给后台补做：读数={readout} —— 判据 6 要求 rollup 走后台"
        )

        # 后台补做成功后才推进覆盖账（层节点此刻才出现）
        state["fail"] = False
        await worker.drain()
        assert _layerNodes(orch), "后台补做成功却没有写层节点：补做路径是空转"
        readout = orch.get_context_health()["fold_rollup"]
        assert readout["failed"] == 0 or readout["succeeded"] >= 1, (
            f"补做成功但读数没记账：{readout}"
        )

    @pytest.mark.asyncio
    async def test_rollup_failure_does_not_advance_coverage(self):
        """后台补做失败**不推进覆盖账**（与 T-05 同族：别把假账带回来）。"""
        orch = _orchestrator()
        state = {"calls": 0}

        async def always_failing(dropped, previous_summary=""):
            state["calls"] += 1
            return None

        orch._window_summarizer = always_failing
        await _build(orch, [_longRound(i) for i in range(30)])

        worker = orch.foldRollupWorker()
        assert worker is not None
        slot = orch._window_compaction_cache["sess-t11e"]
        covered_before = set(slot.get("covered") or set())

        await worker.drain()

        assert set(slot.get("covered") or set()) == covered_before, (
            "补做失败却推进了覆盖账：后续轮次会把未摘要的内容谎报为已覆盖（T-05 同族）"
        )
        assert not _layerNodes(orch), "补做失败却写进了层节点：索引指向不存在的摘要"
        readout = orch.get_context_health()["fold_rollup"]
        assert readout["failed"] >= 1, f"补做失败没被记账：{readout}"
        assert readout["last_error"], (
            "补做失败必须点名原因（教义第 2 条：不许把失败改写成静默）"
        )

    @pytest.mark.asyncio
    async def test_worker_observes_its_own_task(self):
        """后台任务被 worker 持有并 await —— 不是 `ensure_future` 发后不管。

        工单 §12.5 第 4 条把「发后不管」列为假实现（现成反例
        `openai_loop.py:492/555`：异常无人 await）。判据取"异常被 worker 记账"这一
        可观察事实：补做抛异常时 `last_error` 必须点名，且不得逃逸成未处理异常。
        """
        orch = _orchestrator()
        state = {"boom": True}

        async def exploding(dropped, previous_summary=""):
            if state["boom"]:
                raise RuntimeError("LLM 网关 502")
            return "补做摘要"

        orch._window_summarizer = exploding
        await _build(orch, [_longRound(i) for i in range(30)])

        worker = orch.foldRollupWorker()
        await worker.drain()
        readout = orch.get_context_health()["fold_rollup"]
        assert readout["last_error"], (
            f"补做抛出的异常没有人 await（发后不管）：读数={readout}"
        )
        assert "RuntimeError" in str(readout["last_error"]) or "502" in str(
            readout["last_error"]
        ), f"失败原因没有点名：{readout['last_error']}"

    @pytest.mark.asyncio
    async def test_in_flight_is_bounded_per_session(self):
        """后台不是无界队列：同一会话同时在飞的补做至多 1 个（防堆积）。

        判据直接打在 worker 的公开面上（派发/在飞/排空），不借关键路径 ——
        后台化之前，任何"让摘要器等待"的输入都会把整轮 `build_context` 挂住，
        那正是本票要拆掉的那条曲线，不能拿它当判据（判据会挂死，等于没判据）。
        """
        orch = _orchestrator(agentId="a-t11e-bounded")
        gate = asyncio.Event()
        calls = {"n": 0}

        async def slow(dropped, previous_summary=""):
            calls["n"] += 1
            await gate.wait()
            return f"补做摘要 {len(dropped)} 条"

        orch._window_summarizer = slow
        worker = orch.foldRollupWorker()
        assert worker is not None, "rollup worker 未装配（断点）"

        for rnd in range(3):
            worker.dispatch(
                sessionKey="sess-t11e",
                summarize=slow,
                droppedMsgs=[_longRound(100 + rnd)],
                covers=[f"h{rnd}"],
                turnIds=[f"turn_{rnd}"],
                lastCount=1,
            )
        assert worker.inFlightCount("sess-t11e") <= 1, (
            f"同会话在飞补做 {worker.inFlightCount('sess-t11e')} 个："
            "后台队列无界，会话越长堆积越多"
        )
        gate.set()
        await worker.drain()
        assert calls["n"] >= 1, "worker 根本没有把派发的批次跑起来"


class TestRollbackSwitch:
    """§12.6：回退开关关闭时视图与行为等价于本票之前的形状（等式测试）。"""

    @pytest.mark.asyncio
    async def test_switch_off_equals_pre_t11e_shape(self, monkeypatch):
        """`NEUROVA_CONTEXT_ROLLUP=0`：不启动 worker，折叠产物逐字等价。"""
        monkeypatch.setenv("NEUROVA_CONTEXT_ROLLUP", "0")
        orch = _orchestrator(agentId="a-t11e-off")
        calls = {"n": 0}

        async def flaky(dropped, previous_summary=""):
            calls["n"] += 1
            return None

        orch._window_summarizer = flaky
        view = await _build(orch, [_longRound(i) for i in range(30)])

        assert orch.foldRollupWorker() is None, "开关关闭却仍然装配了 rollup worker"
        readout = orch.get_context_health()["fold_rollup"]
        assert readout["dispatched"] == 0, f"开关关闭仍有派发：{readout}"
        assert readout["in_flight"] == 0, f"开关关闭仍有在飞任务：{readout}"
        # 视图等价物：失败时仍是静态折叠桩（T-11c 之前的形状）
        stubs = [
            m
            for m in view
            if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))
        ]
        assert stubs, f"开关关闭后失败形状丢了静态折叠桩：{[m.get('role') for m in view][:4]}"

    @pytest.mark.asyncio
    async def test_readout_shape_is_single_source(self):
        """空形状取自 `_emptyContextHealth()` 单源（不再各处写一份字段表）。"""
        orch = _orchestrator(agentId="a-t11e-shape")
        readout = orch.get_context_health()["fold_rollup"]
        assert readout == {
            "dispatched": 0,
            "succeeded": 0,
            "failed": 0,
            "in_flight": 0,
            "dropped": 0,
            "last_error": None,
        }, f"空形状与单源不一致：{readout}"
