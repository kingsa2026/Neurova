"""
记忆压缩机制 - 层级压缩、语义压缩、记忆聚合

优化内容:
- 集成 LLM 生成高质量摘要 (替代简单的关键词拼接)
- 改进语义压缩算法 (TF-IDF 相似度替代 Jaccard)
- 优化记忆聚合逻辑 (按时间+类别双维度分组)
"""

import datetime
import logging
import math
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CompressionStrategy(str, Enum):
    """压缩策略"""

    TIER = "tier"  # 层级压缩
    SEMANTIC = "semantic"  # 语义压缩
    AGGREGATION = "aggregation"  # 记忆聚合
    LLM = "llm"  # LLM辅助压缩
    RULE_BASED = "rule_based"  # 规则压缩


@dataclass
class CompressionResult:
    """压缩结果"""

    original_count: int
    compressed_count: int
    removed_count: int
    merged_count: int
    strategy: CompressionStrategy
    duration_ms: float = 0.0
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryGroup:
    """记忆分组"""

    category: str
    time_window: str
    memories: List[Dict[str, Any]]
    similarity_threshold: float = 0.7


class MemoryCompressor:
    """
    记忆压缩器

    提供多种压缩策略：
    1. 层级压缩 - 按重要性和时间分层
    2. 语义压缩 - 基于相似度合并相似记忆
    3. 记忆聚合 - 按时间和类别分组聚合
    4. LLM辅助 - 使用LLM生成高质量摘要
    5. 规则压缩 - 基于规则的简单压缩
    """

    def __init__(
        self,
        storage: Any = None,
        llm_client: Any = None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化记忆压缩器

        Args:
            storage: 存储后端
            llm_client: LLM客户端
            config: 配置字典
        """
        self._storage = storage
        self._llm_client = llm_client
        self._config = config or {}
        self._lock = threading.RLock()

        # 配置参数
        self._similarity_threshold = self._config.get("similarity_threshold", 0.7)
        self._max_memories_per_group = self._config.get("max_memories_per_group", 10)
        self._time_window_hours = self._config.get("time_window_hours", 24)
        self._importance_threshold = self._config.get("importance_threshold", 0.3)
        self._enable_llm_compression = self._config.get("enable_llm_compression", True)

        # 缓存
        self._tfidf_cache: Dict[str, Dict[str, float]] = {}
        self._idf_cache: Dict[str, float] = {}
        self._cache_lock = threading.RLock()

        logger.info("MemoryCompressor initialized")

    def compress(
        self,
        memories: List[Dict[str, Any]],
        strategy: CompressionStrategy = CompressionStrategy.SEMANTIC,
        **kwargs,
    ) -> CompressionResult:
        """
        压缩记忆

        Args:
            memories: 记忆列表
            strategy: 压缩策略
            **kwargs: 策略特定参数

        Returns:
            压缩结果
        """
        start_time = time.time()

        try:
            if strategy == CompressionStrategy.TIER:
                result = self._tier_compression(memories, **kwargs)
            elif strategy == CompressionStrategy.SEMANTIC:
                result = self._semantic_compression(memories, **kwargs)
            elif strategy == CompressionStrategy.AGGREGATION:
                result = self._memory_aggregation(memories, **kwargs)
            elif strategy == CompressionStrategy.LLM:
                result = self._llm_compression(memories, **kwargs)
            elif strategy == CompressionStrategy.RULE_BASED:
                result = self._rule_based_compression(memories, **kwargs)
            else:
                raise ValueError(f"Unknown compression strategy: {strategy}")

            result.duration_ms = (time.time() - start_time) * 1000
            result.strategy = strategy

            logger.info(
                f"Compression completed: {result.original_count} → {result.compressed_count} "
                f"({result.removed_count} removed, {result.merged_count} merged)"
            )

            return result

        except Exception as e:
            logger.error("Compression failed: %s", e)
            return CompressionResult(
                original_count=len(memories),
                compressed_count=len(memories),
                removed_count=0,
                merged_count=0,
                strategy=strategy,
                duration_ms=(time.time() - start_time) * 1000,
                details={"error": str(e)},
            )

    def _get_old_memories(
        self,
        days: int = 30,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        """
        获取旧记忆

        Args:
            days: 天数限制
            limit: 数量限制

        Returns:
            旧记忆列表
        """
        if not self._storage:
            return []

        try:
            return self._storage.get_recent_memories(days=days, limit=limit)
        except Exception as e:
            logger.warning("Failed to get old memories: %s", e)
            return []

    def _tier_compression(
        self,
        memories: List[Dict[str, Any]],
        **kwargs,
    ) -> CompressionResult:
        """
        层级压缩 - 按重要性和时间分层

        Args:
            memories: 记忆列表
            **kwargs: 额外参数

        Returns:
            压缩结果
        """
        original_count = len(memories)

        # 按重要性分层
        high_importance = []
        medium_importance = []
        low_importance = []

        for memory in memories:
            importance = memory.get("importance", 0.5)
            temperature = memory.get("temperature", 0.5)

            # 综合评分
            score = importance * 0.7 + temperature * 0.3

            if score > 0.7:
                high_importance.append(memory)
            elif score > 0.4:
                medium_importance.append(memory)
            else:
                low_importance.append(memory)

        # 低重要性记忆：大幅压缩
        compressed_low = []
        if low_importance:
            # 按时间分组
            time_groups = self._group_by_time(low_importance, hours=self._time_window_hours)
            for group in time_groups.values():
                if len(group) <= 2:
                    compressed_low.extend(group)
                else:
                    # 保留最新的，压缩其他的
                    sorted_group = sorted(
                        group,
                        key=lambda m: m.get("created_at", ""),
                        reverse=True,
                    )
                    compressed_low.append(sorted_group[0])  # 保留最新
                    # 其他的合并为摘要
                    if len(sorted_group) > 1:
                        merged = self._merge_memories(sorted_group[1:])
                        if merged:
                            compressed_low.append(merged)

        # 中等重要性记忆：适度压缩
        compressed_medium = []
        if medium_importance:
            # 按类别分组
            category_groups = defaultdict(list)
            for memory in medium_importance:
                category = memory.get("category", "general")
                category_groups[category].append(memory)

            for category, group in category_groups.items():
                if len(group) <= 3:
                    compressed_medium.extend(group)
                else:
                    # 每3个合并为1个
                    for i in range(0, len(group), 3):
                        chunk = group[i : i + 3]
                        if len(chunk) == 1:
                            compressed_medium.append(chunk[0])
                        else:
                            merged = self._merge_memories(chunk)
                            if merged:
                                compressed_medium.append(merged)

        # 高重要性记忆：保持原样
        compressed_memories = high_importance + compressed_medium + compressed_low

        return CompressionResult(
            original_count=original_count,
            compressed_count=len(compressed_memories),
            removed_count=original_count - len(compressed_memories),
            merged_count=0,
            strategy=CompressionStrategy.TIER,
            details={
                "high_importance": len(high_importance),
                "medium_importance": len(medium_importance),
                "low_importance": len(low_importance),
            },
        )

    def _semantic_compression(
        self,
        memories: List[Dict[str, Any]],
        **kwargs,
    ) -> CompressionResult:
        """
        语义压缩 - 基于相似度合并相似记忆

        Args:
            memories: 记忆列表
            **kwargs: 额外参数

        Returns:
            压缩结果
        """
        original_count = len(memories)
        threshold = kwargs.get("threshold", self._similarity_threshold)

        # 计算所有记忆的TF-IDF
        self._compute_tfidf(memories)

        # 找到相似记忆组
        similarity_groups = self._find_similarity_groups(memories, threshold)

        # 合并相似记忆
        compressed_memories = []
        merged_count = 0

        for group in similarity_groups:
            if len(group) == 1:
                compressed_memories.append(group[0])
            else:
                # 合并组内记忆
                merged = self._merge_memories(group)
                if merged:
                    compressed_memories.append(merged)
                    merged_count += len(group) - 1

        return CompressionResult(
            original_count=original_count,
            compressed_count=len(compressed_memories),
            removed_count=original_count - len(compressed_memories),
            merged_count=merged_count,
            strategy=CompressionStrategy.SEMANTIC,
            details={
                "similarity_threshold": threshold,
                "groups_found": len(similarity_groups),
            },
        )

    def _semantic_compression_locked(
        self,
        memories: List[Dict[str, Any]],
        **kwargs,
    ) -> CompressionResult:
        """
        语义压缩（带锁版本）

        Args:
            memories: 记忆列表
            **kwargs: 额外参数

        Returns:
            压缩结果
        """
        with self._cache_lock:
            return self._semantic_compression(memories, **kwargs)

    def _memory_aggregation(
        self,
        memories: List[Dict[str, Any]],
        **kwargs,
    ) -> CompressionResult:
        """
        记忆聚合 - 按时间和类别分组聚合

        Args:
            memories: 记忆列表
            **kwargs: 额外参数

        Returns:
            压缩结果
        """
        original_count = len(memories)

        # 按类别和时间分组
        groups = self._group_by_category_and_time(memories)

        # 聚合每个组
        compressed_memories = []
        merged_count = 0

        for group in groups:
            if len(group.memories) <= self._max_memories_per_group:
                compressed_memories.extend(group.memories)
            else:
                # 聚合大组
                aggregated = self._aggregate_group(group)
                compressed_memories.extend(aggregated)
                merged_count += len(group.memories) - len(aggregated)

        return CompressionResult(
            original_count=original_count,
            compressed_count=len(compressed_memories),
            removed_count=original_count - len(compressed_memories),
            merged_count=merged_count,
            strategy=CompressionStrategy.AGGREGATION,
            details={
                "groups_created": len(groups),
                "max_memories_per_group": self._max_memories_per_group,
            },
        )

    def _llm_compression(
        self,
        memories: List[Dict[str, Any]],
        **kwargs,
    ) -> CompressionResult:
        """
        LLM辅助压缩 - 使用LLM生成高质量摘要

        Args:
            memories: 记忆列表
            **kwargs: 额外参数

        Returns:
            压缩结果
        """
        original_count = len(memories)

        if not self._llm_client or not self._enable_llm_compression:
            # 降级到规则压缩
            return self._rule_based_compression(memories, **kwargs)

        # 按类别分组
        category_groups = defaultdict(list)
        for memory in memories:
            category = memory.get("category", "general")
            category_groups[category].append(memory)

        compressed_memories = []
        merged_count = 0

        for category, group in category_groups.items():
            if len(group) <= 2:
                compressed_memories.extend(group)
            else:
                # 使用LLM生成摘要
                try:
                    summary = self._generate_llm_summary(group)
                    if summary:
                        # 创建摘要记忆
                        summary_memory = {
                            "id": f"summary_{category}_{int(time.time())}",
                            "content": summary,
                            "category": category,
                            "type": "summary",
                            "importance": 0.8,
                            "temperature": 0.9,
                            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                            "metadata": {
                                "compression": "llm",
                                "original_count": len(group),
                                "original_ids": [m.get("id") for m in group],
                            },
                        }
                        compressed_memories.append(summary_memory)
                        merged_count += len(group) - 1
                    else:
                        # LLM失败，保留原样
                        compressed_memories.extend(group)
                except Exception as e:
                    logger.warning("LLM compression failed for category %s: %s", category, e)
                    compressed_memories.extend(group)

        return CompressionResult(
            original_count=original_count,
            compressed_count=len(compressed_memories),
            removed_count=original_count - len(compressed_memories),
            merged_count=merged_count,
            strategy=CompressionStrategy.LLM,
            details={
                "categories": list(category_groups.keys()),
                "llm_used": True,
            },
        )

    def _rule_based_compression(
        self,
        memories: List[Dict[str, Any]],
        **kwargs,
    ) -> CompressionResult:
        """
        规则压缩 - 基于规则的简单压缩

        Args:
            memories: 记忆列表
            **kwargs: 额外参数

        Returns:
            压缩结果
        """
        original_count = len(memories)

        # 规则1：删除重复内容
        seen_contents = set()
        unique_memories = []
        duplicate_count = 0

        for memory in memories:
            content = memory.get("content", "")
            content_hash = hash(content)

            if content_hash not in seen_contents:
                seen_contents.add(content_hash)
                unique_memories.append(memory)
            else:
                duplicate_count += 1

        # 规则2：合并短记忆
        compressed_memories = []
        short_memories = []

        for memory in unique_memories:
            content = memory.get("content", "")
            if len(content) < 50:  # 短于50字符
                short_memories.append(memory)
            else:
                compressed_memories.append(memory)

        # 合并短记忆
        if short_memories:
            merged_short = self._merge_memories(short_memories)
            if merged_short:
                compressed_memories.append(merged_short)

        return CompressionResult(
            original_count=original_count,
            compressed_count=len(compressed_memories),
            removed_count=original_count - len(compressed_memories),
            merged_count=duplicate_count,
            strategy=CompressionStrategy.RULE_BASED,
            details={
                "duplicates_removed": duplicate_count,
                "short_memories_merged": len(short_memories),
            },
        )

    def _group_by_time(
        self,
        memories: List[Dict[str, Any]],
        hours: int = 24,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        按时间分组

        Args:
            memories: 记忆列表
            hours: 时间窗口（小时）

        Returns:
            时间分组字典
        """
        groups = defaultdict(list)

        for memory in memories:
            created_at = memory.get("created_at", "")
            if created_at:
                try:
                    if isinstance(created_at, str):
                        dt = datetime.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    else:
                        dt = created_at

                    # 计算时间窗口
                    window = dt.replace(
                        hour=(dt.hour // hours) * hours,
                        minute=0,
                        second=0,
                        microsecond=0,
                    )
                    window_key = window.isoformat()
                    groups[window_key].append(memory)
                except Exception:
                    groups["unknown"].append(memory)
            else:
                groups["unknown"].append(memory)

        return dict(groups)

    def _group_by_category_and_time(
        self,
        memories: List[Dict[str, Any]],
    ) -> List[MemoryGroup]:
        """
        按类别和时间分组

        Args:
            memories: 记忆列表

        Returns:
            记忆分组列表
        """
        # 先按类别分组
        category_groups = defaultdict(list)
        for memory in memories:
            category = memory.get("category", "general")
            category_groups[category].append(memory)

        # 再按时间细分
        result = []
        for category, category_memories in category_groups.items():
            time_groups = self._group_by_time(category_memories, hours=self._time_window_hours)

            for time_window, time_memories in time_groups.items():
                result.append(
                    MemoryGroup(
                        category=category,
                        time_window=time_window,
                        memories=time_memories,
                    )
                )

        return result

    def _compute_tfidf(self, memories: List[Dict[str, Any]]) -> None:
        """
        计算TF-IDF

        Args:
            memories: 记忆列表
        """
        with self._cache_lock:
            # 清空缓存
            self._tfidf_cache.clear()
            self._idf_cache.clear()

            # 计算TF
            all_tokens = []
            for memory in memories:
                content = memory.get("content", "")
                tokens = self._tokenize(content)
                all_tokens.extend(tokens)

                # 计算TF
                tf = Counter(tokens)
                total = len(tokens)
                if total > 0:
                    tf_normalized = {token: count / total for token, count in tf.items()}
                else:
                    tf_normalized = {}

                memory_id = memory.get("id", "")
                self._tfidf_cache[memory_id] = tf_normalized

            # 计算IDF
            doc_count = len(memories)
            if doc_count == 0:
                return

            # 统计每个词出现在多少文档中
            doc_freq = Counter()
            for memory in memories:
                memory_id = memory.get("id", "")
                tokens = set(self._tfidf_cache.get(memory_id, {}).keys())
                for token in tokens:
                    doc_freq[token] += 1

            # 计算IDF
            for token, freq in doc_freq.items():
                self._idf_cache[token] = math.log(doc_count / (freq + 1)) + 1

    def _tokenize(self, text: str) -> List[str]:
        """
        分词

        Args:
            text: 输入文本

        Returns:
            词列表
        """
        # 简单分词：按空格和标点分割
        text = text.lower()
        tokens = re.findall(r"\b\w+\b", text)
        return tokens

    def _calculate_tfidf_similarity(
        self,
        memory1: Dict[str, Any],
        memory2: Dict[str, Any],
    ) -> float:
        """
        计算TF-IDF相似度

        Args:
            memory1: 记忆1
            memory2: 记忆2

        Returns:
            相似度分数 (0-1)
        """
        memory1_id = memory1.get("id", "")
        memory2_id = memory2.get("id", "")

        tf1 = self._tfidf_cache.get(memory1_id, {})
        tf2 = self._tfidf_cache.get(memory2_id, {})

        if not tf1 or not tf2:
            return 0.0

        # 计算TF-IDF向量
        all_tokens = set(tf1.keys()) | set(tf2.keys())

        vector1 = []
        vector2 = []

        for token in all_tokens:
            idf = self._idf_cache.get(token, 1.0)
            vector1.append(tf1.get(token, 0.0) * idf)
            vector2.append(tf2.get(token, 0.0) * idf)

        # 计算余弦相似度
        return self._cosine_similarity(vector1, vector2)

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """
        计算余弦相似度

        Args:
            vec1: 向量1
            vec2: 向量2

        Returns:
            相似度分数 (0-1)
        """
        if len(vec1) != len(vec2):
            return 0.0

        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))

        if norm1 == 0 or norm2 == 0:
            return 0.0

        return dot_product / (norm1 * norm2)

    def _find_similarity_groups(
        self,
        memories: List[Dict[str, Any]],
        threshold: float,
    ) -> List[List[Dict[str, Any]]]:
        """
        找到相似记忆组

        Args:
            memories: 记忆列表
            threshold: 相似度阈值

        Returns:
            相似记忆组列表
        """
        n = len(memories)
        visited = [False] * n
        groups = []

        for i in range(n):
            if visited[i]:
                continue

            # BFS找相似记忆
            group = []
            queue = [i]
            visited[i] = True

            while queue:
                idx = queue.pop(0)
                group.append(memories[idx])

                # 找相似记忆
                for j in range(n):
                    if visited[j]:
                        continue

                    similarity = self._calculate_tfidf_similarity(
                        memories[idx],
                        memories[j],
                    )

                    if similarity >= threshold:
                        visited[j] = True
                        queue.append(j)

            groups.append(group)

        return groups

    def _merge_memories(self, memories: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        合并记忆

        Args:
            memories: 记忆列表

        Returns:
            合并后的记忆，如果失败返回None
        """
        if not memories:
            return None

        if len(memories) == 1:
            return memories[0]

        # 尝试LLM合并
        if self._llm_client and self._enable_llm_compression:
            try:
                merged_content = self._generate_llm_merge_summary(memories)
                if merged_content:
                    # 创建合并记忆
                    merged_memory = {
                        "id": f"merged_{int(time.time())}",
                        "content": merged_content,
                        "category": memories[0].get("category", "general"),
                        "type": "merged",
                        "importance": max(m.get("importance", 0.5) for m in memories),
                        "temperature": max(m.get("temperature", 0.5) for m in memories),
                        "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        "metadata": {
                            "compression": "llm_merge",
                            "original_count": len(memories),
                            "original_ids": [m.get("id") for m in memories],
                        },
                    }
                    return merged_memory
            except Exception as e:
                logger.warning("LLM merge failed: %s", e)

        # 降级到规则合并
        return self._rule_based_merge(memories)

    def _rule_based_merge(self, memories: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        规则合并

        Args:
            memories: 记忆列表

        Returns:
            合并后的记忆
        """
        # 提取所有内容
        contents = []
        for memory in memories:
            content = memory.get("content", "")
            if content:
                contents.append(content)

        # 合并内容
        merged_content = " | ".join(contents)

        # 计算平均重要性和温度
        importances = [m.get("importance", 0.5) for m in memories]
        temperatures = [m.get("temperature", 0.5) for m in memories]

        merged_memory = {
            "id": f"merged_{int(time.time())}",
            "content": merged_content,
            "category": memories[0].get("category", "general"),
            "type": "merged",
            "importance": sum(importances) / len(importances),
            "temperature": max(temperatures),
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "metadata": {
                "compression": "rule_merge",
                "original_count": len(memories),
                "original_ids": [m.get("id") for m in memories],
            },
        }

        return merged_memory

    def _generate_llm_summary(self, memories: List[Dict[str, Any]]) -> Optional[str]:
        """
        使用LLM生成摘要

        Args:
            memories: 记忆列表

        Returns:
            摘要文本，如果失败返回None
        """
        if not self._llm_client:
            return None

        try:
            # 准备内容
            contents = []
            for memory in memories:
                content = memory.get("content", "")
                if content:
                    contents.append(content)

            if not contents:
                return None

            # 构建提示
            prompt = f"""请将以下记忆内容压缩为一段简洁的摘要，保留关键信息：

{chr(10).join([f"- {c}" for c in contents])}

要求：
1. 摘要应该简洁明了
2. 保留所有重要信息
3. 去除重复内容
4. 使用中文"""

            # 调用LLM
            response = self._llm_client.generate(prompt)
            return response

        except Exception as e:
            logger.warning("LLM summary generation failed: %s", e)
            return None

    def _generate_rule_summary(self, memories: List[Dict[str, Any]]) -> str:
        """
        使用规则生成摘要

        Args:
            memories: 记忆列表

        Returns:
            摘要文本
        """
        # 提取关键词
        all_tokens = []
        for memory in memories:
            content = memory.get("content", "")
            tokens = self._tokenize(content)
            all_tokens.extend(tokens)

        # 统计词频
        word_freq = Counter(all_tokens)

        # 获取前10个关键词
        keywords = [word for word, _ in word_freq.most_common(10)]

        # 构建摘要
        summary = f"包含 {len(memories)} 条相关记忆，主要涉及：{', '.join(keywords)}"

        return summary

    def _generate_llm_merge_summary(self, memories: List[Dict[str, Any]]) -> Optional[str]:
        """
        使用LLM生成合并摘要

        Args:
            memories: 记忆列表

        Returns:
            合并摘要，如果失败返回None
        """
        if not self._llm_client:
            return None

        try:
            # 准备内容
            contents = []
            for memory in memories:
                content = memory.get("content", "")
                if content:
                    contents.append(content)

            if not contents:
                return None

            # 构建提示
            prompt = f"""请将以下多条记忆合并为一条完整的记忆，保留所有重要信息：

{chr(10).join([f"{i+1}. {c}" for i, c in enumerate(contents)])}

要求：
1. 合并为一条连贯的记忆
2. 保留所有重要信息
3. 去除重复和冗余
4. 使用中文"""

            # 调用LLM
            response = self._llm_client.generate(prompt)
            return response

        except Exception as e:
            logger.warning("LLM merge summary generation failed: %s", e)
            return None

    def _cleanup_compressed(self, original_ids: List[str]) -> None:
        """
        清理被压缩的记忆

        Args:
            original_ids: 原始记忆ID列表
        """
        if not self._storage:
            return

        for memory_id in original_ids:
            try:
                self._storage.delete_memory(memory_id)
            except Exception as e:
                logger.warning("Failed to delete compressed memory %s: %s", memory_id, e)

    def get_stats(self) -> Dict[str, Any]:
        """
        获取压缩器统计信息

        Returns:
            统计信息字典
        """
        with self._cache_lock:
            return {
                "tfidf_cache_size": len(self._tfidf_cache),
                "idf_cache_size": len(self._idf_cache),
                "similarity_threshold": self._similarity_threshold,
                "max_memories_per_group": self._max_memories_per_group,
                "time_window_hours": self._time_window_hours,
                "importance_threshold": self._importance_threshold,
                "enable_llm_compression": self._enable_llm_compression,
            }


# 全局单例
_memory_compressor: Optional[MemoryCompressor] = None
_compressor_lock = threading.Lock()


def get_memory_compressor(
    storage: Any = None,
    llm_client: Any = None,
    config: Optional[Dict[str, Any]] = None,
) -> MemoryCompressor:
    """
    获取全局记忆压缩器单例

    Args:
        storage: 存储后端
        llm_client: LLM客户端
        config: 配置字典

    Returns:
        MemoryCompressor实例
    """
    global _memory_compressor
    if _memory_compressor is None:
        with _compressor_lock:
            if _memory_compressor is None:
                _memory_compressor = MemoryCompressor(
                    storage=storage,
                    llm_client=llm_client,
                    config=config,
                )
    return _memory_compressor


def reset_memory_compressor() -> None:
    """重置全局记忆压缩器（用于测试）"""
    global _memory_compressor
    with _compressor_lock:
        _memory_compressor = None
