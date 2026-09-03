"""
端到端测试: 棘轮剪枝递归进化机制完整闭环 — 根因 4 验证

完整链路:
  1. 经验记录(经验反馈系统)
  2. 触发 RSI 迭代(节流后)
  3. RSI 内部: 结晶 + 棘轮剪枝 + 应用
  4. 进化状态更新(工具权重/生命周期)
  5. 下一次迭代收敛

该测试使用真实的 EvolutionOrchestrator + 真实 RSIOrchestrator(若可用),
不可用时回退到 stub,但仍验证端到端信号链。
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestEndToEndRSIClosedLoop:
    """根因 4: 经验→RSI→剪枝→应用 端到端闭环"""

    def test_signal_chain_experience_to_rsi_iteration(self):
        """端到端: 经验记录后, RSI 真正被迭代(节流可绕过)"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 真实 RSI 实例(用 Mock 模拟, 但接口签名一致)
        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {
            "convergence": 0.75,
            "applied_count": 2,
            "gain": 0.15,
            "pruned_count": 1,
        }
        mock_rsi.should_continue.return_value = False

        # 1. 构造 orchestrator 并注入 RSI
        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        orch.register_tools(["tool_a", "tool_b"])

        # 2. 记录 5 次经验(部分成功, 部分失败)
        results = []
        for i in range(5):
            r = orch.on_experience_recorded(
                text=f"经验 #{i}",
                task="e2e_test",
                tools=["tool_a"],
                success=(i % 2 == 0),
            )
            results.append(r)

        # 3. 验证: 经验记录都返回了 rsi 字段
        for r in results:
            assert "rsi" in r, "每条经验记录都必须返回 rsi 字段"
            assert "triggered" in r["rsi"], "rsi 字段必须包含 triggered 标记"

        # 4. 主动触发 RSI 迭代(force 跳过节流)
        rsi_result = orch.on_rsi_iterate(force=True)

        # 5. 验证: RSI.run_iteration 被实际调用
        assert mock_rsi.run_iteration.called, (
            "端到端: 主动触发后, RSI.run_iteration 必须被调用"
        )

        # 6. 验证: 迭代结果被正确暴露
        assert rsi_result["triggered"] is True
        assert rsi_result["iteration"] >= 1
        assert rsi_result["convergence"] == 0.75
        assert rsi_result["applied_count"] == 2

    def test_closed_loop_with_real_rsi_orchestrator_if_available(self):
        """若 RSIOrchestrator 真实可导入, 验证完整真实链路"""
        try:
            from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        except ImportError:
            pytest.skip("RSIOrchestrator 不可用")

        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 用真实 RSIOrchestrator, 传入 4 个最小 MagicMock 系统
        try:
            real_rsi = RSIOrchestrator(
                sleep_system=MagicMock(),
                emotion_system=MagicMock(),
                experience_system=MagicMock(),
                tool_memory_system=MagicMock(),
            )
        except Exception as e:
            pytest.skip(f"RSIOrchestrator 实例化失败: {e}")

        orch = EvolutionOrchestrator(rsi_orchestrator=real_rsi)
        orch.register_tools(["test_tool"])

        # 经验记录
        result = orch.on_experience_recorded(
            text="real RSI test",
            task="e2e_real",
            tools=["test_tool"],
            success=True,
        )
        assert "rsi" in result

        # 主动触发 RSI 迭代
        rsi_result = orch.on_rsi_iterate(force=True)
        # 真实 RSI 必须返回 triggered=True(无异常)
        if rsi_result.get("triggered") is False and rsi_result.get("reason") == "error":
            pytest.fail(f"真实 RSI 迭代报错: {rsi_result.get('error')}")
        assert rsi_result["triggered"] is True

    def test_throttling_protection_under_burst_load(self):
        """高频经验记录不会触发 RSI 风暴"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {
            "convergence": 0.5,
            "applied_count": 0,
            "gain": 0.0,
        }
        mock_rsi.should_continue.return_value = False

        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        orch._rsi_iteration_interval = 999.0  # 1秒内不重复

        # 触发 100 次经验记录
        for i in range(100):
            orch.on_experience_recorded(
                text=f"burst #{i}",
                task="burst_test",
                tools=[],
                success=True,
            )

        # 由于节流, RSI.run_iteration 最多被调用 1 次
        call_count = mock_rsi.run_iteration.call_count
        assert call_count <= 1, (
            f"节流失效: 100 次经验记录后 RSI 被调用 {call_count} 次, 应 <= 1"
        )

    def test_singleton_shares_state_via_injection(self):
        """验证: agent_core.py 注入后, 单例 evolution 的 RSI 状态可被所有调用方观察"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 模拟"单例" + 注入模式
        singleton = EvolutionOrchestrator()
        assert singleton.rsi_orchestrator is None  # 初始为空

        # 模拟 agent_core.py 注入
        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {"convergence": 0.8, "applied_count": 1, "gain": 0.2}
        mock_rsi.should_continue.return_value = False
        singleton.rsi_orchestrator = mock_rsi

        # 所有后续调用共享同一 RSI
        assert singleton.rsi_orchestrator is mock_rsi
        singleton._last_rsi_iteration_at = 0.0
        result = singleton.on_experience_recorded(
            text="shared test",
            task="shared",
            tools=[],
            success=True,
        )
        assert result["rsi"]["triggered"] is True
        assert mock_rsi.run_iteration.called


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
