"""
Enhanced Memory Retrieval System - 增强版记忆检索系统

模拟人类回忆机制的多层级检索系统：
1. 即时激活（基于当前上下文）
2. 关联扩散（语义网络传播）
3. 情感共鸣（情感匹配增强）
4. 重要性加权（记忆强度 + 温度）
5. 时间衰减（近期记忆优先）
"""

from __future__ import annotations

import datetime
from neurova.core.logger import get_logger
import math
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


class ActivationType(str, Enum):
    """激活类型"""

    CONTEXT = "context"  # 上下文激活
    SEMANTIC = "semantic"  # 语义激活
    EMOTIONAL = "emotional"  # 情感激活
    TEMPORAL = "temporal"  # 时间激活
    FREQUENCY = "frequency"  # 频率激活
    SPREAD = "spread"  # 扩散激活


@dataclass
class MemoryActivation:
    """记忆激活模型

    跟踪记忆的激活状态，支持多种激活源和时间衰减。
    """

    memory_id: str
    activation_level: float = 0.0  # 激活水平 (0-1)
    activation_sources: Dict[str, float] = field(default_factory=dict)  # 激活源 -> 贡献值
    last_activated: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))
    decay_rate: float = 0.1  # 衰减率 (每小时)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def activate(self, source: str, strength: float, timestamp: Optional[datetime.datetime] = None) -> None:
        """激活记忆

        Args:
            source: 激活源类型
            strength: 激活强度 (0-1)
            timestamp: 激活时间戳
        """
        if timestamp is None:
            timestamp = datetime.datetime.now(datetime.timezone.utc)

        # 更新激活源
        self.activation_sources[source] = min(1.0, strength)

        # 计算总激活水平（所有源的加权平均）
        if self.activation_sources:
            weights = {
                ActivationType.CONTEXT.value: 1.0,
                ActivationType.SEMANTIC.value: 0.9,
                ActivationType.EMOTIONAL.value: 0.8,
                ActivationType.TEMPORAL.value: 0.7,
                ActivationType.FREQUENCY.value: 0.6,
                ActivationType.SPREAD.value: 0.5,
            }

            total_weight = 0.0
            weighted_sum = 0.0
            for src, val in self.activation_sources.items():
                w = weights.get(src, 0.5)
                weighted_sum += val * w
                total_weight += w

            self.activation_level = weighted_sum / total_weight if total_weight > 0 else 0.0

        self.last_activated = timestamp
        self.metadata["last_source"] = source

    def decay(self, current_time: Optional[datetime.datetime] = None) -> float:
        """应用时间衰减

        Args:
            current_time: 当前时间

        Returns:
            衰减后的激活水平
        """
        if current_time is None:
            current_time = datetime.datetime.now(datetime.timezone.utc)

        # 计算时间差（小时）
        time_diff = (current_time - self.last_activated).total_seconds() / 3600.0

        # 指数衰减: level = level * e^(-decay_rate * time)
        decay_factor = math.exp(-self.decay_rate * time_diff)
        self.activation_level *= decay_factor

        # 清理过期的激活源
        sources_to_remove = []
        for source, strength in self.activation_sources.items():
            # 激活源也随时间衰减
            decayed_strength = strength * decay_factor
            if decayed_strength < 0.01:
                sources_to_remove.append(source)
            else:
                self.activation_sources[source] = decayed_strength

        for source in sources_to_remove:
            del self.activation_sources[source]

        return self.activation_level

    def get_total_activation(self) -> float:
        """获取总激活水平"""
        return self.activation_level

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "memory_id": self.memory_id,
            "activation_level": self.activation_level,
            "activation_sources": self.activation_sources,
            "last_activated": self.last_activated.isoformat(),
            "decay_rate": self.decay_rate,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MemoryActivation":
        """从字典创建"""
        return cls(
            memory_id=data["memory_id"],
            activation_level=data.get("activation_level", 0.0),
            activation_sources=data.get("activation_sources", {}),
            last_activated=datetime.datetime.fromisoformat(data["last_activated"]),
            decay_rate=data.get("decay_rate", 0.1),
            metadata=data.get("metadata", {}),
        )


