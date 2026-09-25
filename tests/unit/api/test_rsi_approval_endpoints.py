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
        """判据通过 → advance_phase 真正推进（判据/推进分离是原设计）

        工单 003：返回值由 bool 改为 GateVerdict。断言等价改写并加严一层 ——
        原来只能表达"放行"，现在还要区分"放行"与"因缺证据而未知"。
        """
        c = self._controller()
        verdict = c.evaluate_phase_transition({"convergence_status": "converging", "roi": 0.1})
        assert bool(verdict) is True and verdict.state == "passed", verdict.reason
        assert c.advance_phase() == 1
        assert c.get_current_phase() == 1

    def test_diverging_blocks_transition(self):
        """发散是"有证据的否决"，不得与"取不到证据"混成同一个 False。"""
        c = self._controller()
        verdict = c.evaluate_phase_transition({"convergence_status": "diverging", "roi": 0.1})
        assert bool(verdict) is False
        assert verdict.state == "failed", f"发散应判 failed，实际 {verdict.state}"
        assert c.get_current_phase() == 0

    def test_negative_roi_blocks_transition(self):
        verdict = self._controller().evaluate_phase_transition(
            {"convergence_status": "converging", "roi": -0.5})
        assert bool(verdict) is False
        assert verdict.state == "failed", f"负 ROI 应判 failed，实际 {verdict.state}"

    def test_missing_evidence_is_unevidenced_not_passed(self):
        """工单 003 新增：读数缺失时不得放行，且要写清缺的是哪一项。

        取 phase 1 而非 phase 0：008 把"必需性"改成按阶段声明——phase 0 是观察期，
        `roi`/回滚读数在结构上还不可能存在（自动执行要求先晋升到 phase 2），
        在那里要求它们等于把晋升链锁成循环依赖，所以空读数判 passed
        （由 `test_phase_zero_requires_no_execution_evidence` 反向钉住这条裁决）。
        三份读数的全量缺项断言见 tests/unit/evolution/rsi/test_gate_verdict.py。
        """
        verdict = RSIDeploymentController(initial_phase=1).evaluate_phase_transition({})

        assert bool(verdict) is False
        assert verdict.state == "unevidenced"
        assert "days_without_rollback" in verdict.reason, verdict.reason

    def test_phase_zero_requires_no_execution_evidence(self):
        """观察期放行空读数：这是"无从产生证据"，不是"证据表明可以晋升"。"""
        verdict = self._controller().evaluate_phase_transition({})

        assert bool(verdict) is True
        assert "phase 0" in verdict.reason, verdict.reason

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
        from neurova.api.deps import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin1", "role": "admin"}
        with patch(
            "neurova.api.endpoints.governance._get_rsi_orchestrator",
            return_value=orch,
        ):
            yield TestClient(app)

    def _make_proposer_with_pending(self):
        import tempfile
        from pathlib import Path

        from neurova.evolution.rsi.deployment_controller import RSIDeploymentController
        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager
        from neurova.evolution.rsi.self_improvement_proposer import SelfImprovementProposer

        # proposer 磁盘持久化（.agents/proposals）——隔离到 tmp 防跨测试泄漏
        # 工单 005：控制器与回滚管理器必须由调用方注入，proposer 不再自建
        tmp = tempfile.mkdtemp()
        proposer = SelfImprovementProposer(
            agent_id="test-agent",
            proposals_dir=Path(tmp) / "proposals",
            deployment_controller=RSIDeploymentController(initial_phase=0),
            rollback_manager=RSIRollbackManager(),
        )
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
                # 工单 010：manifest 里没有可执行内容时，批准人要在请求里补交
                # tool_sequence —— 否则这条提案按 not_supported 拒绝（409）
                json={
                    "approved_by": "admin",
                    "tool_sequence": ["read_memory", "write_memory"],
                },
            )
            assert resp.status_code == 200, resp.text
            data = resp.json()["data"]
            assert data["applied"] is True
            assert data["applied_skill_id"] == "rsi_escalation_tool_memory_3"
            assert data["registry_hit"] is True, "端点报生效但注册表没命中"

    def test_approve_without_executable_content_is_rejected(self):
        """not_supported 必须走 409，不能被端点咽成"批准成功"（工单 010）。"""
        proposer, proposal = self._make_proposer_with_pending()
        for client in self._client_with_proposer(proposer):
            resp = client.post(
                f"/api/v1/governance/rsi/proposals/{proposal.proposal_id}/approve",
                json={"approved_by": "admin"},
            )
            assert resp.status_code == 409, resp.text
            assert "not_supported" in resp.json()["detail"], resp.text
            assert proposer.list_pending_proposals(), "被拒绝的提案不该从待审队列消失"

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

    def test_rsi_not_initialized_returns_503(self):
        """工单 011 改写本用例：`available:false` 的静默 200 把"没装配"读成"一切正常"。

        原断言是 200 + 空列表 + `available:false`；现在"没装配"必须是 503 + 原因，
        因为运维对这两种情形的处置完全相反（去装配 / 去看为什么没产出）。
        """
        from unittest.mock import patch

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints.governance import router

        app = FastAPI()
        app.include_router(router, prefix="/api/v1/governance")
        from neurova.api.deps import get_current_user
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "admin1", "role": "admin"}
        with patch("neurova.api.endpoints.governance._get_rsi_orchestrator", return_value=None):
            client = TestClient(app)
            resp = client.get("/api/v1/governance/rsi/proposals/pending")
            assert resp.status_code == 503, resp.text
            assert resp.json()["detail"], "503 必须带原因"
