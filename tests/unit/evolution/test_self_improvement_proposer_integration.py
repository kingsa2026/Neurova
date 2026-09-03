"""
TDD RED：暴露 SelfImprovementProposer 966 行代码完全孤立问题（P0-A3）

验证 SelfImprovementProposer 与 RSIOrchestrator 之间的接线：
1. RSIOrchestrator 应持有 SelfImprovementProposer 实例（用于升级到人工评审）
2. 当 RSI 检测到发散/振荡（convergence status == "diverging" 或 "oscillating"）时，
   应通过 SelfImprovementProposer 创建提案（而非继续无效的自动参数调整）
3. 提案应进入 PENDING 状态等待人工评审（不直接应用）

根因（P0-A3）：
    neurova/evolution/rsi/self_improvement_proposer.py（966 行）
        完整实现三种渐进路径（skill_manifest/action_definition/pr_patch）+
        三层安全防御 + 状态机守卫 + 线程安全，但：
    - 全文件唯一引用自身，无任何生产代码调用
    - get_self_improvement_proposer() 工厂存在但无调用方
    - RSIOrchestrator 检测到发散后只能"立即停止"，无升级路径

设计意图（来源：self_improvement_proposer.py 文件头注释）：
    "将 Agent 的'改进代码/UI'意图转化为可审查、可回滚的提案"
    "必须经过人类评审 gate（approve_and_apply / reject_proposal）"
    RSI 的自动参数调整是低风险路径；
    SelfImprovementProposer 是中高风险路径（需要人工评审）。
    二者构成"渐进式自我改进"的完整链路。
"""

import pytest
from unittest.mock import Mock, MagicMock


def _create_orchestrator_with_diverging_convergence():
    """创建一个收敛状态为 diverging 的 RSIOrchestrator

    通过预填 gain_history 让 analyze_convergence 返回 diverging
    """
    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    sleep_system = Mock()
    sleep_system.get_feedback = Mock(return_value={"performance_score": 0.3})
    sleep_system.base_decay_rate = 0.1

    emotion_system = Mock()
    emotion_system.get_feedback = Mock(return_value={"stability": 0.4})
    emotion_system.emotional_protection_threshold = 0.5

    experience_system = Mock()
    experience_system.get_feedback = Mock(return_value={"success_rate": 0.3})
    experience_system.crystallize_min_observations = 3

    tool_memory_system = Mock()
    tool_memory_system.get_feedback = Mock(return_value={"avg_success_rate": 0.3})
    tool_memory_system.success_bonus = 0.1

    orchestrator = RSIOrchestrator(
        sleep_system=sleep_system,
        emotion_system=emotion_system,
        experience_system=experience_system,
        tool_memory_system=tool_memory_system,
    )

    # 预填 gain_history 让 analyze_convergence 返回 diverging
    # divergence_threshold = -0.05，需要 mean_gain < -0.05
    orchestrator.convergence_analyzer.gain_history = [-0.2] * orchestrator.convergence_analyzer.window_size
    orchestrator.convergence_analyzer.cost_history = [1.0] * orchestrator.convergence_analyzer.window_size

    return orchestrator


class TestSelfImprovementProposerIntegration:
    """测试 SelfImprovementProposer 与 RSIOrchestrator 的接线"""

    def test_orchestrator_holds_self_improvement_proposer(self):
        """RSIOrchestrator 应持有 SelfImprovementProposer 实例

        场景：构造 RSIOrchestrator
        期望：orchestrator.self_improvement_proposer 是 SelfImprovementProposer 实例
        当前：RSIOrchestrator 完全不引用 SelfImprovementProposer
        """
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator
        from neurova.evolution.rsi.self_improvement_proposer import SelfImprovementProposer

        sleep_system = Mock()
        sleep_system.get_feedback = Mock(return_value={"performance_score": 0.5})
        sleep_system.base_decay_rate = 0.1

        emotion_system = Mock()
        emotion_system.get_feedback = Mock(return_value={"stability": 0.5})
        emotion_system.emotional_protection_threshold = 0.5

        experience_system = Mock()
        experience_system.get_feedback = Mock(return_value={"success_rate": 0.5})
        experience_system.crystallize_min_observations = 3

        tool_memory_system = Mock()
        tool_memory_system.get_feedback = Mock(return_value={"avg_success_rate": 0.5})
        tool_memory_system.success_bonus = 0.1

        orchestrator = RSIOrchestrator(
            sleep_system=sleep_system,
            emotion_system=emotion_system,
            experience_system=experience_system,
            tool_memory_system=tool_memory_system,
        )

        assert hasattr(orchestrator, "self_improvement_proposer"), (
            "RSIOrchestrator 应持有 self_improvement_proposer 属性，"
            "用于在自动参数调整失效时升级到人工评审提案"
        )
        assert isinstance(orchestrator.self_improvement_proposer, SelfImprovementProposer), (
            "self_improvement_proposer 应是 SelfImprovementProposer 实例"
        )

    def test_run_iteration_escalates_to_proposer_on_divergence(self):
        """当收敛状态为 diverging 时，run_iteration 应通过 SelfImprovementProposer 创建提案

        场景：预填 gain_history 使 convergence status == "diverging"
        期望：run_iteration 调用后，proposer 有至少 1 个 PENDING 提案
        当前：RSI 检测到发散后只能"立即停止"，无升级路径
        """
        orchestrator = _create_orchestrator_with_diverging_convergence()

        # 验证预填的收敛状态确实是 diverging
        convergence = orchestrator.convergence_analyzer.analyze_convergence()
        assert convergence.get("status") == "diverging", (
            f"测试前置条件失败：预填的收敛状态应为 diverging，实际: {convergence.get('status')}"
        )

        orchestrator.run_iteration()

        # 检查 proposer 是否有 PENDING 提案
        pending = orchestrator.self_improvement_proposer.list_pending_proposals()
        assert len(pending) > 0, (
            "收敛状态为 diverging 时，run_iteration 应通过 SelfImprovementProposer "
            "创建至少 1 个 PENDING 提案（升级到人工评审），实际 pending 列表为空"
        )

    def test_escalation_does_not_auto_apply(self):
        """升级到 proposer 的提案应保持 PENDING 状态，不自动应用

        场景：RSI 检测到发散后创建提案
        期望：提案状态为 PENDING（等待人工 approve_and_apply）
        当前：无 proposer 集成，谈不上状态
        """
        from neurova.evolution.rsi.self_improvement_proposer import ProposalStatus

        orchestrator = _create_orchestrator_with_diverging_convergence()

        orchestrator.run_iteration()

        pending = orchestrator.self_improvement_proposer.list_pending_proposals()
        assert len(pending) > 0, "前置条件：应有 PENDING 提案"

        for proposal in pending:
            assert proposal.status == ProposalStatus.PENDING, (
                f"提案 {proposal.proposal_id} 状态应为 PENDING（等待人工评审），"
                f"实际: {proposal.status}"
            )