@dataclass
class MemoryRetrievalContext:
    """记忆检索上下文

    封装检索请求的所有上下文信息。
    """

    query: str
    agent_id: str
    user_id: str = "default"
    current_emotion: Optional[str] = None
    emotion_intensity: float = 0.0
    importance_threshold: float = 0.3
    max_results: int = 10
    time_window_hours: Optional[float] = None
    include_metadata: bool = True
    diversity_factor: float = 0.3  # 多样性因子 (0-1)
    recency_weight: float = 0.4  # 近因权重
    relevance_weight: float = 0.4  # 相关性权重
    importance_weight: float = 0.2  # 重要性权重
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "query": self.query,
            "agent_id": self.agent_id,
            "user_id": self.user_id,
            "current_emotion": self.current_emotion,
            "emotion_intensity": self.emotion_intensity,
            "importance_threshold": self.importance_threshold,
            "max_results": self.max_results,
            "time_window_hours": self.time_window_hours,
            "include_metadata": self.include_metadata,
            "diversity_factor": self.diversity_factor,
            "recency_weight": self.recency_weight,
            "relevance_weight": self.relevance_weight,
            "importance_weight": self.importance_weight,
            "metadata": self.metadata,
        }


@dataclass
class RetrievalResult:
    """检索结果"""

    memory_id: str
    content: str
    score: float
    activation_level: float
    importance: float
    emotion: Optional[str] = None
    timestamp: Optional[datetime.datetime] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    score_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = {
            "memory_id": self.memory_id,
            "content": self.content[:500],  # 截断长内容
            "score": self.score,
            "activation_level": self.activation_level,
            "importance": self.importance,
        }
        if self.emotion:
            result["emotion"] = self.emotion
        if self.timestamp:
            result["timestamp"] = self.timestamp.isoformat()
        if self.metadata:
            result["metadata"] = self.metadata
        if self.score_breakdown:
            result["score_breakdown"] = self.score_breakdown
        return result


