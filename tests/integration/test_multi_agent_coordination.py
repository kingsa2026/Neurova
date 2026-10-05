# -*- coding: utf-8 -*-
"""多 Agent 协调层集成测试：glance yield / small-brain triage / A-B 实验

历史与本次收缩：本文件原有 6 组组件 18 例，其中 `neurova.agents.seen_boundary` 与
`neurova.agents.wake_debounce` 两个被测模块**不存在**——前者由
`neurova/collaboration/seen_cursor.py` 以同步管理器重塑（命名与签名均变，
`get_seen_boundary()` / `await check_freshness()` 那套异步形态已无对应），后者从未实现
（摘除记账见 `neurova/api/endpoints/coordination_api.py:161-172`）。两条死导入让整个
文件在 collection 阶段即报错，连带 `tests/integration` 全目录无法收集——**活的一半
一条也没在跑**。死设计对应的组随本批删除；给 `seen_cursor` 按其真实语义补覆盖应另批做。

两条必须记住的形态：

1. `reset_glance_yield_checker()` 与 `reset_ab_test_manager()` 是 `async def`。裸调用
   只创建协程、从不执行，于是这两个单例在用例之间**永不重置**——
   `registered_agents == 2` 之类断言只在"恰好第一个跑"时才成立。本文件统一经
   `_freshChecker()` / `_freshManager()` / `_freshGate()` 先重置再取实例，去掉执行顺序
   耦合。（`reset_small_brain_triage_gate()` 是同步函数。）
2. 断言一律取具体值。原 `assert stats[...]["total_checks"] >= 0` 对计数器恒真，等价于
   没有断言（AGENTS.md 修复教义第 2 条禁止降级断言）。另注
   `GlanceYieldChecker._stats` 的 `yields` 只在 :109 初始化、从不累加，
   `get_stats()["yields"]` 恒为 0——因此本文件不断言它，该缺陷单独记账。
"""

import time

import pytest

from neurova.collaboration.glance_yield_rules import (
    GlanceYieldChecker,
    YieldReason,
    get_glance_yield_checker,
    reset_glance_yield_checker,
)
from neurova.experiments.ab_test_manager import (
    ExperimentConfig,
    ExperimentGroup,
    get_ab_test_manager,
    reset_ab_test_manager,
)
from neurova.llm.triage import (
    get_small_brain_triage_gate,
    reset_small_brain_triage_gate,
)


async def _freshChecker() -> GlanceYieldChecker:
    """重置并取回全新 yield 检查器（重置是 async，漏 await 即等于没重置）。"""
    await reset_glance_yield_checker()
    return await get_glance_yield_checker()


async def _freshManager():
    """重置并取回全新 A-B 实验管理器（同上，reset 为 async）。"""
    await reset_ab_test_manager()
    return await get_ab_test_manager()


def _freshGate():
    """重置并取回全部分流门（同步单例）。"""
    reset_small_brain_triage_gate()
    return get_small_brain_triage_gate()


class TestYieldChecker:
    """GLANCE_YIELD 规则链：模型钉 + 并发上限"""

    @pytest.mark.asyncio
    async def test_yield_checker_is_singleton(self):
        checker1 = await get_glance_yield_checker()
        checker2 = await get_glance_yield_checker()

        assert checker1 is checker2

    @pytest.mark.asyncio
    async def test_registered_agents_are_counted(self):
        checker = await _freshChecker()

        checker.register_agent("agent_1", "gpt-4o")
        checker.register_agent("agent_2", "gpt-4o-mini")

        assert checker.get_stats()["registered_agents"] == 2

    @pytest.mark.asyncio
    async def test_concurrency_cap_forces_yield_on_seventh_check(self):
        """同模型前 N 次放行、第 N+1 次让位，上限值直接取常量而非抄注释。

        原用例注释把 DEFAULT_MAX_CONCURRENT_AGENTS 写成 10，实际是 6——数值漂移时
        应当由断言自己说话，而不是靠注释里的手抄数字。
        """
        checker = await _freshChecker()
        limit = GlanceYieldChecker.DEFAULT_MAX_CONCURRENT_AGENTS
        checker.register_agent("agent_1", "gpt-4o")

        decisions = [
            checker.check_yield_rules(
                agent_id=f"agent_{i}",
                model_name="gpt-4o",
                proposed_operations=["do_task"],
            )
            for i in range(limit + 1)
        ]

        assert [d.should_yield for d in decisions] == [False] * limit + [True]
        last = decisions[-1]
        assert last.reason is YieldReason.CONCURRENT_AGENT
        assert last.details["max_allowed"] == limit
        assert last.wait_time_seconds > 0

    @pytest.mark.asyncio
    async def test_model_pin_violation_yields_with_its_own_reason(self):
        """钉了模型的 agent 换模型执行必须让位，理由不得与并发让位混淆。

        替代原来的条件断言：`if decision.should_yield and decision.reason:` 里面才
        assert，两个前提都不成立时整条用例什么都不检查就算通过。
        """
        checker = await _freshChecker()
        checker.register_agent("agent_1", "gpt-4o")

        decision = checker.check_yield_rules(
            agent_id="agent_1",
            model_name="gpt-4o-mini",
            proposed_operations=["task"],
        )

        assert decision.should_yield is True
        assert decision.reason is YieldReason.MODEL_PIN_VIOLATION

    @pytest.mark.asyncio
    async def test_check_counters_match_actual_calls(self):
        """计数器与实际调用数一致——替掉 `>= 0` 那类恒真断言。"""
        checker = await _freshChecker()
        checker.register_agent("agent_1", "gpt-4o")

        for _ in range(3):
            checker.check_yield_rules(
                agent_id="agent_1",
                model_name="gpt-4o",
                proposed_operations=["task"],
            )

        stats = checker.get_stats()
        assert stats["total_checks"] == 3
        assert stats["proceeds"] == 3


