"""冲突四象限的离线标注评估：准确率与误合并/漏判读数。

输入是带人工真值的用例（left/right/expected），不读生产账本；没有用例时
`unevidenced`，绝不把 0 当"没有冲突"。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from neurova.knowledge.conflict_features import buildConflictFeatures, classifyConflict

_DECISIONS = ("similar", "conflict", "different", "manual")


def evaluateConflictCases(cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    rows = list(cases or [])
    if not rows:
        return {
            "measure_state": "unevidenced",
            "case_count": 0,
            "missing_reason": "没有带标注的冲突用例，读数无依据",
        }
    confusion = {expected: {actual: 0 for actual in _DECISIONS} for expected in _DECISIONS}
    invalid: List[Dict[str, Any]] = []
    similarAsConflict = 0
    conflictTotal = 0
    mergedConflict = 0
    for case in rows:
        expected = str(case.get("expected") or "")
        if expected not in _DECISIONS:
            invalid.append({"case_id": case.get("case_id", ""), "reason": "invalid_expected"})
            continue
        features = buildConflictFeatures(
            str(case.get("left") or ""),
            str(case.get("right") or ""),
            vectorSimilarity=case.get("vector_similarity"),
            subjectSimilarity=case.get("subject_similarity"),
        )
        decision, _reason = classifyConflict(features)
        confusion[expected][decision] += 1
        if expected == "conflict":
            conflictTotal += 1
            if decision == "similar":
                mergedConflict += 1
        if decision == "conflict" and expected == "similar":
            similarAsConflict += 1
    evaluated = sum(sum(row.values()) for row in confusion.values())
    if not evaluated:
        return {
            "measure_state": "unevidenced",
            "case_count": len(rows),
            "invalid_cases": invalid,
            "missing_reason": "所有用例的 expected 非法，读数无依据",
        }
    correct = sum(confusion[name][name] for name in _DECISIONS)
    return {
        "measure_state": "measured",
        "case_count": len(rows),
        "evaluated_count": evaluated,
        "invalid_cases": invalid,
        "accuracy": round(correct / evaluated, 6),
        "confusion": confusion,
        "false_merge_rate": (
            round(mergedConflict / conflictTotal, 6) if conflictTotal else None
        ),
        "false_split_count": similarAsConflict,
        "missing_reason": (
            "" if conflictTotal else "用例里没有 expected=conflict 的样本，误合并率分母为 0"
        ),
    }
