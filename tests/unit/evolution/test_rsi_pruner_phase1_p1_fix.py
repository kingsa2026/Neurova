"""
P1 RSI 剪枝修复测试（2026-08 代码审计）

覆盖 bug:
1. EnhancedRatchetPruner.prune_candidates 第一阶段递归剪枝后，
   把全部原始候选重新加回 → 递归剪枝完全失效，无效候选存活
2. 第二阶段基础剪枝只做 top-k 不排除 validation_score<=0 的候选
   → 未通过验证的候选仍会被返回给编排器
"""

import pytest

from neurova.evolution.rsi.recursive_ratchet_pruner import (
    Candidate,
    EnhancedRatchetPruner,
)


def _make_candidates(n_valid: int, n_invalid: int):
    candidates = []
    for i in range(n_valid):
        candidates.append(
            Candidate(id=f"valid-{i}", name=f"valid-{i}", parameters={"kind": "valid", "i": i})
        )
    for i in range(n_invalid):
        candidates.append(
            Candidate(id=f"invalid-{i}", name=f"invalid-{i}", parameters={"kind": "invalid", "i": i})
        )
    return candidates


def _validation_fn(c: Candidate):
    if c.parameters.get("kind") == "valid":
        return {"functional_correctness": 0.9, "performance_baseline": 0.9}
    return {}


def _heuristic_fn(c: Candidate):
    return 1.0 if c.parameters.get("kind") == "valid" else 0.1


def _quick_fn(c: Candidate):
    return 1.0 if c.parameters.get("kind") == "valid" else 0.1


class TestEnhancedPrunerPhase1:
    def _make_pruner(self, max_candidates=10):
        return EnhancedRatchetPruner(
            max_candidates_per_dimension=max_candidates,
            use_recursive=True,
            recursive_rounds=3,
            recursive_candidates_per_round=[30, 15, 5],
        )

    def test_invalid_candidates_eliminated(self):
        """25 个候选（5 有效 + 20 无效），剪枝结果不得包含无效候选"""
        pruner = self._make_pruner(max_candidates=10)
        candidates = _make_candidates(5, 20)

        result = pruner.prune_candidates(
            "test_dim",
            candidates,
            validation_fn=_validation_fn,
            quick_eval_fn=_quick_fn,
            heuristic_fn=_heuristic_fn,
        )

        result_ids = {c.id for c in result}
        leaked = {cid for cid in result_ids if cid.startswith("invalid-")}
        assert not leaked, f"无效候选未被剪枝淘汰: {leaked}"
        assert result, "有效候选应保留"

    def test_phase1_actually_reduces_candidates(self):
        """30 个全部有效的候选，递归剪枝每轮 [30,15,5] → 结果不得超过 5 个存活者"""
        pruner = self._make_pruner(max_candidates=10)
        candidates = _make_candidates(30, 0)

        result = pruner.prune_candidates(
            "test_dim",
            candidates,
            validation_fn=_validation_fn,
            quick_eval_fn=_quick_fn,
            heuristic_fn=_heuristic_fn,
        )

        assert len(result) <= 5, f"第一阶段未真正剪枝（返回 {len(result)} 个，期望 ≤5）"
        assert len(result) > 0

    def test_all_invalid_returns_empty(self):
        """全部候选验证失败时，棘轮语义要求不返回任何候选"""
        pruner = self._make_pruner(max_candidates=10)
        candidates = _make_candidates(0, 25)

        result = pruner.prune_candidates(
            "test_dim",
            candidates,
            validation_fn=_validation_fn,
            quick_eval_fn=_quick_fn,
            heuristic_fn=_heuristic_fn,
        )

        assert result == [], f"全部候选未通过验证时必须返回空列表，实际返回 {len(result)} 个"

    def test_small_candidate_set_skips_phase1_but_still_filters_invalid(self):
        """候选数 ≤20 不触发递归阶段，但基础阶段仍须排除验证失败的候选"""
        pruner = self._make_pruner(max_candidates=10)
        candidates = _make_candidates(3, 10)

        result = pruner.prune_candidates(
            "test_dim",
            candidates,
            validation_fn=_validation_fn,
        )

        result_ids = {c.id for c in result}
        assert all(cid.startswith("valid-") for cid in result_ids), f"无效候选泄漏: {result_ids}"
        assert len(result) == 3

    def test_no_validation_fn_keeps_top_k_by_heuristic(self):
        """无 validation_fn 时保持原 top-k 行为（不误伤）"""
        pruner = self._make_pruner(max_candidates=3)
        candidates = _make_candidates(10, 0)

        result = pruner.prune_candidates(
            "test_dim",
            candidates,
            heuristic_fn=_heuristic_fn,
        )

        assert len(result) == 3
