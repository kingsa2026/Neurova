"""§6-2 阶段① 提案生命周期契约 — 红灯先行的契约测试(2026-10-07)。

两套提案仓(文本进化 proposals.json / RSI proposals/<id>.json)此前各自内联
状态守卫与审批语义——同一函数两份实现。本文件钉住收口后的契约:

- 转移合法性单源(assert_can_decide / assert_can_rollback);
- 死状态退役(RSI 的 APPROVED 从未被任何转移产出);
- 批准必须可归因(require_approver)——文本臂此前缺这层(治理缝隙);
- 文本臂历史行 "approved" 读路径归一为规范 "applied";
- RSI 侧 ProposalStatus 与契约同类(身份断言,防第二份枚举回归)。
"""

import json

import pytest

from neurova.evolution.proposal_lifecycle import (
    LEGACY_TEXT_STATUS_ALIASES,
    ProposalStatus,
    ProposalTransitionError,
    assert_can_decide,
    assert_can_rollback,
    normalize_legacy_status,
    require_approver,
)


class TestTransitionRules:
    def test_only_pending_decidable(self):
        assert_can_decide("pending")
        for state in ("applied", "rejected", "rolled_back"):
            with pytest.raises(ProposalTransitionError):
                assert_can_decide(state)
        with pytest.raises(ProposalTransitionError):
            assert_can_decide("whatever")

    def test_only_applied_rollbackable(self):
        assert_can_rollback("applied")
        for state in ("pending", "rejected", "rolled_back"):
            with pytest.raises(ProposalTransitionError):
                assert_can_rollback(state)

    def test_no_transient_approved_state(self):
        """死状态退役:不存在"已批准未应用"瞬态(两臂批准均为原子决定)。"""
        assert not hasattr(ProposalStatus, "APPROVED")
        assert "approved" not in [s.value for s in ProposalStatus]


class TestApproverGate:
    def test_valid_approver_stripped(self):
        assert require_approver(" admin ", action="批准提案") == "admin"

    @pytest.mark.parametrize("bad", ["", "   ", None])
    def test_empty_approver_rejected(self, bad):
        with pytest.raises(ValueError, match="审批人"):
            require_approver(bad, action="批准提案")


class TestLegacyAlias:
    def test_approved_normalizes_to_applied(self):
        assert normalize_legacy_status("approved") == "applied"
        assert normalize_legacy_status("pending") == "pending"
        assert normalize_legacy_status("") == ""

    def test_alias_table_declares_only_approved(self):
        assert set(LEGACY_TEXT_STATUS_ALIASES) == {"approved"}


class TestRsiWiring:
    def test_rsi_status_enum_is_the_contract(self):
        """身份断言:RSI 侧的 ProposalStatus 必须就是契约类,防第二份枚举回归。"""
        from neurova.evolution.rsi.self_improvement_proposer import (
            ProposalStatus as RsiStatus,
        )

        assert RsiStatus is ProposalStatus


class TestTextArmWiring:
    def _service(self, tmp_path):
        from neurova.evolution.eval.service import SkillEvolutionService

        return SkillEvolutionService("plc-agent", base_dir=tmp_path / "evo")

    def _seed(self, svc, proposal_id, status="pending"):
        svc._dir.mkdir(parents=True, exist_ok=True)
        svc._proposals_file.write_text(json.dumps([
            {"proposal_id": proposal_id, "skill_id": "sk1", "status": status,
             "baseline_text": "b", "improved_text": "i"},
        ], ensure_ascii=False), encoding="utf-8")

    def test_approve_requires_approver(self, tmp_path):
        """治理缝隙补齐:批准不记审批人 = 拒绝执行(此前匿名批准畅通)。"""
        svc = self._service(tmp_path)
        self._seed(svc, "p1")
        with pytest.raises(ValueError, match="审批人"):
            svc.decide("p1", approve=True, approver="   ")

    def test_reject_records_decided_by(self, tmp_path):
        svc = self._service(tmp_path)
        self._seed(svc, "p1")
        assert svc.decide("p1", approve=False, approver="admin") is True
        row = svc.list_proposals()[0]
        assert row["status"] == "rejected"
        assert row["decided_by"] == "admin"

    def test_approve_writes_canonical_status_and_attribution(self, tmp_path, monkeypatch):
        svc = self._service(tmp_path)
        self._seed(svc, "p1")
        monkeypatch.setattr(svc, "_apply_to_skill", lambda row, registry: True)
        assert svc.decide("p1", approve=True, approver="admin") is True
        row = svc.list_proposals()[0]
        # 规范值是 applied(原子决定),不再是历史字面量 "approved"
        assert row["status"] == "applied"
        assert row["decided_by"] == "admin"

    def test_legacy_approved_row_normalized_on_list(self, tmp_path):
        """历史行读路径归一:老数据 "approved" 以 "applied" 呈现,且不可再决定。"""
        svc = self._service(tmp_path)
        self._seed(svc, "old", status="approved")
        row = svc.list_proposals()[0]
        assert row["status"] == "applied"
        assert svc.decide("old", approve=False, approver="admin") is False
