"""检索结果链级 RRF 融合（可选，默认关闭）。

各 retriever 仍各自返回 RetrievalResult；本模块只把它们的 memory 列表按秩融合，
用于图谱/记忆/知识并列时不再“选一个最好的”。默认 legacy 路径不变，
`NEUROVA_RETRIEVAL_FUSION=rrf` 时启用。
"""
from __future__ import annotations

import os
from typing import Any, Dict, Iterable, List, Tuple

FUSION_ENV = "NEUROVA_RETRIEVAL_FUSION"
FUSION_K = 60

_ID_KEYS = ("memory_id", "knowledge_id", "fact_id", "id")


def _identity(item: Dict[str, Any]) -> str:
    for key in _ID_KEYS:
        value = str(item.get(key) or "")
        if value:
            return value
    return ""


def fuseRetrievalResults(
    results: Iterable[Any],
    limit: int = 10,
    weights: Dict[str, float] | None = None,
    k: int = FUSION_K,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """按来源 RRF 融合；同 id 保留首条内容并累加分数，附 routes 证据。"""
    routes: Dict[str, List[Tuple[str, float]]] = {}
    byId: Dict[str, Dict[str, Any]] = {}
    for result in results:
        memories = list(getattr(result, "memories", None) or [])
        source = str(getattr(result, "source", "") or "unknown")
        ranked: List[Tuple[str, float]] = []
        for index, item in enumerate(memories, start=1):
            if not isinstance(item, dict):
                continue
            docId = _identity(item)
            if not docId:
                continue
            ranked.append((docId, float(item.get("score", 0.0) or 0.0)))
            row = byId.setdefault(docId, dict(item))
            row.setdefault("routes", []).append({"source": source, "rank": index})
        if ranked:
            routes[source] = ranked
    if not routes:
        return [], {"routes": 0, "fused": 0}
    effective = {name: float((weights or {}).get(name, 1.0)) for name in routes}
    fused: Dict[str, float] = {}
    for name, ranked in routes.items():
        weight = effective.get(name, 1.0)
        if weight <= 0:
            continue
        for rank, (docId, _score) in enumerate(ranked, start=1):
            fused[docId] = fused.get(docId, 0.0) + weight / (k + rank)
    ordered = sorted(fused.items(), key=lambda pair: pair[1], reverse=True)
    out = []
    for docId, score in ordered[: max(1, int(limit))]:
        row = byId[docId]
        row["score"] = round(score, 6)
        out.append(row)
    return out, {"routes": len(routes), "fused": len(out), "source_counts": {
        name: len(ranked) for name, ranked in routes.items()
    }}


def fusionEnabled() -> bool:
    return str(os.environ.get(FUSION_ENV) or "off").strip().lower() in (
        "rrf", "on", "1", "true", "yes"
    )
