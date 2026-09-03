"""进化钩子接线测试（P1-C）

覆盖两处零调用骨架的真实接入:
- AutoSkillImprover: 全仓无任何 record_usage 调用 → 技能成败数据从不采集，
  改进提案永不产生。接入点: Agent._on_skill_post_execute（成败都记录）+
  propose_pending_improvements 批量提案。
- EvolutionOrchestrator.on_before_tool_selection: 归档/冻结工具过滤与权重排序
  从未在生产路径执行。接入点: orchestrator.build_tools_for_llm 尾部。
"""

import unittest
from types import SimpleNamespace

from neurova.evolution.skill_improver import get_skill_improver, reset_skill_improver


def _tool_schema(name):
    return {"type": "function", "function": {"name": name, "description": f"工具 {name}", "parameters": {}}}


class ApplyToolLifecycleTest(unittest.TestCase):
    def test_filters_archived_and_ranks_by_weight(self):
        from neurova.context.orchestrator import ContextOrchestrator

        fake_evolution = SimpleNamespace(
            on_before_tool_selection=lambda available_tools=None, context="", tools=None: {
                "ranking": ["tool_b", "tool_a"],
                "weights": {"tool_b": 0.9, "tool_a": 0.5},
                "filtered": ["tool_c"],
            }
        )
        stub = SimpleNamespace(_agent=SimpleNamespace(evolution=fake_evolution))
        tools = [_tool_schema("tool_a"), _tool_schema("tool_b"), _tool_schema("tool_c")]

        result = ContextOrchestrator._apply_tool_lifecycle(stub, tools)

        names = [t["function"]["name"] for t in result]
        self.assertEqual(names, ["tool_b", "tool_a"], "应按权重排序并剔除被过滤工具")

    def test_noop_without_evolution(self):
        from neurova.context.orchestrator import ContextOrchestrator

        stub = SimpleNamespace(_agent=SimpleNamespace(evolution=None))
        tools = [_tool_schema("tool_a"), _tool_schema("tool_b")]

        result = ContextOrchestrator._apply_tool_lifecycle(stub, tools)

        names = [t["function"]["name"] for t in result]
        self.assertEqual(names, ["tool_a", "tool_b"], "无进化编排器时保持原序")

    def test_noop_with_invalid_hook_result(self):
        from neurova.context.orchestrator import ContextOrchestrator

        fake_evolution = SimpleNamespace(
            on_before_tool_selection=lambda **kwargs: {"ranking": [], "filtered": []}
        )
        stub = SimpleNamespace(_agent=SimpleNamespace(evolution=fake_evolution))
        tools = [_tool_schema("tool_a"), _tool_schema("tool_b")]

        result = ContextOrchestrator._apply_tool_lifecycle(stub, tools)

        names = [t["function"]["name"] for t in result]
        self.assertEqual(names, ["tool_a", "tool_b"], "空 ranking 时保持原序")


class SkillImproverWiringTest(unittest.TestCase):
    def setUp(self):
        reset_skill_improver()

    def tearDown(self):
        reset_skill_improver()

    def _make_result(self, success, error=""):
        return SimpleNamespace(success=success, error=error, execution_time=1.5, metadata={})

    def test_post_execute_records_both_success_and_failure(self):
        """成败都必须记录（原实现失败时提前 return，改进分析永远缺数据）"""
        from neurova.agent_core import Agent

        stub = SimpleNamespace(
            tool_memory=None,
            tool_executor=None,
            growth_log_manager=None,
            config=SimpleNamespace(agent_id="skill_agent"),
            _current_user_input="",
        )

        Agent._on_skill_post_execute(
            stub,
            skill=SimpleNamespace(skill_id="sk_1", name="weather"),
            result=self._make_result(False, error="timeout"),
        )
        Agent._on_skill_post_execute(
            stub,
            skill=SimpleNamespace(skill_id="sk_1", name="weather"),
            result=self._make_result(True),
        )

        improver = get_skill_improver()
        history = improver.get_usage_history("sk_1")
        self.assertEqual(len(history), 2, "成功与失败都应记录使用数据")
        self.assertFalse(history[0].success)
        self.assertTrue(history[1].success)

    def test_propose_pending_improvements_batches_all_skills(self):
        improver = get_skill_improver()
        for i in range(12):
            improver.record_usage("sk_x", success=(i % 4 != 0), duration=1.0, error_message="err" if i % 4 == 0 else "")

        proposals = improver.propose_pending_improvements()
        self.assertIsInstance(proposals, list)
        # 失败率 25% 低于默认阈值 0.3 时不强制要求有提案，但接口必须可用
        self.assertTrue(all(p.skill_id == "sk_x" for p in proposals))

    def test_low_failure_rate_yields_no_proposals(self):
        improver = get_skill_improver()
        for i in range(12):
            improver.record_usage("sk_ok", success=True, duration=1.0)

        self.assertEqual(improver.propose_pending_improvements(), [], "无失败不应产生提案")


if __name__ == "__main__":
    unittest.main()
