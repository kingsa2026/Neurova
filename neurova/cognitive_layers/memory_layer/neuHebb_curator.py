"""
NeuHebbCurator — Neurova Hebb 检索与排序器

深度模块设计：小接口（retrieve / diversity_filter / get_query_embedding），
深实现（余弦相似度检索、多样性过滤、使用频率加权排序）。

支持注入 embed_fn 替换嵌入后端。
"""

from __future__ import annotations

import logging
import math
from typing import Callable, List, Optional, Dict, Any, Tuple

from .neurova_hebb import NeurovaHebb, NeuHebbConfig, NeuHebbMem

logger = logging.getLogger(__name__)


class NeuHebbCurator:
    """
    Neurova Hebb 检索器。

    负责：
    1. 将查询编码为向量
    2. 从 NeuHebbMem 中检索最相关的 NeurovaHebb
    3. 应用多样性过滤去除冗余
    4. 按相关度×使用频率加权排序
    """

    def __init__(
        self,
        config: Optional[NeuHebbConfig] = None,
        embed_fn: Optional[Callable[[str], List[float]]] = None,
        storage: Optional[NeuHebbMem] = None,
    ):
        """
        Args:
            config: 配置
            embed_fn: 文本嵌入函数
            storage: NeuHebbMem 存储实例（不传则自动创建）
        """
        self.config = config or NeuHebbConfig()
        self._embed = embed_fn or self._default_embed
        self._storage = storage

    @property
    def storage(self) -> NeuHebbMem:
        """延迟初始化存储。"""
        if self._storage is None:
            self._storage = NeuHebbMem(self.config)
        return self._storage

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    def get_query_embedding(self, query: str) -> List[float]:
        """将查询文本编码为向量。"""
        return self._embed(query)

    def retrieve(
        self,
        query_embedding: List[float],
        top_k: Optional[int] = None,
    ) -> List[NeurovaHebb]:
        """
        从存储中检索最相关的 NeurovaHebb。

        Args:
            query_embedding: 查询向量
            top_k: 返回数量（默认使用配置值）

        Returns:
            按相关度降序排列的 NeurovaHebb 列表
        """
        top_k = top_k or self.config.top_k
        all_hebbs = self._get_all_hebbs_with_embeddings()

        if not all_hebbs:
            return []

        # 计算相似度
        scored: List[Tuple[float, NeurovaHebb]] = []
        for hebb in all_hebbs:
            if hebb.embedding is None:
                continue
            score = self._cosine_similarity(query_embedding, hebb.embedding)
            scored.append((score, hebb))

        # 按分数降序
        scored.sort(key=lambda x: x[0], reverse=True)

        # 应用多样性过滤
        candidates = [h for _, h in scored[:self.config.max_neurova_hebbs_per_query]]
        filtered = self.diversity_filter(candidates)

        # 限制数量
        result = filtered[:top_k]

        # 更新使用计数
        for hebb in result:
            hebb.touch()

        return result

    def diversity_filter(self, candidates: List[NeurovaHebb]) -> List[NeurovaHebb]:
        """
        基于余弦相似度的多样性过滤。

        顺序选择，跳过与已选项相似度 >= threshold 的候选项。

        Args:
            candidates: 候选列表（需已设置 embedding）

        Returns:
            过滤后的多样列表
        """
        if not candidates:
            return []

        selected: List[NeurovaHebb] = [candidates[0]]

        for candidate in candidates[1:]:
            if candidate.embedding is None:
                continue

            is_diverse = True
            for sel in selected:
                if sel.embedding is None:
                    continue
                sim = self._cosine_similarity(candidate.embedding, sel.embedding)
                if sim >= self.config.diversity_threshold:
                    is_diverse = False
                    break

            if is_diverse:
                selected.append(candidate)

        return selected

    # ── 内部实现 ──────────────────────────────────────────────────────────────

    def _get_all_hebbs_with_embeddings(self) -> List[NeurovaHebb]:
        """获取所有有嵌入的 NeurovaHebb。"""
        all_data = self.storage.get_all()
        result = []
        for doc_hebbs in all_data.values():
            for hebb in doc_hebbs:
                if hebb.embedding is not None:
                    result.append(hebb)
        return result

    @staticmethod
    def _cosine_similarity(a: List[float], b: List[float]) -> float:
        """计算余弦相似度。"""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    @staticmethod
    def _default_embed(text: str) -> List[float]:
        logger.warning("NeuHebbCurator: no embed_fn provided, returning zero vector")
        return [0.0] * 64
