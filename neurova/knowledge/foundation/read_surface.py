"""知识读面（工单 011，设计文档 §7）：叙述条目 + 底座事实的统一检索入口。

纪律：
- 关闸态必须**逐位等于**旧行为——旧路一行代码都不改，事实池根本不被调用。
- 事实池排序复用 `hybrid.bm25_rank` 与 `hybrid.rrf_fusion` 原件，不另写第二套打分器；
  否则"基线变差"到底是知识变差还是尺子变了，就再也分不清。
- 时效与置信两项是**排序修正**，不融进 RRF 秩本身（RRF 只吃秩不吃分数，ADR 0007）。
- 命中即写使用计数（010 的触发点）：没有这一步，"零使用占比"永远是 100%。
"""

from __future__ import annotations

import datetime
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.knowledge.hybrid import bm25_rank

from .knowledge_facts import KnowledgeFactStore, normalizeLabel

logger = get_logger(__name__)

ENV_FLAG = "NEUROVA_KB_FACT_SURFACE"


@dataclass
class FactSurfaceConfig:
    """读面开关。默认关：新能力的默认态必须是旧行为。"""

    enabled: bool = False
    freshnessWeight: float = 0.15
    confidenceWeight: float = 0.20
    halfLifeDays: float = 180.0

    @classmethod
    def fromEnv(cls) -> "FactSurfaceConfig":
        raw = (os.environ.get(ENV_FLAG) or "").strip().lower()
        enabled = raw in ("1", "true", "on", "yes")
        return cls(enabled=enabled)


def factToItem(fact: Dict[str, Any], canonicalLabel: str) -> Dict[str, Any]:
    """事实 → 检索条目形状（同一形状的 id 才能与叙述命中一起排序）。"""
    return {
        "knowledge_id": fact["fact_id"],
        "title": "%s · %s" % (canonicalLabel, fact["object_term"]),
        "content": fact.get("content") or "%s %s %s" % (
            canonicalLabel, fact["predicate_term_id"], fact["object_term"]),
        "category": "fact",
        "tags": ["fact"],
        "source": "knowledge_foundation",
        "confidence": fact.get("confidence"),
        "visibility": "private",
        "record_kind": "fact",
        "lineage_id": fact["fact_id"],
        "evidence_state": fact.get("evidence_state"),
        "valid_until": fact.get("valid_until"),
        "recorded_at": fact.get("recorded_at"),
    }


class FactSurface:
    def __init__(self, store: KnowledgeFactStore, config: Optional[FactSurfaceConfig] = None) -> None:
        self._store = store
        self._cfg = config or FactSurfaceConfig.fromEnv()

    @property
    def enabled(self) -> bool:
        return self._cfg.enabled

    def search(self, query: str, limit: int = 10, agentId: Optional[str] = None) -> List[Dict[str, Any]]:
        """关闸即返回空池——开关只在这里判一次，不交给调用方各自自觉。"""
        if not self._cfg.enabled:
            return []
        corpus = self._store.searchableFacts(agentId=agentId)
        if not corpus:
            return []
        items = [factToItem(f, f["canonical_label"]) for f in corpus]
        ranked = bm25_rank(query, [{"id": it["knowledge_id"],
                                    "content": it["title"] + " " + it["content"]} for it in items],
                           top_k=limit)
        byId = {it["knowledge_id"]: it for it in items}
        hits = []
        for factId, score in ranked:
            item = byId.get(factId)
            if item is None:
                continue
            item["fact_score"] = float(score)
            item["freshness_term"] = self._freshness(item.get("recorded_at"))
            item["confidence_term"] = self._confidence(item)
            hits.append(item)
        return hits

    def rankHits(self, hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """修正项只在开闸态生效；权重全为 0 时必须与纯 BM25 序一致。"""
        return sorted(
            hits,
            key=lambda h: (-(h.get("fact_score", 0.0)
                             + self._cfg.freshnessWeight * h.get("freshness_term", 0.0)
                             + self._cfg.confidenceWeight * h.get("confidence_term", 0.0)),
                           h.get("knowledge_id", "")),
        )

    def _freshness(self, recordedAt: Optional[str]) -> float:
        if not recordedAt:
            return 0.0
        try:
            stamp = datetime.datetime.fromisoformat(str(recordedAt).replace("Z", "+00:00"))
        except ValueError:
            return 0.0
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=datetime.timezone.utc)
        ageDays = max(0.0, (datetime.datetime.now(datetime.timezone.utc) - stamp).total_seconds() / 86400.0)
        return 0.5 ** (ageDays / self._cfg.halfLifeDays)

    @staticmethod
    def _confidence(item: Dict[str, Any]) -> float:
        """无置信按 unevidenced 处理，贡献 0 而不是猜一个中间值（ADR 016 三态纪律）。"""
        value = item.get("confidence")
        if value is None or item.get("evidence_state") != "evidenced":
            return 0.0
        return max(0.0, min(1.0, float(value)))


def mergeIntoLegacy(legacy: List[Dict[str, Any]], facts: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """两池各自有序，按秩交织合并；不重算分数，避免把两套分数域混在一起。"""
    merged: List[Dict[str, Any]] = []
    pool = list(legacy) + list(facts)
    seen: set = set()
    for rank in range(max(len(legacy), len(facts)) + 1):
        for source, bucket in (("narrative", legacy), ("fact", facts)):
            if rank >= len(bucket):
                continue
            item = bucket[rank]
            key = item.get("knowledge_id")
            if key in seen:
                continue
            seen.add(key)
            item = dict(item)
            item.setdefault("record_kind", "narrative")
            merged.append(item)
        if len(merged) >= limit:
            break
    return merged[:limit]


def recordHitsAsInjection(store: KnowledgeFactStore, hits: List[Dict[str, Any]]) -> int:
    """010 的触发点：只有事实类命中参与计数，叙述条目由 019 降级后再统一。"""
    factIds = [h["knowledge_id"] for h in hits if h.get("record_kind") == "fact"]
    if not factIds:
        return 0
    try:
        return store.recordInjection(factIds)
    except LookupError as exc:
        # 计数丢一次不该让检索失败，但必须留下可读痕迹，不能静默
        logger.warning("使用回流计数未写入（事实可能已被取代）: %s", exc)
        return 0
