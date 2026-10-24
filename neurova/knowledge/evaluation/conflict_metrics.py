"""冲突度量：检出分布与有标签的误合并率。

没有人工标签时只报分布与 `unevidenced`，不把"判成 similar 的比例"冒充误合并率。
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

_DECISIONS = ("similar", "conflict", "different", "manual")


def conflictMetrics(
    records: Iterable[Dict[str, Any]],
    labels: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """records: 冲突账；labels: {conflict_id: 人工判定}，判定取 same 四态。

    - `conflict_share` 是账本里判成冲突的比例，不是检出率（检出率需要真值）；
    - `false_merge_rate` 只在给出标签时计算：判 similar 而人工判 conflict 的比例；
    - 没有任何账本时 `measure_state=unevidenced`，绝不回 0 当"没有冲突"。
    """
    rows = list(records or [])
    if not rows:
        return {
            "measure_state": "unevidenced",
            "conflict_count": 0,
            "decision_counts": {name: 0 for name in _DECISIONS},
            "pending_count": 0,
            "conflict_share": None,
            "false_merge_rate": None,
            "missing_reason": "冲突账本为空：既可能真的没有同标题新说法，也可能链路未触发",
        }
    counts = {name: 0 for name in _DECISIONS}
    pending = 0
    for row in rows:
        decision = str(row.get("decision") or "")
        if decision in counts:
            counts[decision] += 1
        if str(row.get("status") or "") == "pending":
            pending += 1
    scored = sum(counts.values())
    result: Dict[str, Any] = {
        "measure_state": "measured" if scored else "unevidenced",
        "conflict_count": len(rows),
        "decision_counts": counts,
        "pending_count": pending,
        "conflict_share": round(counts["conflict"] / scored, 6) if scored else None,
        "false_merge_rate": None,
    }
    if not scored:
        result["missing_reason"] = "账本里没有带 decision 的记录（旧账或特征层未落）"
        return result

    labels = dict(labels or {})
    comparable = [
        row for row in rows
        if str(row.get("conflict_id") or "") in labels
        and str(row.get("decision") or "") in _DECISIONS
    ]
    if not comparable:
        result["missing_reason"] = "没有人工复核标签，误合并率无法计算（不改报 0）"
        return result
    falseMerges = 0
    similarCount = 0
    correct = 0
    for row in comparable:
        decision = str(row.get("decision"))
        expected = str(labels[str(row.get("conflict_id"))])
        if decision == expected:
            correct += 1
        if decision == "similar":
            similarCount += 1
            if expected == "conflict":
                falseMerges += 1
    result["labeled_count"] = len(comparable)
    result["decision_accuracy"] = round(correct / len(comparable), 6)
    result["false_merge_rate"] = (
        round(falseMerges / similarCount, 6) if similarCount else None
    )
    if similarCount == 0:
        result["missing_reason"] = "标签集里没有被判 similar 的记录，误合并率分母为 0"
    return result
