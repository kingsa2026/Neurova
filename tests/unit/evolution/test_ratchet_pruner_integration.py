"""
TDD 切片 1：暴露 RecursiveRatchetPruner 未接入 RSIOrchestrator（P0-A1）

验证 RSIOrchestrator 持有 RecursiveRatchetPruner 实例，并在 run_iteration 中
真正调用 recursive_prune 进行多候选方案剪枝。

根因：RecursiveRatchetPruner 643 行完整实现但零生产调用，与 RSIOrchestrator 之间无接线。
"""

import pytest
from unittest.mock import Mock


def _create_real_orchestrator():
    """创建带真实反馈信号的 RSIOrchestrator"""
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    sleep_system = Mock()
    sleep_system.get_feedback = Mock(return_value={"performance_score": 0.65})
    sleep_system.base_decay_rate = 0.1
    sleep_system.similarity_threshold = 0.8
    sleep_system.merge_threshold = 0.9

    emotion_system = Mock()
    emotion_system.get_feedback = Mock(return_value={"stability": 0.6})
    emotion_system.emotional_protection_threshold = 0.5
    emotion_system.emotional_protection_factor = 1.2

    experience_system = Mock()
    experience_system.get_feedback = Mock(return_value={"success_rate": 0.55})
    experience_system.crystallize_min_observations = 3
    experience_system.crystallize_min_success_rate = 0.7
    experience_system.pattern_min_support = 2

    tool_memory_system = Mock()
    tool_memory_system.get_feedback = Mock(return_value={"avg_success_rate": 0.6})
    tool_memory_system.success_bonus = 0.1
    tool_memory_system.failure_penalty = 0.2
    tool_memory_system.decay_rate = 0.05
    tool_memory_system.muscle_memory_threshold = 0.85

    return RSIOrchestrator(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
    )


class TestRecursiveRatchetPrunerIntegration:
    """测试 RecursiveRatchetPruner 接入 RSIOrchestrator"""

    def test_orchestrator_holds_pruner_instance(self):
        """RSIOrchestrator 应持有 RecursiveRatchetPruner 实例"""
        orchestrator = _create_real_orchestrator()

        assert hasattr(orchestrator, "pruner"), "RSIOrchestrator 应持有 pruner 属性"
        assert orchestrator.pruner is not None, "pruner 不应为 None"

    def test_run_iteration_invokes_recursive_prune(self):
        """run_iteration 应调用 recursive_prune 进行多候选剪枝

        场景：有反馈信号时，生成多个候选优化方案，用 recursive_prune 选出最优
        期望：run_iteration 后 pruner.prune_history 非空（证明 recursive_prune 被调用）
        """
        orchestrator = _create_real_orchestrator()

        orchestrator.run_iteration()

        assert len(orchestrator.pruner.prune_history) > 0, (
            "run_iteration 应调用 recursive_prune 剪枝候选方案，"
            f"实际 prune_history 为空（pruner 未被调用）。"
            f"prune_history: {orchestrator.pruner.prune_history}"
        )

    def test_optimizations_are_pruned_best_candidates(self):
        """优化结果应是剪枝后的最优候选（非全部候选）

        场景：生成多个候选（不同调整幅度），剪枝后只保留最优
        期望：optimizations 数量 <= 候选总数
        """
        orchestrator = _create_real_orchestrator()

        result = orchestrator.run_iteration()
        optimizations = result.get("optimizations", [])

        # 应有优化建议（性能低时触发调整）
        assert len(optimizations) > 0, "性能低于阈值时应有优化建议"

        # 每个优化应包含 new_value（剪枝后的最优值）
        for opt in optimizations:
            assert "new_value" in opt, f"优化建议应含 new_value，实际: {opt}"
            assert "pruned" in opt.get("metadata", {}) or opt.get("pruned") is not None or "prune_round" in opt, (
                f"优化建议应标记来自剪枝过程，实际: {opt}"
            )
