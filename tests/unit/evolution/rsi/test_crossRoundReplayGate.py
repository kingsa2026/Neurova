# -*- coding: utf-8 -*-
"""C1 跨轮回放门（survey §10.2）：RSI 参数应用后回放早先用例集，例级退化即回滚。

判据机器**接线不并造**（教义第 6 条）：复用文本侧 `_caseRegressionReadout`
（P1-A 成果、probeCaseLevelGate 的同一判据形态），RSI 侧 allowance=0
（安全地板最严档：任何一条早先通过用例被撞坏即回滚）。
回放集＝决策档用例（密封档零引用纪律不变，D3 守卫管辖）。
"""

import pytest

from neurova.evolution.eval.runner import _caseRegressionReadout


def _cases(scores):
    return [{"id": cid, "score": score} for cid, score in scores.items()]


def _caseScores(before, after):
    """编排器侧的形状适配：决策档例级读数 → 文本侧判据机器的入参形状。"""
    before_by_id = {c["id"]: c["score"] for c in before}
    return {
        c["id"]: {"baseline": before_by_id[c["id"]], "candidate": c["score"],
                  "baseline_failed": False, "candidate_failed": False}
        for c in after if c["id"] in before_by_id
    }


class TestSharedJudgmentMachine:
    def test_mean_up_single_case_broken_is_reported(self):
        """均值涨单例坏的组合读数必须报出那条退化（probeCaseLevelGate 同形态）。"""
        before = _cases({"a": 0.4, "b": 0.4})
        after = _cases({"a": 0.1, "b": 0.9})  # 均值 0.4→0.5 涨，但 a 被撞坏
        regressions, unevidenced = _caseRegressionReadout(_caseScores(before, after))
        assert regressions == ["a"], (
            f"均值涨掩盖了单例退化：regressions={regressions}——例级门没咬合")
        assert unevidenced == []

    def test_no_regression_passes(self):
        before = _cases({"a": 0.5, "b": 0.5})
        after = _cases({"a": 0.6, "b": 0.5})
        regressions, _ = _caseRegressionReadout(_caseScores(before, after))
        assert regressions == []


class TestRollbackCaseAxis:
    def test_single_regression_rolls_back(self):
        """红灯判据本体：一条早先通过用例被撞坏 → 回滚（allowance=0）。"""
        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

        result = RSIRollbackManager().should_rollback({
            "gain": 0.05,
            "gain_ci": {"lower": 0.02, "upper": 0.08, "n": 6},
            "case_regressions": ["c1"],
        })
        assert result is True, "均值与 CI 都好看，但单例退化没被抓住"

    def test_clean_case_axis_does_not_rollback(self):
        from neurova.evolution.rsi.rollback_manager import RSIRollbackManager

        assert RSIRollbackManager().should_rollback({
            "gain": 0.05,
            "gain_ci": {"lower": 0.02, "upper": 0.08, "n": 6},
            "case_regressions": [],
        }) is False
        # 缺席（读数缺省）不参与判据
        assert RSIRollbackManager().should_rollback({"gain": 0.05}) is False


def test_orchestrator_case_metrics_via_shared_machine(tmp_path, monkeypatch):
    """接线证明：编排器的例级读数经**同一台**判据机器出退化清单（不并造）。"""
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    before = {"state": "measured", "cases": _cases({"a": 0.4, "b": 0.4})}
    after = {"state": "measured", "cases": _cases({"a": 0.1, "b": 0.9})}

    metrics = orch._caseRegressionMetrics(before, after)
    assert metrics["case_regressions"] == ["a"], (
        f"编排器没走共享判据机器或形状适配失守：{metrics}")
    # 与文本侧机器同读数（单源咬合）
    direct, _ = _caseRegressionReadout(_caseScores(before["cases"], after["cases"]))
    assert metrics["case_regressions"] == direct