class EnhancedMemoryRetriever:
    """增强版记忆检索器

    模拟人类回忆机制的多层级检索系统。
    """

    def __init__(
        self,
        memory_manager: Any = None,
        temperature_engine: Any = None,
        vector_search: Any = None,
        max_activations: int = 1000,
    ):
        """初始化检索器

        Args:
            memory_manager: 记忆管理器
            temperature_engine: 温度引擎
            vector_search: 向量搜索引擎
            max_activations: 最大激活记忆数量
        """
        self._memory_manager = memory_manager
        self._temperature_engine = temperature_engine
        self._vector_search = vector_search
        self._max_activations = max_activations

        # 激活记忆缓存
        self._activations: Dict[str, MemoryActivation] = {}
        self._lock = threading.RLock()

        # 统计信息
        self._stats = {
            "total_retrievals": 0,
            "cache_hits": 0,
            "avg_retrieval_time_ms": 0.0,
        }

        logger.info("EnhancedMemoryRetriever 初始化完成")

    def _get_temperature_score(self, memory: Any) -> float:
        """获取记忆温度分数

        Args:
            memory: 记忆对象

        Returns:
            温度分数 (0-1)
        """
        if self._temperature_engine is None:
            return 0.5

        try:
            # 尝试从温度引擎获取温度
            if hasattr(memory, "id"):
                temp = self._temperature_engine.get_temperature(memory.id)
                if temp is not None:
                    return temp

            # 回退到默认计算
            if hasattr(memory, "importance") and hasattr(memory, "last_accessed"):
                importance = getattr(memory, "importance", 0.5)
                last_accessed = getattr(memory, "last_accessed", None)

                if last_accessed:
                    # 基于重要性和访问时间计算温度
                    time_diff = (datetime.datetime.now(datetime.timezone.utc) - last_accessed).total_seconds() / 3600.0
                    time_factor = math.exp(-0.1 * time_diff)  # 时间衰减
                    return importance * 0.7 + time_factor * 0.3

            return 0.5
        except Exception as e:
            logger.warning("获取温度分数失败: %s", e)
            return 0.5

    def _get_temporal_score(self, memory: Any, current_time: Optional[datetime.datetime] = None) -> float:
        """获取时间分数

        Args:
            memory: 记忆对象
            current_time: 当前时间

        Returns:
            时间分数 (0-1)，近期记忆分数更高
        """
        if current_time is None:
            current_time = datetime.datetime.now(datetime.timezone.utc)

        try:
            # 获取记忆时间戳
            memory_time = None
            if hasattr(memory, "timestamp"):
                memory_time = memory.timestamp
            elif hasattr(memory, "created_at"):
                memory_time = memory.created_at
            elif hasattr(memory, "last_accessed"):
                memory_time = memory.last_accessed

            if memory_time is None:
                return 0.5

            # 计算时间差（小时）
            time_diff_hours = (current_time - memory_time).total_seconds() / 3600.0

            # 对数衰减：近期记忆分数高，但不会完全归零
            # score = 1 / (1 + log(1 + time_diff_hours))
            score = 1.0 / (1.0 + math.log1p(time_diff_hours))

            return min(1.0, max(0.0, score))
        except Exception as e:
            logger.warning("获取时间分数失败: %s", e)
            return 0.5

    def _get_emotional_match_score(self, memory: Any, context: MemoryRetrievalContext) -> float:
        """获取情感匹配分数

        Args:
            memory: 记忆对象
            context: 检索上下文

        Returns:
            情感匹配分数 (0-1)
        """
        if not context.current_emotion:
            return 0.5  # 无情感上下文，返回中性分数

        try:
            # 获取记忆的情感标签
            memory_emotion = None
            if hasattr(memory, "emotion"):
                memory_emotion = memory.emotion
            elif hasattr(memory, "tags"):
                # 从标签中提取情感
                tags = getattr(memory, "tags", [])
                for tag in tags:
                    if tag.startswith("emotion:"):
                        memory_emotion = tag.split(":")[1]
                        break

            if not memory_emotion:
                return 0.5

            # 情感相似度矩阵
            emotion_similarity = {
                ("joy", "joy"): 1.0,
                ("joy", "trust"): 0.8,
                ("joy", "anticipation"): 0.7,
                ("sadness", "sadness"): 1.0,
                ("sadness", "fear"): 0.6,
                ("anger", "anger"): 1.0,
                ("anger", "disgust"): 0.7,
                ("fear", "fear"): 1.0,
                ("fear", "sadness"): 0.6,
                ("surprise", "surprise"): 1.0,
                ("surprise", "joy"): 0.5,
                ("trust", "trust"): 1.0,
                ("trust", "joy"): 0.8,
                ("anticipation", "anticipation"): 1.0,
                ("anticipation", "joy"): 0.7,
            }

            # 计算情感匹配度
            pair = (context.current_emotion, memory_emotion)
            reverse_pair = (memory_emotion, context.current_emotion)

            similarity = emotion_similarity.get(pair, emotion_similarity.get(reverse_pair, 0.5))

            # 考虑情感强度
            intensity_factor = 1.0 - (context.emotion_intensity * 0.3)  # 高强度情感更宽容

            return similarity * intensity_factor
        except Exception as e:
            logger.warning("获取情感匹配分数失败: %s", e)
            return 0.5

    def _get_importance_score(self, memory: Any) -> float:
        """获取重要性分数

        Args:
            memory: 记忆对象

        Returns:
            重要性分数 (0-1)
        """
        try:
            # 直接获取重要性属性
            if hasattr(memory, "importance"):
                return min(1.0, max(0.0, memory.importance))

            # 从元数据获取
            if hasattr(memory, "metadata") and isinstance(memory.metadata, dict):
                return memory.metadata.get("importance", 0.5)

            return 0.5
        except Exception as e:
            logger.warning("获取重要性分数失败: %s", e)
            return 0.5

    def _get_activation_score(self, memory_id: str) -> float:
        """获取激活分数

        Args:
            memory_id: 记忆ID

        Returns:
            激活分数 (0-1)
        """
        with self._lock:
            activation = self._activations.get(memory_id)
            if activation:
                return activation.get_total_activation()
            return 0.0

    def _spread_activation(
        self,
        source_memory_id: str,
        memories: List[Any],
        strength: float = 0.3,
        max_spread: int = 5,
    ) -> List[Tuple[str, float]]:
        """扩散激活

        模拟神经网络中的激活扩散。

        Args:
            source_memory_id: 源记忆ID
            memories: 所有记忆列表
            strength: 扩散强度
            max_spread: 最大扩散数量

        Returns:
            [(memory_id, activation_strength), ...]
        """
        spread_results = []

        try:
            # 获取源记忆
            source_memory = None
            for mem in memories:
                if hasattr(mem, "id") and mem.id == source_memory_id:
                    source_memory = mem
                    break

            if not source_memory:
                return []

            # 获取源记忆的关联记忆
            source_tags = set()
            if hasattr(source_memory, "tags"):
                source_tags = set(source_memory.tags)
            elif hasattr(source_memory, "metadata") and isinstance(source_memory.metadata, dict):
                source_tags = set(source_memory.metadata.get("tags", []))

            if not source_tags:
                return []

            # 计算关联度并扩散
            for mem in memories:
                if hasattr(mem, "id") and mem.id != source_memory_id:
                    # 计算标签重叠度
                    mem_tags = set()
                    if hasattr(mem, "tags"):
                        mem_tags = set(mem.tags)
                    elif hasattr(mem, "metadata") and isinstance(mem.metadata, dict):
                        mem_tags = set(mem.metadata.get("tags", []))

                    if mem_tags:
                        overlap = len(source_tags & mem_tags)
                        total = len(source_tags | mem_tags)

                        if total > 0:
                            similarity = overlap / total
                            activation_strength = strength * similarity

                            if activation_strength > 0.1:  # 阈值过滤
                                spread_results.append((mem.id, activation_strength))

            # 按激活强度排序，取前N个
            spread_results.sort(key=lambda x: x[1], reverse=True)
            return spread_results[:max_spread]
        except Exception as e:
            logger.warning("扩散激活失败: %s", e)
            return []

    def _calculate_composite_score(
        self,
        memory: Any,
        context: MemoryRetrievalContext,
        temperature_score: float,
        temporal_score: float,
        emotional_score: float,
        importance_score: float,
        activation_score: float,
    ) -> Tuple[float, Dict[str, float]]:
        """计算复合分数

        Args:
            memory: 记忆对象
            context: 检索上下文
            temperature_score: 温度分数
            temporal_score: 时间分数
            emotional_score: 情感分数
            importance_score: 重要性分数
            activation_score: 激活分数

        Returns:
            (总分数, 分数分解)
        """
        # 权重配置
        weights = {
            "temperature": 0.25,
            "temporal": context.recency_weight,
            "emotional": 0.15,
            "importance": context.importance_weight,
            "activation": 0.1,
        }

        # 计算加权分数
        score_breakdown = {
            "temperature": temperature_score * weights["temperature"],
            "temporal": temporal_score * weights["temporal"],
            "emotional": emotional_score * weights["emotional"],
            "importance": importance_score * weights["importance"],
            "activation": activation_score * weights["activation"],
        }

        total_score = sum(score_breakdown.values())

        return total_score, score_breakdown

    def _diversity_filter(
        self,
        results: List[RetrievalResult],
        diversity_factor: float,
    ) -> List[RetrievalResult]:
        """多样性过滤

        确保结果多样性，避免返回过于相似的记忆。

        Args:
            results: 检索结果列表
            diversity_factor: 多样性因子 (0-1)

        Returns:
            过滤后的结果列表
        """
        if not results or diversity_factor <= 0:
            return results

        try:
            # 按分数排序
            results.sort(key=lambda x: x.score, reverse=True)

            filtered = [results[0]]  # 保留最高分
            remaining = results[1:]

            while remaining and len(filtered) < len(results):
                # 计算每个候选项与已选项目的最小相似度
                best_candidate = None
                best_diversity_score = -1

                for candidate in remaining:
                    # 计算与已选项目的最小相似度
                    min_similarity = 1.0
                    for selected in filtered:
                        similarity = self._simple_content_similarity(candidate.content, selected.content)
                        min_similarity = min(min_similarity, similarity)

                    # 多样性分数 = 原始分数 * (1 - 相似度 * diversity_factor)
                    diversity_score = candidate.score * (1 - min_similarity * diversity_factor)

                    if diversity_score > best_diversity_score:
                        best_diversity_score = diversity_score
                        best_candidate = candidate

                if best_candidate:
                    filtered.append(best_candidate)
                    remaining.remove(best_candidate)
                else:
                    break

            return filtered
        except Exception as e:
            logger.warning("多样性过滤失败: %s", e)
            return results

    def _simple_content_similarity(self, content1: str, content2: str) -> float:
        """简单内容相似度计算

        使用字符级别的Jaccard相似度。

        Args:
            content1: 内容1
            content2: 内容2

        Returns:
            相似度 (0-1)
        """
        if not content1 or not content2:
            return 0.0

        # 简单的字符级Jaccard相似度
        set1 = set(content1.lower())
        set2 = set(content2.lower())

        intersection = len(set1 & set2)
        union = len(set1 | set2)

        return intersection / union if union > 0 else 0.0

    def retrieve_memories(
        self,
        context: MemoryRetrievalContext,
        memories: List[Any],
    ) -> List[RetrievalResult]:
        """检索记忆

        Args:
            context: 检索上下文
            memories: 记忆列表

        Returns:
            检索结果列表
        """
        start_time = time.time()

        try:
            results = []
            current_time = datetime.datetime.now(datetime.timezone.utc)

            for memory in memories:
                # 计算各维度分数
                temperature_score = self._get_temperature_score(memory)
                temporal_score = self._get_temporal_score(memory, current_time)
                emotional_score = self._get_emotional_match_score(memory, context)
                importance_score = self._get_importance_score(memory)

                # 获取激活分数
                memory_id = getattr(memory, "id", str(id(memory)))
                activation_score = self._get_activation_score(memory_id)

                # 计算复合分数
                total_score, score_breakdown = self._calculate_composite_score(
                    memory,
                    context,
                    temperature_score,
                    temporal_score,
                    emotional_score,
                    importance_score,
                    activation_score,
                )

                # 过滤低分记忆
                if total_score >= context.importance_threshold:
                    # 获取记忆内容
                    content = ""
                    if hasattr(memory, "content"):
                        content = memory.content
                    elif hasattr(memory, "text"):
                        content = memory.text
                    elif hasattr(memory, "summary"):
                        content = memory.summary

                    # 获取记忆时间戳
                    timestamp = None
                    if hasattr(memory, "timestamp"):
                        timestamp = memory.timestamp
                    elif hasattr(memory, "created_at"):
                        timestamp = memory.created_at

                    # 获取情感标签
                    emotion = None
                    if hasattr(memory, "emotion"):
                        emotion = memory.emotion

                    # 构建结果
                    result = RetrievalResult(
                        memory_id=memory_id,
                        content=content,
                        score=total_score,
                        activation_level=activation_score,
                        importance=importance_score,
                        emotion=emotion,
                        timestamp=timestamp,
                        score_breakdown=score_breakdown,
                    )
                    results.append(result)

            # 排序
            results.sort(key=lambda x: x.score, reverse=True)

            # 多样性过滤
            if context.diversity_factor > 0:
                results = self._diversity_filter(results, context.diversity_factor)

            # 限制结果数量
            results = results[: context.max_results]

            # 更新统计
            retrieval_time_ms = (time.time() - start_time) * 1000
            self._stats["total_retrievals"] += 1
            self._stats["avg_retrieval_time_ms"] = (
                self._stats["avg_retrieval_time_ms"] * (self._stats["total_retrievals"] - 1) + retrieval_time_ms
            ) / self._stats["total_retrievals"]

            logger.debug("检索完成: %.2f 条记忆, 耗时 %sms", len(results), retrieval_time_ms)
            return results
        except Exception as e:
            logger.error("检索记忆失败: %s", e)
            return []

    def decay_all_activations(self, current_time: Optional[datetime.datetime] = None) -> None:
        """衰减所有激活记忆

        Args:
            current_time: 当前时间
        """
        with self._lock:
            if current_time is None:
                current_time = datetime.datetime.now(datetime.timezone.utc)

            # 衰减所有激活
            to_remove = []
            for memory_id, activation in self._activations.items():
                activation.decay(current_time)

                # 移除低激活记忆
                if activation.get_total_activation() < 0.01:
                    to_remove.append(memory_id)

            for memory_id in to_remove:
                del self._activations[memory_id]

            logger.debug("衰减完成: 移除 %s 条低激活记忆", len(to_remove))

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                **self._stats,
                "active_memories": len(self._activations),
            }

    def clear(self) -> None:
        """清空激活缓存"""
        with self._lock:
            self._activations.clear()
            logger.info("激活缓存已清空")