class TestTriageGate:
    """小脑分流门"""

    def test_triage_gate_is_singleton(self):
        assert get_small_brain_triage_gate() is get_small_brain_triage_gate()

    @pytest.mark.asyncio
    async def test_empty_history_is_actionable_for_a_stated_reason(self):
        gate = _freshGate()

        result = await gate.triage_message("empty_conv")

        assert result.actionable is True
        assert result.reason == "no_history"

    @pytest.mark.asyncio
    async def test_triage_counts_every_call(self):
        gate = _freshGate()

        await gate.triage_message("conv_1")
        await gate.triage_message("conv_2")

        assert gate.get_stats()["total_tries"] == 2


class TestABTestManager:
    """A/B 实验生命周期与流量分配"""

    @pytest.mark.asyncio
    async def test_ab_test_manager_is_singleton(self):
        manager1 = await get_ab_test_manager()
        manager2 = await get_ab_test_manager()

        assert manager1 is manager2

    @pytest.mark.asyncio
    async def test_experiment_lifecycle(self):
        manager = await _freshManager()
        config = ExperimentConfig(
            name="test_coordination_v1",
            description="Test coordination rules",
            groups=[ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT],
            traffic_split={
                ExperimentGroup.CONTROL: 0.5,
                ExperimentGroup.TREATMENT: 0.5,
            },
            metrics=["success_rate", "latency_ms"],
            duration_days=7,
            min_sample_size=10,
        )

        assert await manager.start_experiment(config) is True

        group = await manager.get_experiment_group("agent_1", "test_coordination_v1")
        assert group in (ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT)

        await manager.record_metric(
            experiment_name="test_coordination_v1",
            group=group,
            metrics={"success_rate": 0.8, "latency_ms": 150},
            context={"task_type": "test"},
        )

        assert await manager.end_experiment("test_coordination_v1") is True
        assert await manager.get_experiment_results("test_coordination_v1") is not None

    @pytest.mark.asyncio
    async def test_same_agent_always_gets_the_same_group(self):
        manager = await _freshManager()
        await manager.start_experiment(
            ExperimentConfig(
                name="split_test",
                description="Test traffic splitting",
                groups=[ExperimentGroup.CONTROL, ExperimentGroup.TREATMENT],
                traffic_split={
                    ExperimentGroup.CONTROL: 0.3,
                    ExperimentGroup.TREATMENT: 0.7,
                },
                metrics=["metric1"],
                duration_days=1,
            )
        )

        group1 = await manager.get_experiment_group("consistent_agent", "split_test")
        group2 = await manager.get_experiment_group("consistent_agent", "split_test")

        assert group1 == group2


class TestCoordinationWorkflow:
    """活组件串起来的协调路径（原用例还挂着两个已不存在的组件）"""

    @pytest.mark.asyncio
    async def test_yield_then_triage_then_record_metric(self):
        checker = await _freshChecker()
        manager = await _freshManager()
        gate = _freshGate()

        checker.register_agent("agent_1", "gpt-4o")
        assert await manager.start_experiment(
            ExperimentConfig(
                name="full_workflow_test",
                description="Complete workflow test",
                groups=[ExperimentGroup.TREATMENT],
                traffic_split={ExperimentGroup.TREATMENT: 1.0},
                metrics=["turn_count"],
                duration_days=1,
            )
        ) is True

        decision = checker.check_yield_rules(
            agent_id="agent_1",
            model_name="gpt-4o",
            proposed_operations=["workflow_task"],
            conversation_id="workflow_conv",
        )
        assert decision.should_yield is False

        assert (await gate.triage_message("workflow_conv")).actionable is True

        group = await manager.get_experiment_group("agent_1", "full_workflow_test")
        await manager.record_metric(
            experiment_name="full_workflow_test",
            group=group,
            metrics={"turn_count": 1},
            context={},
        )

        assert checker.get_stats()["total_checks"] == 1
        assert checker.get_stats()["registered_agents"] == 1
        # 结果只在实验结束后可得（运行中 get_experiment_results 返回 None）：
        # 先收尾，再断指标真的落了账。
        assert await manager.end_experiment("full_workflow_test") is True
        results = await manager.get_experiment_results("full_workflow_test")
        assert results is not None


class TestCoordinationOverhead:
    """让位判定在每轮热路径上，开销必须有界"""

    @pytest.mark.asyncio
    async def test_coordination_overhead_under_one_millisecond(self):
        checker = await _freshChecker()
        checker.register_agent("perf_agent", "gpt-4o")

        iterations = 100
        start = time.perf_counter()
        for i in range(iterations):
            checker.check_yield_rules(
                agent_id="perf_agent",
                model_name="gpt-4o",
                proposed_operations=[f"task_{i}"],
            )
        avgMs = (time.perf_counter() - start) / iterations * 1000

        assert avgMs < 1.0, f"协调层单次判定开销 {avgMs:.2f}ms，超过 1ms 预算"
