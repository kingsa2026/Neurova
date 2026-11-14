from __future__ import annotations

"""
防漂移去重器 - Drift Safe Deduplicator

多阶段去重，保留关键上下文。

B12（对照改进项）：语义判重阶段（设计文档 §5.2 高阈值语义去重）。
只在**写入期**由 ContextPool.add_context 调用（`semanticDuplicate`），
视图侧 dedup 仍只有精确+模式两阶段——语义判重不改变视图装配行为。
"""

from neurova.core.logger import get_logger
from typing import Dict, List, Optional, Sequence, Tuple

from neurova.context.pool_models import ContextInput, ContextSource

logger = get_logger(__name__)

#: 语义判重豁免面（设计文档 §5.3 关键上下文）：这些来源不参与语义判重。
_SEMANTIC_EXEMPT_SOURCES = frozenset({
    ContextSource.USER_INPUT,
    ContextSource.SYSTEM_INSTRUCTION,
    ContextSource.DEVELOPER_INSTRUCTION,
})

#: 高优先级豁免线（设计文档 §5.3：priority >= 90 不去重）。
_SEMANTIC_PRIORITY_FLOOR = 90

#: 过短文本不参与语义判重（向量对短串不可靠，易误判）。
_SEMANTIC_MIN_CHARS = 20


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

    def semanticDuplicate(
        self,
        incoming: ContextInput,
        residents: Sequence[ContextInput],
        *,
        probe,
        threshold: float,
    ) -> Tuple[Optional[ContextInput], float]:
        """B12：写入期语义判重（纯判定，无 I/O）。

        probe(text_a, text_b) -> float | None：相似度探针（None = 向量面
        不可用，该对放行——fail-open，保守纪律）。

        豁免面（设计文档 §5.3 关键上下文）：高优先级（≥90）、用户输入、
        系统/开发者指令、过短文本。同 source 由调用方保证（只喂同源 residents）。

        Returns:
            (匹配的既有条目, 相似度) 或 (None, 0.0)＝放行。
        """
        if probe is None or threshold <= 0 or incoming is None:
            return None, 0.0
        if getattr(incoming, "source", None) in _SEMANTIC_EXEMPT_SOURCES:
            return None, 0.0
        if (getattr(incoming, "priority", 0) or 0) >= _SEMANTIC_PRIORITY_FLOOR:
            return None, 0.0
        incoming_text = str(getattr(incoming, "content", "") or "").strip()
        if len(incoming_text) < _SEMANTIC_MIN_CHARS:
            return None, 0.0

        incoming_hash = getattr(incoming, "hash", None)
        best: Optional[ContextInput] = None
        best_sim = 0.0
        for resident in residents or []:
            if resident is None:
                continue
            if getattr(resident, "hash", None) == incoming_hash:
                continue  # 精确重复归 stage1 管
            text = str(getattr(resident, "content", "") or "").strip()
            if len(text) < _SEMANTIC_MIN_CHARS:
                continue
            similarity = probe(incoming_text, text)
            if similarity is None:
                continue  # 探针不可用：该对放行
            if similarity >= threshold and similarity > best_sim:
                best, best_sim = resident, float(similarity)
        return best, best_sim

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
