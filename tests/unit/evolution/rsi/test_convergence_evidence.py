"""三态收敛与晋升判据的适用性（工单 008 第一步）。

本单要消灭的两个"把未知读成已知"：

1. 喂数门 `if applied_count > 0 or gain != 0.0`（orchestrator.py:237-239）
   在评测集度量失明时仍把 gain=0.0 喂进收敛历史 → 20 轮后 `mean_gain=0`
   被判 `converged` → `should_continue()` False → 本进程内 RSI 永久自停。
2. 阶段判据对所有阶段一律要求"三份读数齐全"，于是
   0→1 也要等 converged-with-evidence，而 evidence 只能靠"已经晋升到 2 并应用参数"产生
   —— 循环依赖，任何阶段都出不去。

三态契约（工单 003）里 `unevidenced` 与 `passed` 必须可区分；本单把"该读数此阶段是否必需"
也变成显式声明，而不是靠 `.get(key, 0)` 的默认值蒙混。
"""

import pytest

from neurova.evolution.rsi.convergence_analyzer import ConvergenceAnalyzer
from neurova.evolution.rsi.deployment_controller import RSIDeploymentController


# ── 1. 度量失明不得被喂成"收敛" ─────────────────────────────────


def test_blind_iterations_never_enter_gain_history(rsi_probe_factory, blind_eval_harness,
                                                   monkeypatch):
    """评测集报 measurement_blind 的轮次，不得往收敛历史里喂 0。

    现状：`applied_count > 0` 就喂，而度量失明时 gain 恒为 0.0
    —— 于是"量不出来"与"确实没有改善空间"在同一个数字上重合。

    前置断言"参数真的被应用了"是这条用例的命门：若用"无可优化参数"的系统桩来
    制造失明，`attempted` 本身就是 False，喂数门从未被触发，用例会在与门无关的
    路径上蒙绿（工单 007 执行期已证伪"真实评测集 + 有参数 ⇒ 失明"的可构造性，
    所以失明由评测集自报口径注入 —— 那正是 `run_iteration` 读取的契约边界）。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "_eval_harness", blind_eval_harness())

    probe.run(3)

    assert probe.applied_total > 0, "前置失效：本轮没有参数被应用，喂数门根本未被触发"
    assert probe.orchestrator.convergence_analyzer.gain_history == [], (
        f"度量失明的轮次污染了收敛历史：{probe.orchestrator.convergence_analyzer.gain_history}")


def test_blind_attempt_is_recorded_as_blind_not_as_an_empty_window(rsi_probe_factory,
                                                                   blind_eval_harness,
                                                                   monkeypatch):
    """失明轮次要留下"量过了但量不出来"的痕迹，不能什么都不记。

    什么都不记时窗口是空的 → 分析器报 `insufficient_data`（"再等等"），
    而真实结论是"再多样本也量不出来，该去修测量"。两种措辞指向相反的运维动作。
    成本更要记：那次评测真的跑了，roi 的分母里就该有它（工单 006 移交的零产出语义）。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "_eval_harness", blind_eval_harness())

    probe.run(3)

    analyzer = probe.orchestrator.convergence_analyzer
    assert analyzer.analyze_convergence()["status"] == "measurement_blind", (
        f"三次失明尝试后仍报 {analyzer.analyze_convergence()['status']}：等于假装什么都没发生")
    assert sum(analyzer.cost_history) == 3.0, "评测成本必须进分母，否则 roi 虚高"


def test_unevidenced_record_fills_cost_but_not_gain_history():
    """`evidenced=False` 的记录只进成本与证据史，不进增益史（增益史必须纯净）。

    增益史是收敛统计的输入，掺进"量不出来的 0"就会把零证据窗口算成已收敛。
    """
    analyzer = ConvergenceAnalyzer(window_size=20)

    analyzer.record_iteration(gain=0.0, cost=1.0, evidenced=False)

    assert analyzer.gain_history == []
    assert analyzer.cost_history == [1.0]
    assert analyzer.evidence_history == [False]
    # 成本已发生 → roi 是"花了钱零产出"，不是"还没花过钱"
    assert analyzer.analyze_convergence()["metrics"]["roi"] == 0.0


