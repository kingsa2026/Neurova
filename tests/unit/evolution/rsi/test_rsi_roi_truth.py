"""ROI 判据真值化（工单 006）。

审计事实：`run_iteration` 读 `convergence["metrics"]["roi"]`
（orchestrator.py:282），但 `analyze_convergence()` 的 metrics 实测只返回
`mean_gain / std_dev / trend_slope` 三个键（convergence_analyzer.py:131-135），
`compute_roi()`（:138）生产零调用方。于是读点兜底成 0.0，
`roi < 0` 这条晋升守卫**在有负 ROI 时也照样放行** —— 幻影守卫。

本单把 roi 变成真值，并顺手记下一条更重的发现：
`run_iteration` 在 gain<0 时把 `gain` 与 `applied_count` 双双归零，
所以有害调整的负增益从不进入 `gain_history` —— 在棘轮正常工作的前提下
`total_gain >= 0` 恒成立，`roi < 0` **按构造不可达**。
这不是"补个供值"能解决的，故本单只锁事实、不假装修好：
一条用例断言该不可达性，把裁决权交给拥有收敛语义的工单 008。
008 的裁决见 `test_harmful_adjustment_never_reaches_negative_roi_under_current_feeding`：
有害尝试改记为"有证据的零产出"，负增益语义不引入。
"""

import pytest

from neurova.evolution.rsi.convergence_analyzer import ConvergenceAnalyzer
from neurova.evolution.rsi.gate_verdict import GateVerdict


# ── 1. compute_roi 从死方法变真供值 ───────────────────────────────


def test_convergence_metrics_expose_roi_from_recorded_history():
    """ROI = 总增益 / 总成本，由 `compute_roi()` 供值。

    期望值手算：增益 [0.2, 0.3]、成本 [1.0, 1.0] → 0.5/2 = 0.25。
    """
    analyzer = ConvergenceAnalyzer(window_size=1)
    analyzer.record_iteration(gain=0.2, cost=1.0)
    analyzer.record_iteration(gain=0.3, cost=1.0)

    metrics = analyzer.analyze_convergence()["metrics"]

    assert "roi" in metrics, "analyze_convergence 未产出 roi，晋升守卫仍在读一个不存在的键"
    assert metrics["roi"] == pytest.approx(0.25)


def test_roi_is_absent_when_no_iteration_cost_was_spent():
    """空历史 → 不产出 roi 键。

    `compute_roi()` 在无成本时返回 0.0，那是"没花过钱"不是"回报为 0"；
    产出 0 会让下游把无证据当成一次合法的零回报。缺席才会落 `unevidenced`。
    """
    metrics = ConvergenceAnalyzer().analyze_convergence()["metrics"]

    assert "roi" not in metrics or metrics["roi"] is None, (
        f"无迭代成本时不应给出 roi 读数，实际 {metrics.get('roi')!r}")


def test_insufficient_data_branch_also_reports_roi_once_costed():
    """样本未达窗口也要给 roi —— 它是成本核算，与收敛判定的样本量无关。

    否则阶段判据在 RSI 刚起步的 20 轮里永远拿不到 roi，
    等于用样本门槛间接掐死一条独立的守卫。
    """
    analyzer = ConvergenceAnalyzer(window_size=20)
    analyzer.record_iteration(gain=0.4, cost=1.0)

    result = analyzer.analyze_convergence()

    assert result["status"] == "insufficient_data"
    assert result["metrics"]["roi"] == pytest.approx(0.4)


# ── 2. 编排器不再伪造读数 ────────────────────────────────────────


def test_orchestrator_omits_roi_key_when_convergence_has_none(rsi_probe_factory, monkeypatch):
    """默认观察期下从不应用参数 → 无成本记录 → roi 键必须缺席，而不是伪装 0.0。"""
    probe = rsi_probe_factory(rsi_phase=0)
    captured = {}

    def _spy(metrics):
        captured.update(metrics)
        return GateVerdict.failed("测试用：阻断真实推进")

    monkeypatch.setattr(probe.orchestrator.deployment_controller,
                        "evaluate_phase_transition", _spy)

    probe.orchestrator.run_iteration()

    assert "roi" not in captured, (
        "默认观察期下无任何成本记录，编排器不得把缺失的 roi 伪装成 0.0 喂给判据"
        f" —— 那正是幻影守卫的来源。实际传入 {captured.get('roi')!r}")


