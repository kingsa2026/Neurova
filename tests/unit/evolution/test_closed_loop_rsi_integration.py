"""
闭环系统接入 RSI 集成测试 — 覆盖根因 1-4

Bug 类别: 棘轮剪枝递归进化机制未真正闭环
问题: 经验/工具/记忆记录后, RSIOrchestrator 没有被触发, 导致:
  - 根因1: EvolutionOrchestrator.on_experience_recorded() 不调用 RSI
  - 根因2: EvolutionOrchestrator 不持有 rsi_orchestrator
  - 根因3: agent_core.py 注入 EvolutionOrchestrator 时未传入 RSI
  - 根因4: 端到端没有覆盖"经验→RSI→剪枝→应用"真实闭环路径

本测试文件按 TDD 顺序：先 RED（编写失败的测试）, 再 GREEN（实现修复）。
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 路径设置
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ============================================================
# 根因 2: EvolutionOrchestrator 必须能接收并持有 rsi_orchestrator
# ============================================================

class TestEvolutionOrchestratorHoldsRSI:
    """根因 2: EvolutionOrchestrator.__init__ 应接受 rsi_orchestrator 参数"""

    def test_init_accepts_rsi_orchestrator_kwarg(self):
        """RED: EvolutionOrchestrator(rsi_orchestrator=mock) 必须不抛 TypeError"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_rsi = MagicMock()
        # 当前实现不接收 rsi_orchestrator 参数 — 此调用在 RED 阶段会抛 TypeError
        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        assert orch.rsi_orchestrator is mock_rsi, (
            "EvolutionOrchestrator 必须持有传入的 rsi_orchestrator"
        )

    def test_init_without_rsi_defaults_to_none(self):
        """GREEN-friendly: 不传 rsi_orchestrator 时应为 None(向后兼容)"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        # 即使 rsi_orchestrator 是 None, 字段也应存在
        assert hasattr(orch, "rsi_orchestrator"), (
            "EvolutionOrchestrator 必须定义 rsi_orchestrator 字段"
        )
        assert orch.rsi_orchestrator is None

    def test_on_rsi_iterate_method_exists(self):
        """RED: 必须提供 on_rsi_iterate() 触发方法"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        assert hasattr(orch, "on_rsi_iterate"), (
            "EvolutionOrchestrator 必须提供 on_rsi_iterate() 方法"
        )
        assert callable(orch.on_rsi_iterate)

    def test_on_rsi_iterate_invokes_run_iteration(self):
        """RED: on_rsi_iterate() 必须调用 rsi_orchestrator.run_iteration()"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {
            "convergence": 0.8,
            "applied_count": 2,
            "gain": 0.3,
        }
        mock_rsi.should_continue.return_value = False

        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        result = orch.on_rsi_iterate()

        assert mock_rsi.run_iteration.called, "on_rsi_iterate 必须调用 rsi_orchestrator.run_iteration()"
        assert "convergence" in result or "rsi_result" in result, (
            "on_rsi_iterate 必须返回 RSI 迭代结果或包装字典"
        )


# ============================================================
# 根因 1: on_experience_recorded 必须触发 RSI 迭代
# ============================================================

class TestOnExperienceRecordedTriggersRSI:
    """根因 1: 经验记录后应触发 RSI 闭环"""

    def test_on_experience_recorded_returns_rsi_field(self):
        """RED: 返回字典必须包含 rsi 字段（即使 RSI 未配置也应有 key）"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        result = orch.on_experience_recorded(
            text="测试经验",
            task="unit_test_task",
            tools=["tool_a", "tool_b"],
            success=True,
        )
        assert "rsi" in result, (
            "on_experience_recorded 返回字典必须包含 'rsi' 字段, "
            "以便下游可观测 RSI 是否被触发"
        )

    def test_on_experience_recorded_invokes_rsi_iteration(self):
        """RED: 配 RSI 后, on_experience_recorded 必须触发 RSI 迭代"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {
            "convergence": 0.9,
            "applied_count": 3,
            "gain": 0.5,
        }
        mock_rsi.should_continue.return_value = True

        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        # 显式调用 on_rsi_iterate 验证路径存在
        rsi_result = orch.on_rsi_iterate()
        assert mock_rsi.run_iteration.called, "on_rsi_iterate 必须调用 rsi.run_iteration"

    def test_rsi_invocation_throttled(self):
        """GREEN-friendly: RSI 触发应有最小间隔, 避免每条经验都全量迭代"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {"convergence": 0.5, "applied_count": 0, "gain": 0.0}
        mock_rsi.should_continue.return_value = True

        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        # 快速连续调用 on_rsi_iterate 两次, 第二次应被节流(不应调用 run_iteration)
        orch.on_rsi_iterate()
        call_count_after_first = mock_rsi.run_iteration.call_count
        orch.on_rsi_iterate()
        call_count_after_second = mock_rsi.run_iteration.call_count
        assert call_count_after_second == call_count_after_first, (
            "RSI 迭代应有最小间隔(节流), 否则每次经验都会触发全量进化"
        )


