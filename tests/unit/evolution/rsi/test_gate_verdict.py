"""判据三态契约（工单 003）。

RSI 的晋升/停止判据此前只有二态，于是"取不到数据"被编码成"数据为 0"并继续参与判定。
本文件锁住三态契约：`passed` / `failed` / `unevidenced`，且 **unevidenced 从类型上
就不可能被当成通过**。这是 spec §2 里"可证伪"这条核心约束的落地把手，
工单 004-009 与 018 第 4 项都往这个对象上挂判据。
"""

import pytest

from neurova.evolution.rsi.gate_verdict import GateVerdict


def test_only_passed_verdict_is_truthy():
    """`if verdict:` 必须只在 passed 时为真。

    这是防止判据退化的关键：如果 unevidenced 为真，调用方的 `if verdict:`
    会把"没有证据"读成"可以晋升"，与现状无异。
    """
    assert bool(GateVerdict.passed(reason="满足全部判据")) is True
    assert bool(GateVerdict.failed(reason="检测到发散")) is False
    assert bool(GateVerdict.unevidenced(reason="metrics 缺 roi 键")) is False


def test_verdict_states_are_a_closed_set():
    """状态集合封闭，防止各处自造第四态导致消费方判不全。"""
    assert {GateVerdict.STATE_PASSED, GateVerdict.STATE_FAILED,
            GateVerdict.STATE_UNEVIDENCED} == {"passed", "failed", "unevidenced"}
    with pytest.raises(ValueError):
        GateVerdict(state="maybe")


def test_verdict_carries_reason_and_is_not_silently_defaulted():
    """unevidenced 必须写明缺哪样证据 —— 静默降级正是本批要消灭的行为。"""
    verdict = GateVerdict.unevidenced(reason="缺 days_without_rollback", evidence="phase=1")

    assert verdict.state == "unevidenced"
    assert "days_without_rollback" in verdict.reason
    assert verdict.evidence == "phase=1"


def test_unevidenced_without_reason_is_rejected():
    """无理由的 unevidenced 等于又一次静默吞掉，必须拒收。"""
    with pytest.raises(ValueError):
        GateVerdict.unevidenced(reason="")


# ── 判据接入：部署阶段晋升（工单 003 交付项 2）──────────────────────


def _controller(phase: int = 0):
    from neurova.evolution.rsi.deployment_controller import RSIDeploymentController

    return RSIDeploymentController(initial_phase=phase)


def test_promotion_passes_when_every_guard_has_evidence():
    """三项判据都有证据且满足时，判 passed。"""
    verdict = _controller(0).evaluate_phase_transition({
        "convergence_status": "converging", "roi": 0.1, "days_without_rollback": 0,
    })

    assert verdict.state == "passed", verdict.reason
    assert bool(verdict) is True


def test_diverging_vetoes_even_where_not_required():
    """硬否决类读数只要存在就生效，不因"此阶段不要求"而豁免（工单 008）。"""
    verdict = _controller(1).evaluate_phase_transition({
        "convergence_status": "diverging", "roi": 0.1, "days_without_rollback": 30,
    })

    assert verdict.state == "failed"
    assert bool(verdict) is False


def test_measurement_blind_vetoes_promotion():
    """零证据窗口不得被当成"没发散所以可以推进"（工单 008）。

    `measurement_blind` 与 `insufficient_data` 是两回事：前者是"量不出来"，
    再多样本也无效；后者只是样本还没攒够。
    """
    verdict = _controller(1).evaluate_phase_transition({
        "convergence_status": "measurement_blind", "roi": 0.1, "days_without_rollback": 30,
    })

    assert verdict.state == "failed"
    assert "measurement_blind" in verdict.reason


