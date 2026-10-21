"""N4：参数轮与候选评测轮的账实恒等式。"""

import pytest

from neurova.evolution.eval.runner import EvolutionRunResult
from neurova.evolution.rsi.orchestrator import (
    assertRsiOptimizationIdentity,
    assertRsiRoundIdentity,
)


def test_rsi_round_identity_accepts_one_result_per_parameter():
    opts = [{"parameter": "tool_memory.success_bonus"}, {"parameter": "sleep.decay"}]
    results = [{"parameter": opts[0]["parameter"], "applied": True},
               {"parameter": opts[1]["parameter"], "applied": False}]
    assertRsiOptimizationIdentity(opts)
    assertRsiRoundIdentity(opts, results)


def test_rsi_round_identity_rejects_duplicates_and_missing_results():
    duplicates = [
        {"parameter": "tool_memory.success_bonus"},
        {"parameter": "tool_memory.success_bonus"},
    ]
    with pytest.raises(AssertionError, match="同一参数"):
        assertRsiOptimizationIdentity(duplicates)

    with pytest.raises(AssertionError, match="参数账实不符"):
        assertRsiRoundIdentity([{"parameter": "a"}], [])

    with pytest.raises(AssertionError, match="缺参数名"):
        assertRsiOptimizationIdentity([{"parameter": ""}])


def test_candidate_identity_accepts_generated_minus_pre_eval_rejections():
    result = EvolutionRunResult(
        candidates_generated=3,
        candidates_rejected_pre_eval=1,
        candidates_evaluated=2,
        iterations_run=2,
    )
    result.assertCandidateIdentity()

    result.candidates_evaluated = 1
    with pytest.raises(AssertionError, match="候选账实不符"):
        result.assertCandidateIdentity()