def test_negative_roi_rejects_promotion_through_the_real_read(rsi_probe_factory):
    """判据必须能否决负 ROI —— 且读数走真实历史，不 patch 收敛分析器。

    直接把一段净损害的历史喂进 `gain_history/cost_history`：
    roi = -0.5/1.0 = -0.5 由 `compute_roi()` 算出，经编排器原样送到控制器并被否决。
    （下一轮里 roi 守卫能否被 RSI 自己走负，见
    `test_harmful_adjustment_never_reaches_negative_roi_under_current_feeding`。）
    """
    probe = rsi_probe_factory(rsi_phase=1)
    probe.orchestrator.convergence_analyzer.record_iteration(gain=-0.5, cost=1.0)

    result = probe.orchestrator.run_iteration()

    assert result["phase_verdict"]["state"] == "failed", (
        f"负 ROI 必须否决晋升，实际 {result['phase_verdict']}")
    assert "roi" in result["phase_verdict"]["reason"]
    assert result["phase_advanced"] is False


# ── 3. 幻影守卫的可达性：本单只锁事实 ────────────────────────────


def test_harmful_adjustment_never_reaches_negative_roi_under_current_feeding(
        rsi_probe_factory, measured_eval_harness, monkeypatch):
    """结构性发现：有害调整被棘轮消化后只能表达为"有证据的零产出"，不是负增益。

    `orchestrator.py` 的 gain<0 分支先回滚留痕、再把 `gain` 与 `applied_count` 归零，
    因此负增益永不进 `gain_history`，`compute_roi()` 分子非负，
    `roi < 0` 这条晋升守卫**按构造不可达**。

    工单 008 对本条的裁决：不引入负增益语义（有害性已由回滚 + 回滚历史表达，
    那是日历时间上的硬否决，比 roi 更直接），改为记一轮**有证据的零产出**
    —— 成本真实花过、测量也有效，于是 roi 可以长期为 0，
    而"只烧成本不产出"由 `measurement_blind`/零产出门槛在阶段判据侧否决。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "_eval_harness",
                        measured_eval_harness([1.0, 0.2, 1.0, 0.2, 1.0, 0.2]))

    for _ in range(3):
        probe.orchestrator.run_iteration()

    assert probe.orchestrator.rollback_manager.get_rollback_history(), (
        "前置：这 3 轮确实每次都判定有害并回滚了（工单 004 的留痕）")
    assert probe.orchestrator.convergence_analyzer.gain_history == [0.0, 0.0, 0.0], (
        "有害尝试应记为有证据的零产出，不得把负增益写进历史（回滚已消化危害），"
        f"也不得整轮不喂（那会让 roi 永远无读数）：实际 "
        f"{probe.orchestrator.convergence_analyzer.gain_history}")
    assert probe.orchestrator.convergence_analyzer.compute_roi() == 0.0


def test_dashboard_roi_metric_is_recorded_so_alerts_can_fire(
        rsi_probe_factory, measured_eval_harness, monkeypatch):
    """`rsi_convergence_roi` 此前从没人写入 → `check_alerts()` 的负 ROI 告警永不触发。

    与工单 012 的"规范指标须有写入方"同源，这里只补 roi 一条。
    """
    from neurova.evolution.rsi.metrics import RSIMetrics

    probe = rsi_probe_factory(rsi_phase=2)
    # gain = 0.8 - 0.5 > 0 → 会被喂进收敛历史
    monkeypatch.setattr(probe.orchestrator, "_eval_harness", measured_eval_harness([0.5, 0.8]))

    probe.orchestrator.run_iteration()

    recorded = probe.orchestrator.metrics.get_metric(RSIMetrics.RSI_CONVERGENCE_ROI)
    assert recorded is not None, (
        "roi 未写入规范指标 → 告警面与仪表盘读到的永远是初始 0")
    assert recorded == pytest.approx(0.3, abs=0.05)