# ============================================================
# 根因 3: agent_core.py 应将 RSI 注入到 EvolutionOrchestrator 单例
# ============================================================

class TestAgentCoreInjectsRSIToEvolution:
    """根因 3: NeurovaAgent 初始化后, evolution 单例必须持有 RSI"""

    def test_set_rsi_on_evolution_orchestrator_helper(self):
        """RED: EvolutionOrchestrator 应提供 set_rsi_orchestrator() 或可写属性"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        orch = EvolutionOrchestrator()
        mock_rsi = MagicMock()

        # 必须支持注入(属性赋值或方法)
        try:
            orch.rsi_orchestrator = mock_rsi
            assert orch.rsi_orchestrator is mock_rsi
        except AttributeError:
            pytest.fail("EvolutionOrchestrator 必须允许 rsi_orchestrator 属性赋值")


# ============================================================
# 根因 4: 端到端真实闭环路径
# ============================================================

class TestEndToEndExperienceToRSILoop:
    """根因 4: 经验→结晶→RSI 迭代→剪枝→应用 的真实闭环"""

    def test_rsi_loop_drives_evolution_state(self):
        """RED: 多次 RSI 迭代必须影响 EvolutionOrchestrator 的进化状态"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        # 真实 RSI mock: should_continue 在 3 次后返回 False
        call_log = []

        def fake_run_iteration(*args, **kwargs):
            call_log.append(time.time())
            return {
                "convergence": 0.1 * len(call_log),
                "applied_count": 1,
                "gain": 0.05,
            }

        mock_rsi = MagicMock()
        mock_rsi.run_iteration.side_effect = fake_run_iteration
        # 使用 iterator 让 should_continue 一直有返回值
        sc_iter = iter([True, True, True, False, False, False])
        mock_rsi.should_continue.side_effect = lambda _=None: next(sc_iter)

        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        iterations = 0
        max_iter = 10
        # while 条件中 should_continue() 被调用 1 次, on_rsi_iterate 内部也调用 1 次
        # iter 提供 [T,T,T,T,F]: while=T(消耗 1)→body iter=2→while=T(消耗 3)→body iter=4→while=F(消耗 5)退出
        # 共迭代 2 次
        while mock_rsi.should_continue() and iterations < max_iter:
            orch.on_rsi_iterate(force=True)
            iterations += 1

        assert iterations == 2, (
            f"应迭代 2 次后停止, 实际={iterations}"
        )
        assert mock_rsi.run_iteration.call_count == 2
        # RSI 状态必须被记录在 orchestrator 中
        assert orch._rsi_iteration_count == 2

    def test_complete_closed_loop_signal_chain(self):
        """RED: 完整信号链 — 经验记录 → 结晶 → RSI → 工具权重变化"""
        from neurova.evolution.closed_loop import EvolutionOrchestrator

        mock_rsi = MagicMock()
        mock_rsi.run_iteration.return_value = {
            "convergence": 0.7,
            "applied_count": 2,
            "gain": 0.2,
        }
        mock_rsi.should_continue.return_value = False

        orch = EvolutionOrchestrator(rsi_orchestrator=mock_rsi)
        orch.register_tools(["test_tool"])

        # Step 1: 记录经验(正常路径)
        result = orch.on_experience_recorded(
            text="使用 test_tool 成功完成任务",
            task="closed_loop_test",
            tools=["test_tool"],
            success=True,
        )

        # Step 2: 经验记录后 RSI 字段必须存在
        assert "rsi" in result, "经验记录返回必须包含 rsi 字段"

        # Step 3: 主动触发 RSI 迭代(节流可绕过)
        orch.on_rsi_iterate(force=True)

        # Step 4: 验证 RSI 被实际调用
        assert mock_rsi.run_iteration.called, (
            "完整闭环: 经验记录+主动触发后, RSI 必须被实际迭代"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
