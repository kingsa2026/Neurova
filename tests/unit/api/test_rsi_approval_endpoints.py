"""RSI 审批出口 + 阶段自动评估回归测试（遗留事项 ①）

断点 A：SelfImprovementProposer 的 escalation 提案 PENDING 后无任何 API/CLI 消费
approve_and_apply/reject_proposal——发散升级提案永远滞留 PENDING，人工评审通道
不存在。
修复：governance 端点新增 RSI 提案审批三连（GET /rsi/proposals/pending、
POST /rsi/proposals/{id}/approve、POST /rsi/proposals/{id}/reject），委托
get_rsi_orchestrator 单例的 self_improvement_proposer；RSI 未初始化时返回空列表/
503。

断点 B：RSIDeploymentController.evaluate_phase_transition 零调用方——phase 永远
停在 0（观察期），can_auto_execute("low") 恒 False，RSI 永远只观察不应用。
修复：RSIOrchestrator.run_iteration 尾部用本次迭代指标自动调用
evaluate_phase_transition（有相位推进判据：ROI≥0、无发散、无回滚天数达标）。
"""

from unittest.mock import MagicMock

from neurova.evolution.rsi.deployment_controller import (
    RSIDeploymentController,
    create_deployment_controller,
)


class TestPhaseAutoTransition:
    def _controller(self):
        return create_deployment_controller(initial_phase=0)

    def test_transition_then_advance(self):
        """判据通过 → advance_phase 真正推进（判据/推进分离是原设计）"""
        c = self._controller()
        assert c.evaluate_phase_transition({"convergence_status": "converging", "roi": 0.1}) is True
        assert c.advance_phase() == 1
        assert c.get_current_phase() == 1

    def test_diverging_blocks_transition(self):
        c = self._controller()
        assert c.evaluate_phase_transition({"convergence_status": "diverging", "roi": 0.1}) is False
        assert c.get_current_phase() == 0

    def test_negative_roi_blocks_transition(self):
        c = self._controller()
        assert c.evaluate_phase_transition({"convergence_status": "converging", "roi": -0.5}) is False

    def test_run_iteration_calls_transition_and_advance(self):
        """run_iteration 尾部必须触发判据+推进（断点 B 接线）"""
        from neurova.evolution.rsi.orchestrator import RSIOrchestrator

        orch = RSIOrchestrator(
            sleep_system=MagicMock(),
            emotion_system=MagicMock(),
            experience_system=MagicMock(),
            tool_memory_system=MagicMock(),
        )
        orch.deployment_controller = MagicMock()
        orch.deployment_controller.can_auto_execute.return_value = False
        orch.deployment_controller.evaluate_phase_transition.return_value = True
        orch.deployment_controller.advance_phase.return_value = 1
        orch.collect_feedback_signals = MagicMock(return_value={})
        orch.convergence_analyzer = MagicMock()
        orch.convergence_analyzer.analyze_convergence.return_value = {
            "status": "converging", "metrics": {},
        }
        orch.generate_optimizations = MagicMock(return_value=[])

        result = orch.run_iteration()

        orch.deployment_controller.evaluate_phase_transition.assert_called_once()
        orch.deployment_controller.advance_phase.assert_called_once()
        assert result["phase_advanced"] is True


class TestRsiApprovalEndpoints:
    def _client_with_proposer(self, proposer):
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints.governance import router

        orch = MagicMock()
        orch.self_improvement_proposer = proposer

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/governance")
        with patch(
            "neurova.api.endpoints.governance._get_rsi_orchestrator",
            return_value=orch,
        ):
            yield TestClient(app)

    def _make_proposer_with_pending(self):
        import tempfile
        from pathlib import Path

        from neurova.evolution.rsi.self_improvement_proposer import SelfImprovementProposer

        # proposer 磁盘持久化（.agents/proposals）——隔离到 tmp 防跨测试泄漏
        tmp = tempfile.mkdtemp()
        proposer = SelfImprovementProposer(agents_dir=Path(tmp))
        proposal = proposer.propose_skill_manifest(
            skill_id="rsi_escalation_tool_memory_3",
            manifest_yaml="name: fix\n",
            description="发散升级",
        )
        proposer.submit_proposal(proposal)
        return proposer, proposal

    def test_list_pending(self):
        proposer, proposal = self._make_proposer_with_pending()
        for client in self._client_with_proposer(proposer):
            resp = client.get("/api/v1/governance/rsi/proposals/pending")
            assert resp.status_code == 200
            ids = [p["proposal_id"] for p in resp.json()["data"]["proposals"]]
            assert proposal.proposal_id in ids

    def test_approve_applies_proposal(self):
        proposer, proposal = self._make_proposer_with_pending()
        for client in self._client_with_proposer(proposer):
            resp = client.post(
                f"/api/v1/governance/rsi/proposals/{proposal.proposal_id}/approve",
                json={"approved_by": "admin"},
            )
            assert resp.status_code == 200
            assert resp.json()["data"]["applied"] is True

    def test_reject_proposal(self):
        proposer, proposal = self._make_proposer_with_pending()
        for client in self._client_with_proposer(proposer):
            resp = client.post(
                f"/api/v1/governance/rsi/proposals/{proposal.proposal_id}/reject",
                json={"reason": "风险过高"},
            )
            assert resp.status_code == 200
            assert resp.json()["data"]["rejected"] is True

    def test_approve_unknown_404(self):
        proposer = MagicMock()
        proposer.approve_and_apply.return_value = MagicMock(success=False, error="proposal not found: x")
        for client in self._client_with_proposer(proposer):
            resp = client.post(
                "/api/v1/governance/rsi/proposals/unknown/approve",
                json={"approved_by": "admin"},
            )
            assert resp.status_code == 404

    def test_rsi_not_initialized_returns_empty(self):
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints.governance import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/governance")
        with patch("neurova.api.endpoints.governance._get_rsi_orchestrator", return_value=None):
            client = TestClient(app)
            resp = client.get("/api/v1/governance/rsi/proposals/pending")
            assert resp.status_code == 200
            assert resp.json()["data"]["proposals"] == []
