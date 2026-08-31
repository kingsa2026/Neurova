from __future__ import annotations

"""
向量语义匹配取水器 - Semantic Match Drawer

按需取水，支持向量语义匹配和关键词降级匹配。
"""

import hashlib
from neurova.core.logger import get_logger
import math
import re
from datetime import datetime
from typing import List, Optional

from neurova.context.pool_models import ContextInput, ContextSource

logger = get_logger(__name__)


class SemanticMatchDrawer:
    """向量语义匹配取水器 - 按需取水，不需要预定义需求类型"""

    SOURCE_MULTIPLIERS = {
        ContextSource.USER_INPUT: 1.0,
        ContextSource.SUMMARY: 0.9,  # P1-1③：折叠摘要高价值
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

    # [按需调取] 相关性门槛：match_score 低于此值的归档不调入视图。
    # 全路径统一刻度（见 _calculate_match_score）：0.5 = 不相关基线，
    # 实测相关内容 ≥0.64 → 门槛 0.55 取空隙中点，双向留余量。
    # 仅在 need 非空时生效。
    RELEVANCE_FLOOR = 0.55

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

        # [按需调取] 相关性门槛：need 存在时，与查询无关的归档整条排除
        #（留在池中，token 只花在相关内容上）；刻度全路径统一（0.5 基线）
        threshold_active = bool(need)

        def _relevant(d: ContextInput) -> bool:
            return (not threshold_active) or self._calculate_match_score(d, need) >= self.RELEVANCE_FLOOR

        conv_items = [
            (i, d) for i, d in enumerate(drops) if d.source == ContextSource.CONVERSATION and _relevant(d)
        ]
        non_conv_items = [d for d in drops if d.source != ContextSource.CONVERSATION and _relevant(d)]

        scored_non_conv = []
        for drop in non_conv_items:
            score = self._calculate_score(drop, need)
            scored_non_conv.append((score, drop))
        scored_non_conv.sort(key=lambda x: -x[0])

        result_by_pos = {}
        for idx, (orig_pos, item) in enumerate(conv_items):
            result_by_pos[orig_pos] = item

        non_conv_idx = 0
        for pos in range(len(drops)):
            if pos in result_by_pos:
                continue
            if non_conv_idx < len(scored_non_conv):
                _, item = scored_non_conv[non_conv_idx]
                result_by_pos[pos] = item
                non_conv_idx += 1

        # [按需调取] 整条选取：分数只决定"取不取"，绝不切片截断内容
        #（归档无损，视图层超预算的条目整条跳过，留在池中等待后续调取）
        selected = []
        total_tokens = 0
        for pos in range(len(drops)):
            if pos not in result_by_pos:
                continue
            drop = result_by_pos[pos]
            drop_tokens = drop.tokens if drop.tokens > 0 else self._estimate_tokens(drop.content)

            if total_tokens + drop_tokens <= self.max_tokens:
                selected.append(drop)
                total_tokens += drop_tokens
            # 超预算：整条跳过并继续尝试更小的条目（不截断内容、不中断选取）

        # [缓存稳定] 最终顺序按 created_at 稳定排序：
        # 同一批被调取的条目在不同请求中保持相同相对位置，保住 LLM 前缀缓存
        selected.sort(key=lambda d: d.created_at or datetime.min)
        return selected

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
        """匹配得分，全路径统一刻度：0.5 = 不相关基线，1.0 = 强相关。

        向量路径返回 (cosine+1)/2；关键词路径原始分 ∈[0,1]（0=无匹配），
        归一化为 0.5 + kw/2 后与向量刻度对齐——相关性门槛因此可以全路径统一，
        不受"向量库存在但运行时降级"的刻度错配影响（如测试污染 sys.modules）。
        """
        if not need:
            return 0.5

        if self.vector_store:
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

        return 0.5 + self._keyword_match_score(drop, need) / 2

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

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        from neurova.context.token_estimator import EstimationStrategy, TokenEstimator
        estimator = TokenEstimator(EstimationStrategy.BALANCED)
        return estimator.estimate(text)