class MemoryQueryIntelligence:
    """记忆查询智能

    分析查询意图，选择最佳检索策略。
    """

    def __init__(self):
        """初始化查询智能"""
        # 查询模式
        self._query_patterns = {
            "factual": [
                r"what is|什么是|是什么",
                r"define|定义|解释",
                r"who is|谁是|是谁",
                r"when did|什么时候|何时",
                r"where is|在哪里|在哪",
            ],
            "temporal": [
                r"recent|最近|近期",
                r"yesterday|昨天",
                r"last week|上周",
                r"last month|上个月",
                r"today|今天",
                r"this week|本周",
            ],
            "emotional": [
                r"feel|感觉|感受",
                r"happy|开心|高兴",
                r"sad|难过|悲伤",
                r"angry|生气|愤怒",
                r"afraid|害怕|恐惧",
            ],
            "procedural": [
                r"how to|如何|怎么",
                r"step by step|步骤|流程",
                r"instruct|指导|教程",
                r"guide|指南|引导",
            ],
            "associative": [
                r"related|相关|关联",
                r"similar|类似|相似",
                r"like|像|好像",
                r"remind|提醒|想起",
            ],
        }

        # 检索策略
        self._strategies = {
            "factual": {
                "recency_weight": 0.2,
                "relevance_weight": 0.6,
                "importance_weight": 0.2,
                "diversity_factor": 0.2,
            },
            "temporal": {
                "recency_weight": 0.7,
                "relevance_weight": 0.2,
                "importance_weight": 0.1,
                "diversity_factor": 0.1,
            },
            "emotional": {
                "recency_weight": 0.3,
                "relevance_weight": 0.3,
                "importance_weight": 0.2,
                "diversity_factor": 0.2,
            },
            "procedural": {
                "recency_weight": 0.1,
                "relevance_weight": 0.5,
                "importance_weight": 0.4,
                "diversity_factor": 0.3,
            },
            "associative": {
                "recency_weight": 0.2,
                "relevance_weight": 0.4,
                "importance_weight": 0.2,
                "diversity_factor": 0.5,
            },
            "default": {
                "recency_weight": 0.4,
                "relevance_weight": 0.4,
                "importance_weight": 0.2,
                "diversity_factor": 0.3,
            },
        }

        logger.info("MemoryQueryIntelligence 初始化完成")

    def classify_query(self, query: str) -> str:
        """分类查询意图

        Args:
            query: 查询文本

        Returns:
            查询类型
        """
        import re

        query_lower = query.lower()

        for query_type, patterns in self._query_patterns.items():
            for pattern in patterns:
                if re.search(pattern, query_lower):
                    return query_type

        return "default"

    def get_retrieval_strategy(self, query: str) -> Dict[str, float]:
        """获取检索策略

        Args:
            query: 查询文本

        Returns:
            策略配置
        """
        query_type = self.classify_query(query)
        return self._strategies.get(query_type, self._strategies["default"])