def test_measurement_blind_takes_precedence_over_insufficient_data():
    """样本没攒够 + 一次都没量出来 → 报 measurement_blind，不是 insufficient_data。

    前者与样本量无关：只要历史上全是失明的尝试，多等也不会自动变出证据。
    """
    analyzer = ConvergenceAnalyzer(window_size=20)
    analyzer.record_iteration(gain=0.0, cost=1.0, evidenced=False)

    assert analyzer.analyze_convergence()["status"] == "measurement_blind"


def test_measurement_blind_is_its_own_convergence_state():
    """一轮有效测量都没有时，状态必须是 measurement_blind，不是 converged 也不是 insufficient_data。

    `insufficient_data` 说的是"样本还不够"，`measurement_blind` 说的是
    "再多样本也量不出来" —— 两者对运维的含义完全不同：前者该等，后者该修测量。
    """
    analyzer = ConvergenceAnalyzer(window_size=20)
    for _ in range(25):
        analyzer.record_iteration(gain=0.0, cost=1.0, evidenced=False)

    result = analyzer.analyze_convergence()

    assert result["status"] == "measurement_blind", (
        f"零证据窗口被判成了 {result['status']}：{result['recommendation']}")
    assert result["confidence"] == 0.0
    assert "量不出来" in result["recommendation"] or "blind" in result["recommendation"]


def test_converged_requires_evidence_within_the_window():
    """窗口内只要有有效测量，converged 才是可信结论；全无效则不得判 converged。"""
    blind = ConvergenceAnalyzer(window_size=3)
    for _ in range(3):
        blind.record_iteration(gain=0.0, cost=1.0, evidenced=False)
    assert blind.analyze_convergence()["status"] != "converged"

    measured = ConvergenceAnalyzer(window_size=3)
    for _ in range(3):
        measured.record_iteration(gain=0.0, cost=1.0, evidenced=True)
    assert measured.analyze_convergence()["status"] == "converged"


def test_unevidenced_window_is_not_read_as_converged_by_should_continue(
        rsi_probe_factory, blind_eval_harness, monkeypatch):
    """度量失明时 `should_continue()` 不得因为"已收敛"而永久关掉进化。"""
    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "_eval_harness", blind_eval_harness())

    probe.run(25)

    status = probe.orchestrator.convergence_analyzer.analyze_convergence()["status"]
    assert status != "converged", (
        f"25 轮零有效测量后被宣告已收敛（{status}）—— 这正是"
        "tests/unit/evolution/test_rsi_ratchet_effectiveness.py 文档写的根因 2 回潮")
    assert probe.orchestrator.should_continue() is True
    # 但不该每轮空烧：失明时转入降频巡检（工单 008 交付项 3）
    cadence = probe.orchestrator.iteration_cadence()
    assert cadence.mode == "backoff"
    assert cadence.basis == "measurement_blind", (
        f"降频必须说得出依据哪个判据：{cadence}")
    assert "有效测量 0" in cadence.evidence, (
        f"降频必须说得出依据什么证据：{cadence.evidence}")


# ── 2. 各阶段必需的读数必须显式声明 ─────────────────────────────


def test_phase_zero_to_one_needs_no_execution_evidence():
    """观察期 → 手动期不得要求任何"执行后才可能产生"的读数。

    否则：auto-execute 要求 phase>=2，而 phase 提升要求执行留下的读数 —— 循环依赖，
    任何阶段都出不去（工单 006 交给本单的裁决）。
    阶段 1 只是"生成建议给人看"，本身无自动执行风险。
    """
    controller = RSIDeploymentController(initial_phase=0)

    verdict = controller.evaluate_phase_transition({})

    assert bool(verdict) is True, (
        f"0→1 仍在要求不存在的执行证据：{verdict.state} / {verdict.reason}")


