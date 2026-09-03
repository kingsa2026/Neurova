"""
TDD RED-1：暴露 RSI 棘轮剪枝进化机制无效问题

验证 RSIOrchestrator.run_iteration() 在收到非空反馈信号时：
1. 应产生非空优化建议列表（当前 _generate_optimization_for_param 永远 return None）
2. 应调用 convergence_analyzer.record_iteration() 喂入收敛数据
   （当前从未调用，导致 analyze_convergence 永远返回 insufficient_data）

根因（P0-2 + P0-3）：
    neurova/evolution/rsi/orchestrator.py:162
        def _generate_optimization_for_param(...):
            return None   # 永远不产生优化
    neurova/evolution/rsi/orchestrator.py:72-108
        run_iteration() 从未调用 convergence_analyzer.record_iteration()
        → gain_history 永远为空 → analyze_convergence 永远 insufficient_data
"""

import pytest
from unittest.mock import Mock, MagicMock


def _create_real_orchestrator_with_signals():
    """创建带真实反馈信号的 RSIOrchestrator（非 _NullSystem）"""
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    # 构造带真实反馈信号和可优化参数的闭环系统
    sleep_system = Mock()
    sleep_system.get_feedback = Mock(return_value={
        "decay_rate": 0.15,
        "merge_count": 5,
        "performance_score": 0.82,
    })
    sleep_system.base_decay_rate = 0.1
    sleep_system.similarity_threshold = 0.8
    sleep_system.merge_threshold = 0.9

    emotion_system = Mock()
    emotion_system.get_feedback = Mock(return_value={
        "stability": 0.75,
        "emotional_events": 3,
    })
    emotion_system.emotional_protection_threshold = 0.5
    emotion_system.emotional_protection_factor = 1.2

    experience_system = Mock()
    experience_system.get_feedback = Mock(return_value={
        "pattern_count": 12,
        "success_rate": 0.68,
    })
    experience_system.crystallize_min_observations = 3
    experience_system.crystallize_min_success_rate = 0.7
    experience_system.pattern_min_support = 2

    tool_memory_system = Mock()
    tool_memory_system.get_feedback = Mock(return_value={
        "tool_count": 8,
        "avg_success_rate": 0.72,
    })
    tool_memory_system.success_bonus = 0.1
    tool_memory_system.failure_penalty = 0.2
    tool_memory_system.decay_rate = 0.05
    tool_memory_system.muscle_memory_threshold = 0.85

    orch = RSIOrchestrator(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
    )
    # 启用低风险自动执行，使优化建议能被实际应用（否则 applied_count=0，
    # 按修正后的语义不喂入收敛数据，状态保持 insufficient_data 属正常观察行为）
    orch.deployment_controller._current_phase = 2
    return orch


class TestRSIOrchestratorEffectiveness:
    """测试 RSI 编排器是否真实产生进化效果"""

    def test_run_iteration_produces_optimizations_when_signals_exist(self):
        """run_iteration 在有反馈信号时应产生非空优化建议列表

        场景：四大闭环系统提供非空反馈信号（performance_score=0.82 等）
        期望：run_iteration 返回的 optimizations 列表非空
        当前：_generate_optimization_for_param 永远 return None → optimizations 永远空
        """
        orchestrator = _create_real_orchestrator_with_signals()

        result = orchestrator.run_iteration()

        assert isinstance(result, dict), "run_iteration 应返回 dict"
        optimizations = result.get("optimizations", [])
        assert len(optimizations) > 0, (
            f"有反馈信号时 run_iteration 应产生非空优化建议，"
            f"实际 optimizations 为空（_generate_optimization_for_param 永远 return None）。"
            f"反馈信号: {result.get('feedback_signals')}"
        )

    def test_run_iteration_records_convergence_data(self):
        """run_iteration 应调用 convergence_analyzer.record_iteration() 喂入收敛数据

        场景：run_iteration 执行一次迭代
        期望：convergence_analyzer.gain_history 非空（至少 1 个数据点）
        当前：run_iteration 从未调用 record_iteration → gain_history 永远空
              → analyze_convergence 永远返回 insufficient_data
        """
        orchestrator = _create_real_orchestrator_with_signals()

        orchestrator.run_iteration()

        gain_history = orchestrator.convergence_analyzer.gain_history
        assert len(gain_history) > 0, (
            "run_iteration 应调用 record_iteration 喂入增益数据，"
            "实际 gain_history 为空（analyze_convergence 永远返回 insufficient_data）"
        )

    def test_convergence_status_not_always_insufficient_data(self):
        """多次迭代后收敛状态不应永远是 insufficient_data

        场景：运行 window_size+1 次迭代
        期望：convergence status 不再是 insufficient_data
        当前：因 record_iteration 未被调用，永远 insufficient_data
        """
        orchestrator = _create_real_orchestrator_with_signals()

        # 运行足够多次迭代以填满 window_size（默认 20）
        for _ in range(orchestrator.convergence_analyzer.window_size + 1):
            orchestrator.run_iteration()

        convergence = orchestrator.convergence_analyzer.analyze_convergence()
        status = convergence.get("status")
        assert status != "insufficient_data", (
            f"运行 {orchestrator.convergence_analyzer.window_size + 1} 次迭代后，"
            f"收敛状态不应仍是 insufficient_data，实际: {status}。"
            f"gain_history 长度: {len(orchestrator.convergence_analyzer.gain_history)}"
        )