def test_insufficient_data_does_not_block_phases_below_auto_execution():
    """样本不足不否决 phase 0/1 晋升 —— 否则晋升链会锁成循环依赖（工单 008 裁决）。

    收敛证据只有在真的自动执行过参数之后才可能存在，而自动执行要求先晋升到 phase 2；
    一律要求"收敛状态有效"等于任何阶段都出不去。
    phase 2 起低风险自动执行已在跑，读数该在盘上了，那时转为必需。
    """
    assert _controller(1).evaluate_phase_transition({
        "convergence_status": "insufficient_data", "roi": None, "days_without_rollback": 30,
    }).state == "passed"

    verdict = _controller(2).evaluate_phase_transition({
        "convergence_status": "insufficient_data", "roi": 0.1, "days_without_rollback": 30,
    })
    assert verdict.state == "unevidenced"
    assert "insufficient_data" in verdict.reason


def test_oscillating_is_failed_not_silently_promotable():
    """白名单判据：未被列举为"可晋升"的收敛读数不得因"没被列举为否决"而放行。

    黑名单写法（只列 diverging / measurement_blind）会让分析器新增的失稳态
    默认落在"通过"一侧 —— 与工单 003 要消灭的兜底同病。
    """
    verdict = _controller(2).evaluate_phase_transition({
        "convergence_status": "oscillating", "roi": 0.1, "days_without_rollback": 30,
    })

    assert verdict.state == "failed"
    assert "oscillating" in verdict.reason


def test_missing_roi_is_unevidenced_only_where_required():
    """roi 缺席在 phase 3 判无证据，在低阶段不阻塞（必需性按阶段声明）。

    工单 006 已拆掉编排器那处 `get("roi", 0.0)` 伪造：取不到就不塞键，
    于是"该不该要这份证据"成为显式契约而不是兜底值的副产品。
    """
    at_three = _controller(3).evaluate_phase_transition({
        "convergence_status": "converging", "days_without_rollback": 40,
    })
    assert at_three.state == "unevidenced"
    assert "roi" in at_three.reason

    assert _controller(1).evaluate_phase_transition({
        "convergence_status": "converging", "days_without_rollback": 40,
    }).state == "passed"


def test_missing_days_is_unevidenced_only_when_the_guard_needs_it():
    """无回滚天数：phase 0 的门槛是 0 天，缺键无所谓；phase 1 要求 7 天，缺键即无证据。"""
    assert _controller(0).evaluate_phase_transition({
        "convergence_status": "converging", "roi": 0.1,
    }).state == "passed"

    verdict = _controller(1).evaluate_phase_transition({
        "convergence_status": "converging", "roi": 0.1,
    })
    assert verdict.state == "unevidenced"
    assert "days_without_rollback" in verdict.reason


def test_negative_roi_is_failed_not_unevidenced():
    """有证据且证据为负 → failed。与"取不到证据"必须是两个态。"""
    verdict = _controller(0).evaluate_phase_transition({
        "convergence_status": "converging", "roi": -0.5, "days_without_rollback": 0,
    })

    assert verdict.state == "failed"
    assert bool(verdict) is False


def test_diverging_is_failed():
    verdict = _controller(0).evaluate_phase_transition({
        "convergence_status": "diverging", "roi": 0.1, "days_without_rollback": 0,
    })

    assert verdict.state == "failed"
    assert "diverg" in verdict.reason.lower()


def test_days_short_of_requirement_is_failed():
    """有读数但不够门槛 → failed（证据在，只是不满足）。"""
    verdict = _controller(1).evaluate_phase_transition({
        "convergence_status": "converging", "roi": 0.1, "days_without_rollback": 3,
    })

    assert verdict.state == "failed"
    assert "7" in verdict.reason


def test_max_phase_reports_failed_without_needing_evidence():
    """已在最高阶段：不该再要求任何证据，直接 failed。"""
    assert _controller(4).evaluate_phase_transition({}).state == "failed"


def test_verdict_reasons_are_collected_not_first_wins_only():
    """多判据同时缺证据时，reason 要一次列全，否则修一个又冒一个。

    取 phase 3：三道读数（收敛结论、roi、无回滚天数）在该阶段全部必需，
    于是空 metrics 应一次把三项都写进 reason —— 这也顺带锁住了必需表本身。
    """
    verdict = _controller(3).evaluate_phase_transition({})

    assert verdict.state == "unevidenced"
    for key in ("convergence_status", "roi", "days_without_rollback"):
        assert key in verdict.reason, f"reason 未列出 {key}：{verdict.reason}"
