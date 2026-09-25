"""评测集分母剔除回退用例（工单 007）。

`eval_harness._param()` 在系统未暴露某参数时回退到 setpoint（:32-39），
而 `run()` 的 `overall = sum(score)/len(cases)`（:318）把回退用例照常计入分子分母
—— 于是"系统没暴露参数"表现为满分，棘轮前后之差恒 0。
文件头自称"行为安全地板，而非参数贴贴度复读机"，现状恰是它声称不是的那个东西。

本单要求：回退用例不得参与计分；全族回退时显式报 `measurement_blind`，
而不是给出一个看起来很好的 1.0。
"""

import pytest

from neurova.evolution.rsi.eval_harness import EVAL_CASES, RSIEvalHarness


def _live_params(**overrides):
    """构造一份 live_params：未出现在 overrides 里的系统一律为 {}（→ 触发 setpoint 回退）。"""
    return overrides


TM_ALL = {
    "success_bonus": 0.1,
    "failure_penalty": 0.05,
    "decay_rate": 0.01,
    "muscle_memory_threshold": 0.8,
}
SLEEP_ALL = {"base_decay_rate": 0.1, "similarity_threshold": 0.7}
EMOTION_ALL = {"emotional_protection_threshold": 0.5, "emotional_protection_factor": 0.3}
EXPERIENCE_ALL = {
    "crystallize_min_observations": 3,
    "crystallize_min_success_rate": 0.6,
    "pattern_min_support": 2,
}


def test_every_family_falling_back_to_setpoint_reports_measurement_blind():
    """四系统全不暴露参数时，评测集必须说"我量不出来"，而不是给满分。

    这是工单 008 取消"零证据即收敛"的输入：编排器需要能区分
    "参数确实没改善"（gain=0 且有效测量）与"参数改了但评测集看不见"（无有效测量）。
    """
    result = RSIEvalHarness().run({})

    assert result["state"] == "measurement_blind", (
        f"全族回退被报成了一次有效测量：score={result.get('score')} state={result.get('state')}")
    assert result["evidenced_cases"] == 0
    assert result["blind_cases"] == len(EVAL_CASES)
    assert result["score"] is None, "无有效用例时不得给出分数（0.0 与 1.0 都是假信号）"


def test_blind_cases_are_excluded_from_the_denominator():
    """只有 tool_memory 暴露参数时，分数只由该族用例算出。

    期望值独立可推：三族回退 → 9 个用例里 tool_memory 族 3 个有证据、6 个无证据；
    有证据的三个在 setpoint 默认下均满分 → score=1.0，但 evidenced_cases 必须是 3。
    """
    result = RSIEvalHarness().run(_live_params(tool_memory=TM_ALL))

    assert result["state"] == "measured"
    assert result["evidenced_cases"] == 3, (
        f"分母未剔除回退用例：{result['evidenced_cases']}/{len(EVAL_CASES)}")
    assert result["blind_cases"] == 6
    assert result["score"] == pytest.approx(1.0)


def test_partially_exposed_family_is_still_blind_for_that_family():
    """同族内只暴露一半参数时，该族用例仍算无证据（缺一个参数就无法复现行为）。

    `tm_multiplier_differentiation` 需要 bonus 与 penalty 同时在场才能判"奖惩分化"，
    只给 bonus 会让 penalty 回退 setpoint，用例结论就不再来自真实参数。
    """
    result = RSIEvalHarness().run(_live_params(
        tool_memory={"success_bonus": TM_ALL["success_bonus"]}))

    tm_cases = [c for c in result["cases"] if c["family"] == "tool_memory"]
    assert all(not c["evidenced"] for c in tm_cases), (
        f"部分回退被当成有效测量：{[(c['id'], c.get('evidenced')) for c in tm_cases]}")


def test_blind_cases_do_not_inflate_score_above_evidenced_ones():
    """核心不变式：回退用例不得把分数抬到有效用例均值之上。

    构造：只暴露 tool_memory，且把肌肉阈值推到 5.0 越出 (0,1] 语义域。
    该族 3 个用例全有证据（1.0 / 1.0 / 0.0），其余 6 个回退被剔除 →
    score 必须恰等于有效用例均值 2/3；若回退用例仍计入分母则是 6/9 = 0.667→
    与 1.0 分满分假象不可区分的另一种形态。
    """
    bad = dict(TM_ALL)
    bad["muscle_memory_threshold"] = 5.0  # 越出 (0,1] 语义域 → tm_threshold_band 判 0 分
    result = RSIEvalHarness().run(_live_params(tool_memory=bad))

    evidenced = [c["score"] for c in result["cases"] if c["evidenced"]]
    assert len(evidenced) == 3, f"tool_memory 族应有 3 个有效用例，实际 {len(evidenced)}"
    assert result["score"] == pytest.approx(sum(evidenced) / len(evidenced)), (
        f"分数被无证据用例污染：{result['score']} vs 有效均值 {sum(evidenced)/len(evidenced)}")
    assert result["score"] < 1.0, (
        f"越界参数被算成满分：score={result['score']}")


def test_run_stays_deterministic_and_reports_per_case_provenance():
    """确定性契约不得因本单退化；同时每个用例要自证量的是真实参数。"""
    params = _live_params(tool_memory=TM_ALL, sleep=SLEEP_ALL)

    first = RSIEvalHarness().run(params)
    second = RSIEvalHarness().run(params)

    assert first == second, "评测集失去确定性"
    assert all("evidenced" in case for case in first["cases"]), "用例未自报证据来源"
    # tool_memory 3 个用例 + sleep 2 个用例（同一对参数各测一种行为）共 5 个有效；
    # emotion / experience 未暴露 → 4 个回退用例被剔出分母。
    assert first["evidenced_cases"] == 5, (
        f"tool_memory 3 + sleep 2 应有 5 个有效用例，实际 {first['evidenced_cases']}")
    assert first["blind_cases"] == 4


def test_harmful_drift_is_still_caught_with_blind_families_excluded():
    """放大视角的反向要求：剔除回退用例不能让真危害逃掉。

    只暴露 tool_memory 且把 decay_rate 推到 1.0（瞬间清零乘数）→
    `tm_decay_forgetting_band` 必须失分，且该用例是有证据的。
    """
    harmful = dict(TM_ALL)
    harmful["decay_rate"] = 1.0

    result = RSIEvalHarness().run(_live_params(tool_memory=harmful))

    decay_case = next(c for c in result["cases"] if c["id"] == "tm_decay_forgetting_band")
    assert decay_case["evidenced"] is True
    assert decay_case["score"] == 0.0, (
        f"有害漂移未被量出：{decay_case}")
    assert result["state"] == "measured"
