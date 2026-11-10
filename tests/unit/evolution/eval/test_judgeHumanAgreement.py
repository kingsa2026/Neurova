# -*- coding: utf-8 -*-
"""F2 judge-人工相关性（survey §10.2）——审批动作即标签，塌陷告警。

红灯判据：注入"相关性塌"序列（judge 高增益但人连续拒）→ 告警；样本不足报
insufficient_data 不硬算。
"""

import pytest

from neurova.evolution.eval.judge_human_agreement import judgeHumanAgreement


def _proposal(pid, judge_gain, status):
    return {"proposal_id": pid, "status": status,
            "holdout_before": 0.5, "holdout_after": 0.5 + judge_gain}


def test_collapsing_sequence_alerts():
    """红灯判据本体：judge 高增益但人连续拒（相关性塌）→ 告警。"""
    proposals = [_proposal(f"p{i}", 0.3, "rejected") for i in range(5)]
    readout = judgeHumanAgreement(proposals)
    assert readout["state"] == "measured"
    assert readout["score"] == pytest.approx(0.0)
    assert readout["alert"] is True, f"塌陷没告警：{readout}"


def test_aligned_sequence_no_alert():
    """judge 正增益且人批 = 一致；高一致率不告警。"""
    proposals = [_proposal(f"p{i}", 0.3, "applied") for i in range(5)]
    readout = judgeHumanAgreement(proposals)
    assert readout["score"] == pytest.approx(1.0)
    assert readout["alert"] is False


def test_insufficient_samples_unevidenced():
    proposals = [_proposal("p0", 0.3, "applied")]
    readout = judgeHumanAgreement(proposals)
    assert readout["state"] == "insufficient_data"
    assert readout["score"] is None


def test_pending_not_counted():
    """pending（未决策）不计入样本（没决策不是标签）。"""
    decided = [_proposal(f"p{i}", 0.3, "applied") for i in range(4)]
    pending = [_proposal(f"q{i}", 0.3, "pending") for i in range(6)]
    readout = judgeHumanAgreement(decided + pending)
    assert readout["decisions"] == 4


def test_zero_gain_rejected_is_agreement():
    """judge 零增益时人拒 = 把关节拍对上（一致）。"""
    proposals = [_proposal(f"p{i}", 0.0, "rejected") for i in range(5)]
    readout = judgeHumanAgreement(proposals)
    assert readout["score"] == pytest.approx(1.0)
