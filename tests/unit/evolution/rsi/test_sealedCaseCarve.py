# -*- coding: utf-8 -*-
"""RSI 侧密封档（D1，survey §10.2）：9 固定用例划出永不进 gain/候选生成的 sealed 档。

判据三件事：
- 切分确定性（单一出处 `splitSealedCases`）＋守卫（决策档 ≥1、密封 id 必须在册）；
- gain 路径（`RSIEvalHarness.run`）只由决策档算出——密封用例不得进分母；
- 密封档作决策后的验收证据（`run_sealed`），编排器状态面必须呈报（拒绝"写了没人读"）。
"""

import pytest

from neurova.evolution.rsi.eval_harness import (
    EVAL_CASES,
    RSIEvalHarness,
    splitSealedCases,
)
from neurova.evolution.rsi.system_performance import SYSTEM_SETPOINTS

#: 与 test_rsi_eval_harness 同款的真值基准：参数全在 setpoint。
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


def _setpoint_params():
    return {
        "tool_memory": dict(TM_ALL),
        "sleep": dict(SLEEP_ALL),
        "emotion": dict(EMOTION_ALL),
        "experience": dict(EXPERIENCE_ALL),
    }


def test_sealed_split_is_deterministic_and_guarded():
    """切分单一出处：密封档在册、两档不相交、决策档至少留 1 例、逐次调用稳定。"""
    decision, sealed = splitSealedCases()
    decision_ids = [case_id for case_id, _, _ in decision]
    sealed_ids = [case_id for case_id, _, _ in sealed]

    assert set(sealed_ids) <= {case_id for case_id, _, _ in EVAL_CASES}, (
        "密封档出现注册表之外的用例 id——切分失守")
    assert not (set(decision_ids) & set(sealed_ids)), "两档相交——密封语义失效"
    assert decision_ids, "决策档被切空——carve_heldout 的'判据侧至少留 1'守卫必须镜像"
    assert 2 <= len(sealed_ids) <= 3, f"密封档规模越出票面约定（2–3 例）：{len(sealed_ids)}"
    again = splitSealedCases()
    assert [c[0] for c in again[0]] == decision_ids
    assert [c[0] for c in again[1]] == sealed_ids


def test_decision_set_keeps_all_four_families():
    """决策档必须四族全覆盖——它是回滚安全地板，缺族即漂移盲区。"""
    decision, _ = splitSealedCases()
    families = {family for _, family, _ in decision}
    assert families == {"tool_memory", "sleep", "emotion", "experience"}, (
        f"决策档缺族：{families}——gain 对缺族漂移失明")


def test_harness_gain_path_scores_decision_cases_only():
    """gain 路径的分母只含决策档——密封用例不得进 gain（否则密封语义失效）。"""
    decision, sealed = splitSealedCases()
    sealed_ids = {case_id for case_id, _, _ in sealed}

    outcome = RSIEvalHarness().run(_setpoint_params())
    outcome_ids = {c["id"] for c in outcome["cases"]}

    assert outcome_ids == {case_id for case_id, _, _ in decision}, (
        "run() 的用例集与决策档不一致——gain 分母失守")
    assert not (outcome_ids & sealed_ids), "密封用例进了 gain 分母"


def test_harness_sealed_readout_covers_sealed_cases():
    """密封档只作决策后验收证据：run_sealed 的用例集恰为密封档，setpoint 下满分。"""
    _, sealed = splitSealedCases()

    outcome = RSIEvalHarness().run_sealed(_setpoint_params())

    assert {c["id"] for c in outcome["cases"]} == {case_id for case_id, _, _ in sealed}
    assert outcome["state"] == "measured"
    assert outcome["score"] == pytest.approx(1.0)


def test_sealed_evidence_surfaces_after_decision(rsi_probe_factory):
    """编排器状态面必须呈报密封证据（消费面格：拒绝"写了没人读"）。

    phase 2 自动执行档 + tool_memory 真实梯度 → 真跑一轮（候选→应用→前测后测→
    决策落定）→ sealed_evidence 出现在 get_status，且用例集恰为密封档；
    同面顺带呈报决策档 eval_outcome（此前 _last_eval_outcome 只写不读）。
    """
    probe = rsi_probe_factory(rsi_phase=2)
    probe.orchestrator.run_iteration()

    status = probe.orchestrator.get_status()
    sealed = status.get("sealed_evidence")
    assert isinstance(sealed, dict) and sealed.get("state") not in (None, "unevidenced"), (
        f"决策落定后密封证据未呈报：{sealed}——写了没人读")
    _, sealed_cases = splitSealedCases()
    assert {c["id"] for c in sealed.get("cases", [])} == {cid for cid, _, _ in sealed_cases}

    eval_outcome = status.get("eval_outcome")
    assert isinstance(eval_outcome, dict) and eval_outcome.get("state") == "measured", (
        f"决策档读数未呈报：{eval_outcome}")
