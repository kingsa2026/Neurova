"""元认知认知负荷闭环测试（P1-E）

覆盖 memory_layer/meta_cognition.py 的 MetaCognition 认知负荷类从零调用到真实闭环:
- 每轮对话后用真实轮次指标（工具数/错误率/耗时/记忆规模）更新认知状态
- should_consolidate（低负荷适合整合，高负荷不整合）在轮次间隔门内触发记忆巩固
  （认知负荷 → 睡眠整理 闭环）
"""

import asyncio
import unittest
from types import SimpleNamespace

from neurova.post_chat_pipeline import PostChatPipeline, StepResult, StepStatus


def _make_fake_agent(agent_id="meta_agent", turn_count=10, trigger_recorder=None):
    def _trigger():
        if trigger_recorder is not None:
            trigger_recorder.append(True)
        return {"ok": True}

    idle_tracker = SimpleNamespace(trigger_consolidation=_trigger)
    return SimpleNamespace(
        config=SimpleNamespace(agent_id=agent_id),
        idle_tracker=idle_tracker,
        turn_count=turn_count,
        memory_manager=None,
    )


def _add_steps(pipeline, specs):
    """specs: list of (step_name, status, duration_ms)"""
    for step_name, status, duration_ms in specs:
        pipeline._step_results_store.append(
            StepResult(step_name=step_name, status=status, duration_ms=duration_ms)
        )


class MetaCognitionLoopTest(unittest.TestCase):
    def setUp(self):
        from neurova.cognitive_layers.memory_layer.meta_cognition import reset_meta_cognition

        reset_meta_cognition()

    def tearDown(self):
        from neurova.cognitive_layers.memory_layer.meta_cognition import reset_meta_cognition

        reset_meta_cognition()

    def test_rsi_step_updates_cognitive_state_with_turn_metrics(self):
        triggered = []
        agent = _make_fake_agent(trigger_recorder=triggered)
        pipeline = PostChatPipeline(agent)
        _add_steps(
            pipeline,
            [("tool_a", StepStatus.EXECUTED, 100.0), ("reflection", StepStatus.SKIPPED, 1.0)],
        )

        asyncio.run(pipeline._step_rsi_iteration())

        from neurova.cognitive_layers.memory_layer.meta_cognition import get_meta_cognition

        state = get_meta_cognition("meta_agent").get_state()
        self.assertIsNotNone(state, "RSI 步骤应更新认知负荷状态（此前零调用）")
        self.assertEqual(state.metadata.get("turn_steps"), 2)
        self.assertEqual(state.active_tasks, 1, "工具步骤数应计入 active_tasks")
        self.assertAlmostEqual(state.response_time_ms, 101.0)

    def test_low_load_at_interval_triggers_consolidation(self):
        triggered = []
        agent = _make_fake_agent(turn_count=10, trigger_recorder=triggered)
        pipeline = PostChatPipeline(agent)  # 无失败步骤 → 低负荷

        asyncio.run(pipeline._step_rsi_iteration())

        self.assertEqual(len(triggered), 1, "低负荷 + 到达轮次间隔应触发记忆巩固")

    def test_high_load_does_not_trigger_consolidation(self):
        triggered = []
        agent = _make_fake_agent(turn_count=10, trigger_recorder=triggered)
        pipeline = PostChatPipeline(agent)
        # 高负荷: 全部失败(error=1.0) + 5 个工具步(tasks=0.5) + 高耗时 + 大记忆规模
        _add_steps(
            pipeline,
            [(f"tool_{i}", StepStatus.FAILED, 8000.0) for i in range(5)],
        )
        agent.memory_manager = SimpleNamespace(get_memory_count=lambda: 9000)

        asyncio.run(pipeline._step_rsi_iteration())

        self.assertEqual(triggered, [], "高负荷时不应触发整合（should_consolidate 契约）")

    def test_consolidation_only_at_turn_interval(self):
        triggered = []
        agent = _make_fake_agent(turn_count=5, trigger_recorder=triggered)  # 未到间隔
        pipeline = PostChatPipeline(agent)

        asyncio.run(pipeline._step_rsi_iteration())

        self.assertEqual(triggered, [], "未到轮次间隔不得触发整合（避免每轮整理）")


if __name__ == "__main__":
    unittest.main()