def test_phase_one_to_two_still_requires_rollback_days():
    """半自动门槛不能被一起放宽掉 —— 只免除"此阶段无从产生"的读数要求。"""
    controller = RSIDeploymentController(initial_phase=1)

    assert bool(controller.evaluate_phase_transition({
        "days_without_rollback": 8, "roi": None, "convergence_status": "insufficient_data",
    })) is True
    assert bool(controller.evaluate_phase_transition({
        "days_without_rollback": 1, "convergence_status": "converging",
    })) is False, "days 未达标必须仍然否决"


def test_phase_three_to_four_requires_roi_evidence():
    """到"中风险自动执行"这一档，成本收益读数变成必需项（此时它已可能存在于盘上）。"""
    controller = RSIDeploymentController(initial_phase=3)

    without_roi = controller.evaluate_phase_transition(
        {"days_without_rollback": 40, "convergence_status": "converging"})
    with_roi = controller.evaluate_phase_transition(
        {"days_without_rollback": 40, "convergence_status": "converging", "roi": 0.2})

    assert without_roi.state == "unevidenced" and "roi" in without_roi.reason
    assert bool(with_roi) is True


def test_diverging_vetoes_every_transition():
    """硬否决类读数一旦存在就对所有阶段生效 —— 免除"必需性"不等于免除"否决"。"""
    for phase in (0, 1, 2, 3):
        verdict = RSIDeploymentController(initial_phase=phase).evaluate_phase_transition(
            {"convergence_status": "diverging", "roi": 1.0, "days_without_rollback": 99})
        assert verdict.state == "failed", f"phase {phase} 未拦下发散：{verdict.state}"


# ── 3. 停滞原因要进响应面（工单 008 交付项 5）────────────────────


def test_summary_reports_measurement_state_and_evidenced_cases(
        rsi_probe_factory, blind_eval_harness, monkeypatch):
    """摘要必须区分"没有改善空间"与"量不出来"。

    只有 gain=0 的响应面把这两件事压成同一个数字，而它们的处置相反：
    前者降频巡检即可，后者要去修测量。工单 012 的观测面收口以本字段为凭。
    """
    from neurova.evolution.rsi.result_summary import summarize_rsi_result

    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "_eval_harness", blind_eval_harness())

    summary = summarize_rsi_result(probe.orchestrator.run_iteration())

    assert summary["measure_state"] == "measurement_blind"
    assert summary["evidenced_cases"] == 0


def test_summary_reports_measured_round_with_evidence_count(
        rsi_probe_factory, measured_eval_harness, monkeypatch):
    """有证据的轮次如实报 measured + 用例数，响应面才数得清分母。"""
    from neurova.evolution.rsi.result_summary import summarize_rsi_result

    probe = rsi_probe_factory(rsi_phase=2)
    monkeypatch.setattr(probe.orchestrator, "_eval_harness",
                        measured_eval_harness([0.5, 0.8]))

    summary = summarize_rsi_result(probe.orchestrator.run_iteration())

    assert summary["measure_state"] == "measured"
    assert summary["evidenced_cases"] == 9


def test_summary_reports_not_attempted_when_the_round_never_measured(rsi_probe_factory):
    """观察期根本不跑自动执行 → 没有度量可报，也不许编一个"measured 0 例"。"""
    from neurova.evolution.rsi.result_summary import summarize_rsi_result

    probe = rsi_probe_factory(rsi_phase=0)

    summary = summarize_rsi_result(probe.orchestrator.run_iteration())

    assert summary["measure_state"] == "not_attempted"
    assert summary["evidenced_cases"] is None


def test_convergence_states_are_a_declared_closed_set():
    """六态必须成词表：响应面与判据都按它分派，自造第七态会漏进 else 分支。"""
    from neurova.evolution.rsi.convergence_analyzer import CONVERGENCE_STATES

    assert set(CONVERGENCE_STATES) == {
        "converged", "converging", "oscillating", "diverging",
        "insufficient_data", "measurement_blind",
    }
