"""知识 token 归因策略（纯函数，便于判据钉死三条路径）。

顺序固定：显式引用 → 权重估计 → 均分 → 未归因。
返回 (allocations, unattributed, attribution)；allocations[fact_id] = (prompt, completion)。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple


def _split(total: int, keys: List[str], weights: Optional[Dict[str, float]] = None
           ) -> Dict[str, int]:
    total = max(0, int(total))
    if not keys or total == 0:
        return {key: 0 for key in keys}
    raw = []
    for key in keys:
        weight = float((weights or {}).get(key, 0.0) or 0.0)
        raw.append(max(0.0, weight))
    if sum(raw) <= 0:
        raw = [1.0] * len(keys)
    denom = sum(raw)
    shares = [int(total * value / denom) for value in raw]
    remainder = total - sum(shares)
    for index in range(remainder):
        shares[index % len(shares)] += 1
    return {key: share for key, share in zip(keys, shares)}


def allocateGenerationTokens(
    factIds: Iterable[str],
    promptTokens: int,
    completionTokens: int,
    citationIds: Optional[Iterable[str]] = None,
    weights: Optional[Dict[str, float]] = None,
) -> Tuple[Dict[str, Tuple[int, int]], Tuple[int, int], str]:
    ids = list(dict.fromkeys(str(f) for f in (factIds or []) if f))
    prompt = max(0, int(promptTokens or 0))
    completion = max(0, int(completionTokens or 0))
    if not ids:
        return {}, (prompt, completion), "unattributed"

    citations = {str(c) for c in (citationIds or []) if c}
    selected = [factId for factId in ids if factId in citations]
    if selected:
        p = _split(prompt, selected)
        c = _split(completion, selected)
        allocations = {factId: (p.get(factId, 0), c.get(factId, 0)) for factId in selected}
        return allocations, (0, 0), "explicit_citation"

    positive = any(float((weights or {}).get(factId, 0.0) or 0.0) > 0 for factId in ids)
    if positive:
        p = _split(prompt, ids, weights)
        c = _split(completion, ids, weights)
        return (
            {factId: (p[factId], c[factId]) for factId in ids},
            (0, 0),
            "weighted_estimate",
        )

    p = _split(prompt, ids)
    c = _split(completion, ids)
    return (
        {factId: (p[factId], c[factId]) for factId in ids},
        (0, 0),
        "even_split",
    )
