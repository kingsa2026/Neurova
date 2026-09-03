"""断点 A 修复契约测试：工具执行反馈 → 自适应权重的传动轴。

背景（闭环审计）：AdaptiveToolWeights.update_weight（失败 ×0.95 → adaptive_multiplier
下降 → _get_dynamic_threshold 阈值上升 → 更难 auto_execute）与动态阈值的齿轮
早已存在，但真实执行反馈（ToolExecutor.on_tool_executed）从未调用权重更新——
闭环有齿轮无传动轴。重复失败的工具仍可能被重复选中自动执行。

契约：
- 真实失败 → update_weight(success=False) + multiplier 下降 + 动态阈值上升
- 真实成功 → update_weight(success=True) + multiplier 上升
- 策略拒绝（governance/pending_approval，断点 B 口径）→ 不更新权重
- 权重与 _get_dynamic_threshold 共用同一实例（agent_core 装配语义）
"""

import unittest
from unittest.mock import Mock, patch

from neurova.evolution.closed_loop import AdaptiveToolWeights
from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
    ToolMemoryIntegration,
)
from neurova.tool_executor import ToolExecutor


class TestExecutorFeedbackWiring(unittest.TestCase):
    """传动轴：on_tool_executed 调用 evolution.tool_weights.update_weight。"""

    def _executor_with(self):
        executor = object.__new__(ToolExecutor)
        agent = Mock()
        weights = AdaptiveToolWeights()
        weights.register_tool("computer_shell", base_weight=1.0)
        agent.evolution = Mock()
        agent.evolution.tool_weights = weights
        agent.tool_memory = None  # 隔离记忆路径，只测权重路径
        agent.tool_lifecycle = None
        executor._agent = agent
        return executor, weights, agent.evolution

    def _call(self, executor, success, result=None):
        executor.on_tool_executed(
            tool_name="computer_shell",
            params={"command": "ls"},
            user_input="ls",
            success=success,
            tool_source="builtin",
            execution_time=0.5,
            result=result or ({"content": "ok"} if success else {"success": False}),
        )

    def test_success_updates_weight_with_real_args(self):
        executor, weights, evolution = self._executor_with()
        with patch.object(evolution.tool_weights, "update_weight") as mw:
            self._call(executor, success=True)
        mw.assert_called_once_with("computer_shell", True, 0.5)
        # 真实对象同样上升（上面 patch 不影响实例自身行为断言）
        self.assertGreater(
            self._multiplier_after(evolution, success=True), 1.0)

    def _multiplier_after(self, evolution, success: bool) -> float:
        """以真实实例调用 update 后读取 multiplier（隔离 patch 影响）。"""
        if success:
            evolution.tool_weights.update_weight("computer_shell", True)
        else:
            evolution.tool_weights.update_weight("computer_shell", False)
        w = evolution.tool_weights.get_weight("computer_shell")
        return w.adaptive_multiplier

    def test_failure_lowers_multiplier(self):
        executor, weights, evolution = self._executor_with()
        with patch.object(evolution.tool_weights, "update_weight") as mw:
            self._call(executor, success=False)
        mw.assert_called_once_with("computer_shell", False, 0.5)
        self.assertLess(self._multiplier_after(evolution, success=False), 1.0)

    def test_policy_denial_skips_weight_update(self):
        """策略拒绝（断点 B 口径）不更新权重。"""
        executor, weights, evolution = self._executor_with()
        with patch.object(evolution.tool_weights, "update_weight") as mw:
            self._call(
                executor, success=False,
                result={"success": False, "governance": {"decision": "deny"}},
            )
        mw.assert_not_called()

    def test_no_evolution_is_noop(self):
        """agent 无 evolution：不抛异常、不阻断（可选增强容错）。"""
        executor = object.__new__(ToolExecutor)
        agent = Mock()
        del agent.evolution
        agent.tool_memory = None
        agent.tool_lifecycle = None
        executor._agent = agent
        self._call(executor, success=True)  # 不抛异常


class TestWeightThresholdLink(unittest.TestCase):
    """联动验证：multiplier 下降 → 动态阈值上升（与装配同一实例语义）。"""

    def _threshold_for(self, weights: AdaptiveToolWeights, tool_name: str) -> float:
        integration = ToolMemoryIntegration(
            memory_layer=None,
            muscle_memory=None,
            tool_weights=weights,  # 与 agent_core 装配语义一致：同一实例
        )
        return integration._get_dynamic_threshold(tool_name)

    def test_failure_raises_threshold(self):
        weights = AdaptiveToolWeights()
        weights.register_tool("tool_a", base_weight=1.0)

        before = self._threshold_for(weights, "tool_a")
        for _ in range(3):
            weights.update_weight("tool_a", False)  # ×0.95³ ≈ 0.857
        after = self._threshold_for(weights, "tool_a")

        self.assertGreater(after, before)  # 失败 → 更难自动执行

    def test_success_lowers_threshold(self):
        weights = AdaptiveToolWeights()
        weights.register_tool("tool_a", base_weight=1.0)

        before = self._threshold_for(weights, "tool_a")
        weights.update_weight("tool_a", True)  # ×1.05
        after = self._threshold_for(weights, "tool_a")

        self.assertLess(after, before)  # 成功 → 更易自动执行


if __name__ == "__main__":
    unittest.main()