# 全局实例管理
_enhanced_retriever: Optional[EnhancedMemoryRetriever] = None
_query_intelligence: Optional[MemoryQueryIntelligence] = None
_retriever_lock = threading.Lock()


def get_enhanced_retriever(
    memory_manager: Any = None,
    temperature_engine: Any = None,
    vector_search: Any = None,
) -> EnhancedMemoryRetriever:
    """获取增强检索器单例

    Args:
        memory_manager: 记忆管理器
        temperature_engine: 温度引擎
        vector_search: 向量搜索引擎

    Returns:
        增强检索器实例
    """
    global _enhanced_retriever

    with _retriever_lock:
        if _enhanced_retriever is None:
            _enhanced_retriever = EnhancedMemoryRetriever(
                memory_manager=memory_manager,
                temperature_engine=temperature_engine,
                vector_search=vector_search,
            )
        return _enhanced_retriever


def get_query_intelligence() -> MemoryQueryIntelligence:
    """获取查询智能单例

    Returns:
        查询智能实例
    """
    global _query_intelligence

    with _retriever_lock:
        if _query_intelligence is None:
            _query_intelligence = MemoryQueryIntelligence()
        return _query_intelligence


def reset_enhanced_retriever() -> None:
    """重置增强检索器单例"""
    global _enhanced_retriever

    with _retriever_lock:
        if _enhanced_retriever is not None:
            _enhanced_retriever.clear()
            _enhanced_retriever = None


def reset_query_intelligence() -> None:
    """重置查询智能单例"""
    global _query_intelligence

    with _retriever_lock:
        _query_intelligence = None
