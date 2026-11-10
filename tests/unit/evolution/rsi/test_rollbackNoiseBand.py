# -*- coding: utf-8 -*-
"""B3 不确定度校准（survey §10.2）。

两半：
- 文本侧 `noise_repeats` 默认 0→3（校准算式早已在，只差默认开）；
- RSI 侧 gain 报**配对 CI**（决策档例级差分的抽样不确定度），回滚判据读
  置信区间而非点值——单点噪声不得触发拒绝，确证危害才回滚；CI 缺席回退
  点判据（保守兜底，缺席形态在 eval_outcome 可读）。
"""

import pytest

from neurova.evolution.rsi.rollback_manager import RSIRollbackManager


def _mgr():
    return RSIRollbackManager()


class TestRollbackReadsConfidence:
    def test_point_negative_within_band_does_not_rollback(self):
        """合成两向抖动：点值负增益落在置信带内 → 不回滚（单点噪声不触发拒绝）。"""
        result = _mgr().should_rollback({
            "gain": -0.005,
            "gain_ci": {"lower": -0.02, "upper": 0.01, "n": 6},
        })
        assert result is False, (
            "置信带横跨零的点值负增益触发了回滚——单点噪声当了判据")

    def test_confident_harm_rolls_back(self):
        """确证危害：CI 上界 < 0 → 回滚。"""
        result = _mgr().should_rollback({
            "gain": -0.05,
            "gain_ci": {"lower": -0.08, "upper": -0.02, "n": 6},
        })
        assert result is True

    def test_missing_ci_falls_back_to_point_rule(self):
        """CI 缺席回退点判据（保守兜底）：点值负增益照旧回滚。"""
        assert _mgr().should_rollback({"gain": -0.005}) is True
        assert _mgr().should_rollback({"gain": -0.005, "gain_ci": None}) is True

    def test_confident_improvement_and_positive_gain_never_rollback(self):
        """确证改进（下界 > 0）与正增益：两形态都不回滚。"""
        assert _mgr().should_rollback({
            "gain": 0.05, "gain_ci": {"lower": 0.02, "upper": 0.08, "n": 6},
        }) is False
        assert _mgr().should_rollback({
            "gain": 0.05, "gain_ci": {"lower": -0.01, "upper": 0.11, "n": 6},
        }) is False


def test_default_noise_repeats_is_calibrating():
    """文本侧默认开：noise_repeats 出厂 0→3（校准算式早已在）。"""
    from neurova.evolution.eval.config import EvolutionConfig

    assert EvolutionConfig().noise_repeats == 3, (
        "噪声校准默认仍关——接受判据在读点值，单点噪声可触发接受/拒绝")


def test_orchestrator_surfaces_gain_ci(tmp_path, monkeypatch):
    """编排器实测出 CI：应用轮次后 eval_outcome 携带配对例级 CI。"""
    from unittest.mock import MagicMock

    from neurova.evolution.rsi.orchestrator import RSIOrchestrator

    monkeypatch.delenv("NEUROVA_RSI_IMPROVER_LEDGER", raising=False)
    orch = RSIOrchestrator(
        sleep_system=MagicMock(), emotion_system=MagicMock(),
        experience_system=MagicMock(), tool_memory_system=MagicMock(),
    )
    # 直接喂两份例级读数（决策档形态），CI 由编排器现算
    before = {"state": "measured", "cases": [
        {"id": f"c{i}", "score": 0.5} for i in range(6)]}
    after = {"state": "measured", "cases": [
        {"id": f"c{i}", "score": 0.5 + (0.02 if i % 2 else -0.01)} for i in range(6)]}
    ci = orch._pairedGainCI(before, after)
    assert ci is not None
    assert ci["n"] == 6
    assert ci["lower"] < ci["mean"] < ci["upper"]
    # 全对称无差异 → sd=0 → 带宽为 0（确定性 harness 的诚实退化）
    same = {"state": "measured", "cases": before["cases"]}
    ci0 = orch._pairedGainCI(before, same)
    assert ci0 is not None and ci0["upper"] == pytest.approx(ci0["mean"])
