"""采纳反馈的检索重排先验（单一权重表）。

只作用于能映射到事实行的命中；无 lineage 的文档命中拿不到 adoption，
按中性 1.0 处理。权重刻意保持轻量：failure 降权、success 小幅升权，
不让一次反馈压过 RRF 的多路相关性证据。
"""

from __future__ import annotations

from typing import Any, Dict, List

#: 唯一权重表；新增三态必须在这里登记，不在调用点各写一份。
ADOPTION_WEIGHTS: Dict[str, float] = {
    "success": 1.10,
    "unevidenced": 1.0,
    "failure": 0.60,
}
ADOPTION_NEUTRAL = 1.0


def adoptionWeight(outcome: Any) -> float:
    return ADOPTION_WEIGHTS.get(str(outcome or "").strip().lower(), ADOPTION_NEUTRAL)


def rerankByAdoption(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按 RRF 分 × 采纳权重重排；保留 base_score 供审计与后续解释。"""
    ranked: List[Dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        base = float(item.get("score", 0.0) or 0.0)
        weight = adoptionWeight(item.get("adoption_outcome"))
        row = dict(item)
        row["base_score"] = base
        row["adoption_prior"] = weight
        row["score"] = base * weight
        ranked.append(row)
    ranked.sort(key=lambda row: (row["score"], row["base_score"]), reverse=True)
    return ranked
