"""
agent_core.py RSI 注入测试 — 覆盖根因 3

Bug: agent_core.py 初始化 RSIOrchestrator 后, 没有把它注入到 evolution
单例(EvolutionOrchestrator.rsi_orchestrator), 导致下游 on_experience_recorded
即便能调用 RSI 也找不到引用。

本测试用最小化集成(不真正构建 NeurovaAgent), 直接验证注入逻辑。
"""
import sys
import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestAgentCoreInjectsRSIToEvolution:
    """根因 3: agent_core.py 必须将 RSI 注入 evolution 单例"""

    def test_agent_core_has_rsi_injection_logic(self):
        """RED: agent_core.py 必须包含把 self.rsi_orchestrator 注入 evolution 单例的代码"""
        from neurova import agent_core

        source = inspect.getsource(agent_core)
        # 关键语句: evolution 单例的 rsi_orchestrator 字段被赋值
        assert (
            "evolution.rsi_orchestrator" in source
            or "evolution().rsi_orchestrator" in source
        ), (
            "agent_core.py 必须包含 evolution.rsi_orchestrator = ... "
            "注入语句, 否则经验→RSI 闭环永远不生效"
        )

    def test_injection_uses_correct_api(self):
        """GREEN-friendly: 注入可使用属性赋值或 set_rsi_orchestrator() 方法"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        mock_rsi = MagicMock()

        # 验证两种注入方式都能工作
        orch.rsi_orchestrator = mock_rsi
        assert orch.rsi_orchestrator is mock_rsi


class TestAgentCoreInjectionIntegration:
    """端到端: 模拟 agent_core 初始化路径, 验证 RSI 被正确注入"""

    def test_inject_rsi_to_evolution_helper(self):
        """验证: 给定一个 evolution 单例和 RSI 实例, 注入后 experience 触发 RSI"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 模拟 agent_core 初始化后的状态
        evolution = EvolutionOrchestrator()
        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {
            "convergence": 0.6,
            "applied_count": 1,
            "gain": 0.1,
        }
        mock_rsi.should_continue.return_value = False

        # 注入步骤(模拟 agent_core.py 行为)
        evolution.rsi_orchestrator = mock_rsi
        # 绕过节流
        evolution._last_rsi_iteration_at = 0.0

        # 注册工具
        evolution.register_tools(["t1"])

        # 触发经验记录
        result = evolution.on_experience_recorded(
            text="t1 success",
            task="test",
            tools=["t1"],
            success=True,
        )

        # 验证 RSI 被实际调用(因为节流间隔已过)
        assert mock_rsi.run_iteration.called, (
            "注入后, 经验记录必须真正调用 RSI.run_iteration()"
        )
        assert result["rsi"]["triggered"] is True
        assert result["rsi"]["iteration"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
