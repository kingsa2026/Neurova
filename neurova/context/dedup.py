from __future__ import annotations

"""
防漂移去重器 - Drift Safe Deduplicator

多阶段去重，保留关键上下文。
"""

import logging
from typing import Dict, List

from neurova.context.pool_models import ContextInput, ContextSource

logger = logging.getLogger(__name__)


class DriftSafeDeduplicator:
    """防漂移去重器 - 多阶段去重，保留关键上下文"""

    def __init__(self, semantic_threshold: float = 0.95):
        self.semantic_threshold = semantic_threshold

    def dedup(self, drops: List[ContextInput], stage: str = "input") -> List[ContextInput]:
        if not drops:
            return []

        stage1 = self._exact_dedup(drops)
        stage2 = self._pattern_dedup(stage1)

        return stage2

    def _exact_dedup(self, drops: List[ContextInput]) -> List[ContextInput]:
        seen_hashes = set()
        result = []

        for drop in drops:
            if drop.hash not in seen_hashes:
                seen_hashes.add(drop.hash)
                result.append(drop)
            else:
                existing_idx = next((i for i, d in enumerate(result) if d.hash == drop.hash), None)
                if existing_idx is not None and drop.priority > result[existing_idx].priority:
                    result[existing_idx] = drop

        return result

    def _pattern_dedup(self, drops: List[ContextInput]) -> List[ContextInput]:
        by_source: Dict[ContextSource, List[ContextInput]] = {}

        for drop in drops:
            if drop.source not in by_source:
                by_source[drop.source] = []
            by_source[drop.source].append(drop)

        result = []
        for source, source_drops in by_source.items():
            deduped = self._dedup_same_source(source_drops)
            result.extend(deduped)

        return result

    def _dedup_same_source(self, drops: List[ContextInput]) -> List[ContextInput]:
        if len(drops) <= 1:
            return drops

        by_hash: Dict[str, List[ContextInput]] = {}
        for drop in drops:
            if drop.hash not in by_hash:
                by_hash[drop.hash] = []
            by_hash[drop.hash].append(drop)

        result = []
        for hash_val, hash_drops in by_hash.items():
            best = max(hash_drops, key=lambda d: d.priority)
            result.append(best)

        return result
