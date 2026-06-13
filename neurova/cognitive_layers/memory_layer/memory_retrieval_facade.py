"""
MemoryRetrievalFacade - 统一记忆检索门面

统一 6 通道检索 + NeRF 融合 + 肌肉记忆 + 工具记忆

设计模式：
- Facade 模式：简化接口，内部协调
- 4级降级：完整→传统→简单→空
- LRU+TTL 缓存：避免重复计算
- 并行检索：6通道+肌肉记忆并行
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ────── 数据模型 ──────


@dataclass
class UnifiedRecallResult:
    """统一检索结果"""

    memories: List[Dict[str, Any]]  # 统一格式的记忆列表
    scores: Dict[str, float]  # 各通道/来源的分数
    metadata: Dict[str, Any]  # 元数据（意图、耗时等）
    source: str  # 主要来源（recall/nerf/muscle/tool/fallback）
    confidence: float  # 整体置信度

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "memories": self.memories,
            "scores": self.scores,
            "metadata": self.metadata,
            "source": self.source,
            "confidence": self.confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UnifiedRecallResult":
        """从字典创建"""
        return cls(
            memories=data.get("memories", []),
            scores=data.get("scores", {}),
            metadata=data.get("metadata", {}),
            source=data.get("source", "unknown"),
            confidence=data.get("confidence", 0.0),
        )


# ────── 简单 LRU+TTL 缓存 ──────


class TTLCache:
    """简单的 LRU+TTL 缓存"""

    def __init__(self, maxsize: int = 1000, ttl: int = 300):
        """
        Args:
            maxsize: 最大缓存条目数
            ttl: 缓存过期时间（秒）
        """
        self._maxsize = maxsize
        self._ttl = ttl
        self._cache: Dict[str, Tuple[Any, float]] = {}
        self._access_times: Dict[str, float] = {}

    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self._ttl:
                # 更新访问时间
                self._access_times[key] = time.time()
                return value
            else:
                # 过期，删除
                del self._cache[key]
                del self._access_times[key]
        return None

    def set(self, key: str, value: Any):
        """设置缓存值"""
        # 检查容量
        if len(self._cache) >= self._maxsize:
            # 淘汰最久未访问的条目
            oldest_key = min(self._access_times, key=lambda k: self._access_times[k])
            del self._cache[oldest_key]
            del self._access_times[oldest_key]

        # 添加新条目
        self._cache[key] = (value, time.time())
        self._access_times[key] = time.time()

    def clear(self):
        """清空缓存"""
        self._cache.clear()
        self._access_times.clear()

    def size(self) -> int:
        """缓存大小"""
        return len(self._cache)


# ────── MemoryRetrievalFacade ──────


class MemoryRetrievalFacade:
    """统一记忆检索门面

    协调 NeurovaRecallEngine、VolumeRenderer、MuscleMemory、ToolMemoryIntegration

    使用方式：
        facade = MemoryRetrievalFacade(...)
        result = facade.retrieve("what happened yesterday")
        # result.memories 是统一格式的记忆列表
    """

    def __init__(
        self,
        recall_engine=None,
        volume_renderer=None,
        muscle_memory=None,
        tool_memory=None,
        intent_detector=None,
        use_nerf_fusion: bool = True,
        cache_ttl: int = 300,
        max_workers: int = 4,
        **kwargs,
    ):
        """
        Args:
            recall_engine: NeurovaRecallEngine 实例
            volume_renderer: VolumeRenderer 实例
            muscle_memory: MuscleMemory 实例
            tool_memory: ToolMemoryIntegration 实例
            intent_detector: QueryIntentDetector 实例
            use_nerf_fusion: 是否使用 NeRF 融合
            cache_ttl: 缓存过期时间（秒）
            max_workers: 并行线程数
        """
        # 依赖注入（延迟导入避免循环依赖）
        self._recall_engine = recall_engine
        self._volume_renderer = volume_renderer
        self._muscle_memory = muscle_memory
        self._tool_memory = tool_memory
        self._intent_detector = intent_detector
        self._use_nerf_fusion = use_nerf_fusion

        # 缓存
        self._result_cache = TTLCache(maxsize=1000, ttl=cache_ttl)
        self._channel_cache = TTLCache(maxsize=500, ttl=cache_ttl // 2)

        # 并行线程池
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

        # 统计
        self._stats = {
            "total_requests": 0,
            "cache_hits": 0,
            "fallback_count": 0,
            "avg_latency_ms": 0.0,
        }

        logger.info(
            "MemoryRetrievalFacade initialized (nerf=%s, cache_ttl=%ds)",
            use_nerf_fusion,
            cache_ttl,
        )

    # ══════════════════════════════════════════════════════════════
    # 公共接口
    # ══════════════════════════════════════════════════════════════

    def retrieve(
        self,
        query: str,
        intent=None,
        limit: int = 10,
        use_cache: bool = True,
    ) -> UnifiedRecallResult:
        """统一检索入口 — 自动选择最佳检索策略

        Args:
            query: 查询文本
            intent: 查询意图（可选，自动检测）
            limit: 返回结果数量
            use_cache: 是否使用缓存

        Returns:
            UnifiedRecallResult: 统一检索结果
        """
        start_time = time.time()
        self._stats["total_requests"] += 1

        # 1. 检查缓存
        if use_cache:
            cache_key = f"{query}:{intent}:{limit}"
            cached = self._result_cache.get(cache_key)
            if cached is not None:
                self._stats["cache_hits"] += 1
                return cached

        # 2. 执行检索（4级降级）
        result = self._retrieve_with_fallback(query, intent, limit)

        # 3. 缓存结果
        if use_cache:
            cache_key = f"{query}:{intent}:{limit}"
            self._result_cache.set(cache_key, result)

        # 4. 更新统计
        latency_ms = (time.time() - start_time) * 1000
        self._update_stats(latency_ms)

        return result

    def match_tool(self, user_input: str) -> UnifiedRecallResult:
        """工具记忆匹配 — 用于工具选择决策

        Args:
            user_input: 用户输入

        Returns:
            UnifiedRecallResult: 工具记忆匹配结果
        """
        try:
            # 使用工具记忆集成
            if self._tool_memory:
                decision, result = self._tool_memory.check_tool_memory(user_input)
                if decision != "do_not_execute" and result:
                    return UnifiedRecallResult(
                        memories=[result],
                        scores={"tool_memory": 0.9},
                        metadata={"decision": decision},
                        source="tool_memory",
                        confidence=0.9,
                    )

            # 降级到肌肉记忆
            if self._muscle_memory:
                muscle_results = self._muscle_memory.match_by_query(user_input, top_k=5)
                if muscle_results:
                    memories = []
                    scores = {}
                    for item, confidence in muscle_results:
                        memories.append(
                            {
                                "id": item.id,
                                "tool_name": item.tool_name,
                                "parameters": item.parameters,
                                "result_summary": item.result_summary,
                                "level": item.level.value,
                                "confidence": confidence,
                            }
                        )
                        scores[item.tool_name] = confidence

                    return UnifiedRecallResult(
                        memories=memories,
                        scores=scores,
                        metadata={"match_count": len(memories)},
                        source="muscle_memory",
                        confidence=max(scores.values()) if scores else 0.0,
                    )

            # 返回空结果
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={},
                source="none",
                confidence=0.0,
            )

        except Exception as e:
            logger.warning("Tool memory matching failed: %s", e)
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"error": str(e)},
                source="error",
                confidence=0.0,
            )

    def get_related_memories(
        self,
        memory_id: str,
        max_depth: int = 2,
        limit: int = 10,
    ) -> UnifiedRecallResult:
        """获取关联记忆 — 基于图谱关系

        Args:
            memory_id: 记忆ID
            max_depth: 最大遍历深度
            limit: 返回结果数量

        Returns:
            UnifiedRecallResult: 关联记忆结果
        """
        try:
            # 使用图谱通道检索
            if self._recall_engine and hasattr(self._recall_engine, "_channels"):
                graph_channel = self._recall_engine._channels.get("graph")
                if graph_channel:
                    # 获取关联节点
                    related_nodes = graph_channel.bfs(memory_id, max_depth=max_depth)
                    memories = []
                    for node in related_nodes[:limit]:
                        if hasattr(node, "node_type") and node.node_type.value == "MEMORY":
                            memories.append(
                                {
                                    "id": node.node_id,
                                    "content": node.label,
                                    "score": node.weight,
                                    "source": "graph",
                                }
                            )

                    return UnifiedRecallResult(
                        memories=memories,
                        scores={"graph": 1.0},
                        metadata={"memory_id": memory_id, "max_depth": max_depth},
                        source="graph",
                        confidence=0.8 if memories else 0.0,
                    )

            # 降级：返回空结果
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"memory_id": memory_id},
                source="fallback",
                confidence=0.0,
            )

        except Exception as e:
            logger.warning("Get related memories failed: %s", e)
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"error": str(e)},
                source="error",
                confidence=0.0,
            )

    def search_by_emotion(
        self,
        emotion: str,
        limit: int = 10,
    ) -> UnifiedRecallResult:
        """按情感检索 — 情感维度检索

        Args:
            emotion: 情感标签
            limit: 返回结果数量

        Returns:
            UnifiedRecallResult: 情感检索结果
        """
        try:
            # 使用情感通道检索
            if self._recall_engine and hasattr(self._recall_engine, "_channels"):
                emotion_channel = self._recall_engine._channels.get("emotion")
                if emotion_channel:
                    # 检索情感匹配的记忆
                    results = emotion_channel.search(emotion, limit=limit)
                    memories = []
                    scores = {}
                    for r in results:
                        memories.append(
                            {
                                "id": r.get("memory_id"),
                                "content": r.get("content"),
                                "score": r.get("score", 0.0),
                                "emotion": emotion,
                            }
                        )
                        scores["emotion"] = r.get("score", 0.0)

                    return UnifiedRecallResult(
                        memories=memories,
                        scores=scores,
                        metadata={"emotion": emotion},
                        source="emotion",
                        confidence=max(scores.values()) if scores else 0.0,
                    )

            # 降级：返回空结果
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"emotion": emotion},
                source="fallback",
                confidence=0.0,
            )

        except Exception as e:
            logger.warning("Search by emotion failed: %s", e)
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"error": str(e)},
                source="error",
                confidence=0.0,
            )

    # ══════════════════════════════════════════════════════════════
    # 内部方法
    # ══════════════════════════════════════════════════════════════

    def _retrieve_with_fallback(
        self,
        query: str,
        intent,
        limit: int,
    ) -> UnifiedRecallResult:
        """4级降级检索

        Level 0: 完整功能（NeRF + 6通道 + 肌肉记忆）
        Level 1: 传统融合（加权求和 + 6通道 + 肌肉记忆）
        Level 2: 简单检索（文本通道 + 关键词匹配）
        Level 3: 返回空结果（记录错误日志）
        """
        # Level 0: 完整功能
        try:
            return self._retrieve_full(query, intent, limit)
        except Exception as e:
            logger.warning("Level 0 (full) failed: %s", e)

        # Level 1: 传统融合
        try:
            return self._retrieve_weighted(query, intent, limit)
        except Exception as e:
            logger.warning("Level 1 (weighted) failed: %s", e)

        # Level 2: 简单检索
        try:
            return self._retrieve_simple(query, limit)
        except Exception as e:
            logger.warning("Level 2 (simple) failed: %s", e)

        # Level 3: 返回空结果
        self._stats["fallback_count"] += 1
        logger.error("All retrieval levels failed for query: %s", query[:50])
        return UnifiedRecallResult(
            memories=[],
            scores={},
            metadata={"error": "all_levels_failed", "query": query[:100]},
            source="fallback",
            confidence=0.0,
        )

    def _retrieve_full(
        self,
        query: str,
        intent,
        limit: int,
    ) -> UnifiedRecallResult:
        """Level 0: 完整功能（NeRF + 6通道 + 肌肉记忆）"""
        start_time = time.time()

        # 1. 意图检测（如果未提供）
        if intent is None and self._intent_detector:
            intent = self._intent_detector.detect(query)

        # 2. 并行检索（6通道 + 肌肉记忆）
        with self._executor:
            # 通道检索
            channel_future = self._executor.submit(
                self._retrieve_channels, query, intent
            )
            # 肌肉记忆检索
            muscle_future = self._executor.submit(
                self._retrieve_muscle_memory, query, limit
            )

            # 等待结果
            channel_results = channel_future.result()
            muscle_results = muscle_future.result()

        # 3. NeRF融合
        if self._use_nerf_fusion and self._volume_renderer:
            try:
                rendered = self._volume_renderer.render(
                    channel_results,
                    intent.value if intent else "unknown",
                    limit,
                )
                memories = self._rendered_to_dict(rendered)
                source = "nerf"
            except Exception as e:
                logger.warning("NeRF fusion failed, falling back to weighted: %s", e)
                memories = self._weighted_merge(channel_results, intent, limit)
                source = "weighted"
        else:
            # 传统加权求和
            memories = self._weighted_merge(channel_results, intent, limit)
            source = "weighted"

        # 4. 合并肌肉记忆结果
        memories = self._merge_muscle_memories(memories, muscle_results)

        # 5. 提取分数
        scores = self._extract_scores(channel_results, muscle_results)

        # 6. 计算置信度
        confidence = self._calculate_confidence(memories)

        latency_ms = (time.time() - start_time) * 1000

        return UnifiedRecallResult(
            memories=memories[:limit],
            scores=scores,
            metadata={
                "intent": intent.value if intent else "unknown",
                "fusion_mode": source,
                "latency_ms": latency_ms,
                "channel_count": len(channel_results),
                "muscle_count": len(muscle_results),
            },
            source=source,
            confidence=confidence,
        )

    def _retrieve_weighted(
        self,
        query: str,
        intent,
        limit: int,
    ) -> UnifiedRecallResult:
        """Level 1: 传统融合（加权求和 + 6通道 + 肌肉记忆）"""
        start_time = time.time()

        # 1. 意图检测
        if intent is None and self._intent_detector:
            intent = self._intent_detector.detect(query)

        # 2. 通道检索
        channel_results = self._retrieve_channels(query, intent)

        # 3. 传统加权求和
        memories = self._weighted_merge(channel_results, intent, limit)

        # 4. 肌肉记忆检索
        muscle_results = self._retrieve_muscle_memory(query, limit)
        memories = self._merge_muscle_memories(memories, muscle_results)

        # 5. 提取分数和置信度
        scores = self._extract_scores(channel_results, muscle_results)
        confidence = self._calculate_confidence(memories)

        latency_ms = (time.time() - start_time) * 1000

        return UnifiedRecallResult(
            memories=memories[:limit],
            scores=scores,
            metadata={
                "intent": intent.value if intent else "unknown",
                "fusion_mode": "weighted",
                "latency_ms": latency_ms,
            },
            source="weighted",
            confidence=confidence,
        )

    def _retrieve_simple(self, query: str, limit: int) -> UnifiedRecallResult:
        """Level 2: 简单检索（文本通道 + 关键词匹配）"""
        start_time = time.time()

        # 简单文本搜索
        memories = []
        if self._recall_engine and hasattr(self._recall_engine, "_channels"):
            text_channel = self._recall_engine._channels.get("text")
            if text_channel:
                results = text_channel.search(query, limit=limit)
                for r in results:
                    memories.append(
                        {
                            "id": r.get("memory_id"),
                            "content": r.get("content"),
                            "score": r.get("score", 0.0),
                            "source": "text",
                        }
                    )

        latency_ms = (time.time() - start_time) * 1000

        return UnifiedRecallResult(
            memories=memories[:limit],
            scores={"text": 0.5} if memories else {},
            metadata={"fusion_mode": "simple", "latency_ms": latency_ms},
            source="simple",
            confidence=0.5 if memories else 0.0,
        )

    def _retrieve_channels(self, query: str, intent) -> Dict[str, List]:
        """检索6个通道"""
        cache_key = f"{query}:{intent}"
        cached = self._channel_cache.get(cache_key)
        if cached is not None:
            return cached

        if not self._recall_engine or not hasattr(self._recall_engine, "_retrieve_channels"):
            return {
                "temperature": [],
                "text": [],
                "category": [],
                "graph": [],
                "emotion": [],
                "voice": [],
            }

        try:
            results = self._recall_engine._retrieve_channels(query, intent)
            self._channel_cache.set(cache_key, results)
            return results
        except Exception as e:
            logger.warning("Channel retrieval failed: %s", e)
            return {
                "temperature": [],
                "text": [],
                "category": [],
                "graph": [],
                "emotion": [],
                "voice": [],
            }

    def _retrieve_muscle_memory(self, query: str, limit: int) -> List[Tuple]:
        """检索肌肉记忆"""
        if not self._muscle_memory:
            return []

        try:
            return self._muscle_memory.match_by_query(query, top_k=limit)
        except Exception as e:
            logger.warning("Muscle memory retrieval failed: %s", e)
            return []

    def _rendered_to_dict(self, rendered_memories: List) -> List[Dict[str, Any]]:
        """将 RenderedMemory 转换为字典"""
        result = []
        for rm in rendered_memories:
            result.append(
                {
                    "id": rm.memory_id,
                    "content": rm.content,
                    "score": rm.score,
                    "channel_scores": rm.channel_scores,
                    "metadata": rm.metadata,
                    "source": "nerf",
                }
            )
        return result

    def _weighted_merge(
        self,
        channel_results: Dict[str, List],
        intent,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """传统加权求和融合"""
        # 通道权重（基于意图）
        channel_weights = self._get_channel_weights(intent)

        # 合并所有通道的记忆
        memory_scores: Dict[str, float] = {}
        memory_data: Dict[str, Dict] = {}

        for channel_name, memories in channel_results.items():
            weight = channel_weights.get(channel_name, 0.1)
            for memory in memories:
                memory_id = memory.get("memory_id") or memory.get("id")
                if not memory_id:
                    continue

                # 计算加权分数
                raw_score = memory.get("raw_score") or memory.get("score", 0.0)
                weighted_score = raw_score * weight

                if memory_id in memory_scores:
                    memory_scores[memory_id] += weighted_score
                else:
                    memory_scores[memory_id] = weighted_score
                    memory_data[memory_id] = memory

        # 按分数排序
        sorted_ids = sorted(memory_scores.keys(), key=lambda x: memory_scores[x], reverse=True)

        # 构建结果
        result = []
        for memory_id in sorted_ids[:limit]:
            memory = memory_data[memory_id].copy()
            memory["score"] = memory_scores[memory_id]
            memory["source"] = "weighted"
            result.append(memory)

        return result

    def _merge_muscle_memories(
        self,
        memories: List[Dict],
        muscle_results: List[Tuple],
    ) -> List[Dict[str, Any]]:
        """合并肌肉记忆结果"""
        if not muscle_results:
            return memories

        # 肌肉记忆结果置顶
        muscle_memories = []
        for item, confidence in muscle_results:
            muscle_memories.append(
                {
                    "id": item.id,
                    "tool_name": item.tool_name,
                    "parameters": item.parameters,
                    "result_summary": item.result_summary,
                    "level": item.level.value,
                    "confidence": confidence,
                    "source": "muscle_memory",
                    "score": confidence,
                }
            )

        # 肌肉记忆在前，原始事实在后
        return muscle_memories + memories

    def _extract_scores(
        self,
        channel_results: Dict[str, List],
        muscle_results: List[Tuple],
    ) -> Dict[str, float]:
        """提取各通道分数"""
        scores = {}

        # 通道平均分数
        for channel_name, memories in channel_results.items():
            if memories:
                avg_score = sum(m.get("raw_score", 0.0) for m in memories) / len(memories)
                scores[channel_name] = avg_score

        # 肌肉记忆分数
        if muscle_results:
            scores["muscle_memory"] = max(c for _, c in muscle_results)

        return scores

    def _calculate_confidence(self, memories: List[Dict]) -> float:
        """计算整体置信度"""
        if not memories:
            return 0.0

        # 基于分数和来源计算
        total_score = 0.0
        for memory in memories:
            score = memory.get("score", 0.0)
            source = memory.get("source", "unknown")

            # 不同来源的权重
            if source == "muscle_memory":
                total_score += score * 1.5  # 肌肉记忆加权
            elif source == "nerf":
                total_score += score * 1.2  # NeRF融合加权
            else:
                total_score += score

        # 平均分
        avg_score = total_score / len(memories)

        # 归一化到 [0, 1]
        return min(1.0, max(0.0, avg_score))

    def _get_channel_weights(self, intent) -> Dict[str, float]:
        """获取通道权重（基于意图）"""
        # 默认权重
        default_weights = {
            "temperature": 0.2,
            "text": 0.3,
            "category": 0.15,
            "graph": 0.15,
            "emotion": 0.1,
            "voice": 0.1,
        }

        # 基于意图调整权重
        if intent:
            intent_value = intent.value if hasattr(intent, "value") else str(intent)
            if intent_value == "TEMPORAL":
                default_weights["temperature"] = 0.4
                default_weights["text"] = 0.2
            elif intent_value == "FACTUAL":
                default_weights["text"] = 0.5
                default_weights["category"] = 0.2
            elif intent_value == "CAUSAL":
                default_weights["graph"] = 0.4
                default_weights["text"] = 0.3
            elif intent_value == "COMPARATIVE":
                default_weights["category"] = 0.3
                default_weights["text"] = 0.3
            elif intent_value == "EXPLORATORY":
                default_weights["graph"] = 0.3
                default_weights["emotion"] = 0.2

        return default_weights

    def _update_stats(self, latency_ms: float):
        """更新统计信息"""
        # 更新平均延迟（指数移动平均）
        alpha = 0.1
        self._stats["avg_latency_ms"] = (
            alpha * latency_ms + (1 - alpha) * self._stats["avg_latency_ms"]
        )

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()


# ────── 单例工厂 ──────


_facade_instance: Optional[MemoryRetrievalFacade] = None


def get_memory_retrieval_facade(
    recall_engine=None,
    volume_renderer=None,
    muscle_memory=None,
    tool_memory=None,
    intent_detector=None,
    **kwargs,
) -> MemoryRetrievalFacade:
    """获取 MemoryRetrievalFacade 单例实例

    如果实例不存在，使用提供的组件创建新实例。
    如果实例已存在，忽略参数直接返回现有实例。
    """
    global _facade_instance
    if _facade_instance is None:
        # 延迟导入避免循环依赖
        try:
            from neurova.cognitive_layers.memory_layer.neurova_recall import (
                NeurovaRecallEngine,
            )
            from neurova.cognitive_layers.memory_layer.volume_renderer import (
                VolumeRenderer,
            )
            from neurova.cognitive_layers.memory_layer.muscle_memory import (
                MuscleMemory,
            )
            from neurova.cognitive_layers.memory_layer.tool_memory_integration import (
                ToolMemoryIntegration,
            )
            from neurova.cognitive_layers.memory_layer.neurova_recall import (
                QueryIntentDetector,
            )

            # 使用默认组件（如果未提供）
            if recall_engine is None:
                recall_engine = NeurovaRecallEngine()
            if volume_renderer is None:
                volume_renderer = VolumeRenderer()
            if muscle_memory is None:
                muscle_memory = MuscleMemory()
            if tool_memory is None:
                tool_memory = ToolMemoryIntegration()
            if intent_detector is None:
                intent_detector = QueryIntentDetector()

        except ImportError as e:
            logger.warning("Failed to import default components: %s", e)
            # 使用 Mock 对象
            if recall_engine is None:
                recall_engine = MagicMock()
            if volume_renderer is None:
                volume_renderer = MagicMock()
            if muscle_memory is None:
                muscle_memory = MagicMock()
            if tool_memory is None:
                tool_memory = MagicMock()
            if intent_detector is None:
                intent_detector = MagicMock()

        _facade_instance = MemoryRetrievalFacade(
            recall_engine=recall_engine,
            volume_renderer=volume_renderer,
            muscle_memory=muscle_memory,
            tool_memory=tool_memory,
            intent_detector=intent_detector,
            **kwargs,
        )

    return _facade_instance


def reset_memory_retrieval_facade():
    """重置单例实例（用于测试）"""
    global _facade_instance
    _facade_instance = None