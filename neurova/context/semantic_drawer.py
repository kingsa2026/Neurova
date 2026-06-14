from __future__ import annotations

"""
向量语义匹配取水器 - Semantic Match Drawer

按需取水，支持向量语义匹配和关键词降级匹配。
"""

import hashlib
import logging
import math
import re
from datetime import datetime
from typing import List, Optional

from neurova.context.pool_models import ContextInput, ContextSource

logger = logging.getLogger(__name__)


class SemanticMatchDrawer:
    """向量语义匹配取水器 - 按需取水，不需要预定义需求类型"""

    SOURCE_MULTIPLIERS = {
        ContextSource.USER_INPUT: 1.0,
        ContextSource.CONVERSATION: 0.8,
        ContextSource.MEMORY: 0.3,
        ContextSource.EMOTION: 0.5,
        ContextSource.TOOL_CALL: 0.6,
        ContextSource.SYSTEM_INSTRUCTION: 0.1,
        ContextSource.EXPERIENCE: 0.4,
        ContextSource.REFLECTION: 0.4,
        ContextSource.MULTIMODAL: 0.7,
        ContextSource.DEVELOPER_INSTRUCTION: 0.1,
    }

    WEIGHTS = {
        "match_score": 0.5,
        "freshness": 0.2,
        "priority": 0.2,
        "source_match": 0.1,
    }

    def __init__(self, max_tokens: int = 16000):
        self.max_tokens = max_tokens
        self._vector_store = None

    @property
    def vector_store(self):
        if self._vector_store is None:
            try:
                from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
                self._vector_store = UnifiedVectorStore(backend="auto")
            except ImportError:
                logger.warning("UnifiedVectorStore 不可用，使用简单匹配")
                self._vector_store = False
        return self._vector_store

    def preload_vector_store(self):
        if self._vector_store is None:
            try:
                from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
                self._vector_store = UnifiedVectorStore(backend="auto")
                logger.info("向量存储预加载完成")
            except ImportError:
                logger.warning("UnifiedVectorStore 不可用，使用简单匹配")
                self._vector_store = False

    def draw(self, drops: List[ContextInput], need: str = None) -> List[ContextInput]:
        if not drops:
            return []

        scored_drops = []
        for drop in drops:
            score = self._calculate_score(drop, need)
            scored_drops.append((score, drop))

        scored_drops.sort(key=lambda x: -x[0])

        result = []
        total_tokens = 0

        for score, drop in scored_drops:
            drop_tokens = drop.tokens if drop.tokens > 0 else self._estimate_tokens(drop.content)

            if total_tokens + drop_tokens <= self.max_tokens:
                result.append(drop)
                total_tokens += drop_tokens
            else:
                remaining = self.max_tokens - total_tokens
                if remaining > 100:
                    truncated = self._truncate_drop(drop, remaining)
                    if truncated:
                        result.append(truncated)
                break

        return result

    def _calculate_score(self, drop: ContextInput, need: str = None) -> float:
        match_score = self._calculate_match_score(drop, need) if need else 0.5
        freshness_score = self._calculate_freshness_score(drop)
        priority_score = drop.priority / 100.0
        source_score = self._calculate_source_score(drop, need) if need else 0.5

        total = (
            self.WEIGHTS["match_score"] * match_score
            + self.WEIGHTS["freshness"] * freshness_score
            + self.WEIGHTS["priority"] * priority_score
            + self.WEIGHTS["source_match"] * source_score
        )

        return total

    def _calculate_match_score(self, drop: ContextInput, need: str) -> float:
        if not need:
            return 0.5

        if self.vector_store:
            return self._vector_match_score(drop, need)

        return self._keyword_match_score(drop, need)

    def _vector_match_score(self, drop: ContextInput, need: str) -> float:
        try:
            need_vec = self.vector_store.encode(need)

            drop_text = drop.content
            if drop.tags:
                drop_text += " " + " ".join(drop.tags)
            drop_vec = self.vector_store.encode(drop_text)

            from neurova.cognitive_layers.memory_layer.unified_vector_store import cosine_similarity
            similarity = cosine_similarity(need_vec, drop_vec)

            return (similarity + 1) / 2
        except Exception as e:
            logger.warning("向量匹配失败，降级到关键词匹配: %s", e)
            return self._keyword_match_score(drop, need)

    def _keyword_match_score(self, drop: ContextInput, need: str) -> float:
        need_keywords = [kw.strip() for kw in re.sub(r"[^\w\s]", " ", need).split() if len(kw.strip()) > 1]
        if not need_keywords:
            return 0.5

        tag_matches = sum(1 for kw in need_keywords if any(kw in tag for tag in drop.tags))
        content_matches = sum(1 for kw in need_keywords if kw in drop.content)

        total_keywords = len(need_keywords)
        tag_ratio = tag_matches / total_keywords
        content_ratio = min(content_matches / total_keywords, 1.0)

        return 0.5 * tag_ratio + 0.5 * content_ratio

    def _calculate_freshness_score(self, drop: ContextInput) -> float:
        if not drop.updated_at:
            return 0.5

        age_hours = (datetime.now() - drop.updated_at).total_seconds() / 3600
        freshness = math.exp(-0.1 * age_hours)
        multiplier = self.SOURCE_MULTIPLIERS.get(drop.source, 0.5)

        return freshness * multiplier

    def _calculate_source_score(self, drop: ContextInput, need: str) -> float:
        if not need:
            return 0.5

        source_text = drop.source.value.replace("_", " ")
        need_lower = need.lower()

        if source_text in need_lower:
            return 1.0

        return 0.3

    def _truncate_drop(self, drop: ContextInput, max_tokens: int) -> Optional[ContextInput]:
        drop_tokens = drop.tokens if drop.tokens > 0 else self._estimate_tokens(drop.content)

        if drop_tokens <= max_tokens:
            return drop

        ratio = max_tokens / drop_tokens
        truncated_content = drop.content[: int(len(drop.content) * ratio)]

        return ContextInput(
            source=drop.source,
            content=truncated_content + "...",
            priority=drop.priority,
            metadata=drop.metadata,
            tokens=max_tokens,
            tags=drop.tags,
            hash=hashlib.md5(truncated_content.encode()).hexdigest(),
            created_at=drop.created_at,
            updated_at=drop.updated_at,
        )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        from neurova.context.token_estimator import EstimationStrategy, TokenEstimator
        estimator = TokenEstimator(EstimationStrategy.BALANCED)
        return estimator.estimate(text)
