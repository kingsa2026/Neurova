"""
Neurova 统一记忆检索引擎 — 多维融合 + 意图钻取

架构：
  Phase 1: 多维融合召回 — 5通道并行，多信号加权排序
  Phase 2: 意图驱动钻取 — 从种子记忆沿关系路径定向深入

核心理念：
  不是"搜索"，而是"浮现"——热的、情感的、相关的记忆自然浮现
  不是"遍历"，而是"钻探"——有意图、有方向、可解释地深入
"""

from dataclasses import dataclass, field
import datetime
import logging
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ────── Enums ──────

class RecallChannel(Enum):
    """检索通道"""
    TEMPERATURE = "temperature"   # 温度通道（热记忆优先）
    TEXT = "text"                 # 文本通道（语义相似度）
    CATEGORY = "category"        # 分类通道（同类别记忆）
    GRAPH = "graph"              # 图通道（关系图谱）
    EMOTION = "emotion"          # 情感通道（情感相似度）


class DrillIntent(Enum):
    """钻取意图"""
    EXPLORE = "explore"           # 探索（发现新知识）
    DEEPEN = "deepen"            # 深化（深入理解）
    CONNECT = "connect"          # 连接（建立关联）
    CONTRAST = "contrast"        # 对比（寻找差异）
    VALIDATE = "validate"        # 验证（确认事实）


# ────── Data Models ──────

@dataclass
class RecalledMemory:
    """召回的记忆"""
    memory_id: str = ""
    content: str = ""
    score: float = 0.0
    channel: RecallChannel = RecallChannel.TEXT
    metadata: Dict[str, Any] = field(default_factory=dict)
    recalled_at: datetime.datetime = field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "content": self.content,
            "score": self.score,
            "channel": self.channel.value,
            "metadata": self.metadata,
            "recalled_at": self.recalled_at.isoformat(),
        }


@dataclass
class RecallResult:
    """检索结果"""
    query: str = ""
    intent: DrillIntent = DrillIntent.EXPLORE
    recalled_memories: List[RecalledMemory] = field(default_factory=list)
    total_score: float = 0.0
    phase1_duration_ms: float = 0.0
    phase2_duration_ms: float = 0.0
    total_duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query,
            "intent": self.intent.value,
            "recalled_memories": [m.to_dict() for m in self.recalled_memories],
            "total_score": self.total_score,
            "phase1_duration_ms": self.phase1_duration_ms,
            "phase2_duration_ms": self.phase2_duration_ms,
            "total_duration_ms": self.total_duration_ms,
            "metadata": self.metadata,
        }


# ────── Main Engine ──────

class NeurovaRecallEngine:
    """
    Neurova 统一记忆检索引擎
    
    多维融合召回 + 意图驱动钻取
    """
    
    def __init__(
        self,
        memory_manager: Any = None,
        max_workers: int = 4,
        timeout_seconds: float = 10.0,
    ):
        """
        初始化检索引擎
        
        Args:
            memory_manager: 记忆管理器
            max_workers: 最大并行工作线程数
            timeout_seconds: 超时时间（秒）
        """
        self.memory_manager = memory_manager
        self.max_workers = max_workers
        self.timeout_seconds = timeout_seconds
        
        # 通道权重
        self._channel_weights = {
            RecallChannel.TEMPERATURE: 0.3,
            RecallChannel.TEXT: 0.35,
            RecallChannel.CATEGORY: 0.15,
            RecallChannel.GRAPH: 0.1,
            RecallChannel.EMOTION: 0.1,
        }
        
        logger.info("NeurovaRecallEngine 初始化完成")
    
    def recall(
        self,
        query: str,
        intent: DrillIntent = DrillIntent.EXPLORE,
        limit: int = 20,
        channels: Optional[List[RecallChannel]] = None,
    ) -> RecallResult:
        """
        检索记忆（两阶段）
        
        Args:
            query: 查询文本
            intent: 钻取意图
            limit: 返回数量限制
            channels: 启用的通道
            
        Returns:
            检索结果
        """
        start_time = time.time()
        
        # 确定启用的通道
        if channels is None:
            channels = list(RecallChannel)
        
        # Phase 1: 多维融合召回
        phase1_start = time.time()
        phase1_results = self._phase1_multichannel_recall(query, channels, limit * 2)
        phase1_duration = (time.time() - phase1_start) * 1000
        
        # Phase 2: 意图驱动钻取
        phase2_start = time.time()
        phase2_results = self._phase2_drill(query, intent, phase1_results, limit)
        phase2_duration = (time.time() - phase2_start) * 1000
        
        total_duration = (time.time() - start_time) * 1000
        
        # 计算总分
        total_score = sum(m.score for m in phase2_results)
        
        return RecallResult(
            query=query,
            intent=intent,
            recalled_memories=phase2_results,
            total_score=total_score,
            phase1_duration_ms=phase1_duration,
            phase2_duration_ms=phase2_duration,
            total_duration_ms=total_duration,
            metadata={
                "channels_used": [c.value for c in channels],
                "limit": limit,
            },
        )
    
    def recall_flat(
        self,
        query: str,
        limit: int = 20,
        channels: Optional[List[RecallChannel]] = None,
    ) -> List[RecalledMemory]:
        """
        平坦检索（不进行意图钻取）
        
        Args:
            query: 查询文本
            limit: 返回数量限制
            channels: 启用的通道
            
        Returns:
            召回的记忆列表
        """
        if channels is None:
            channels = list(RecallChannel)
        
        results = self._phase1_multichannel_recall(query, channels, limit)
        
        # 按分数排序
        results.sort(key=lambda m: m.score, reverse=True)
        
        return results[:limit]
    
    def _run_with_timeout(self, func, *args, **kwargs) -> Any:
        """带超时执行"""
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(func, *args, **kwargs)
            try:
                return future.result(timeout=self.timeout_seconds)
            except TimeoutError:
                logger.warning(f"执行超时: {func.__name__}")
                return []
    
    def _phase1_multichannel_recall(
        self,
        query: str,
        channels: List[RecallChannel],
        limit: int,
    ) -> List[RecalledMemory]:
        """
        Phase 1: 多维融合召回
        
        Args:
            query: 查询文本
            channels: 启用的通道
            limit: 返回数量限制
            
        Returns:
            召回的记忆列表
        """
        all_results: List[RecalledMemory] = []
        
        # 并行执行各通道检索
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {}
            
            for channel in channels:
                if channel == RecallChannel.TEMPERATURE:
                    futures[executor.submit(self._channel_temperature, query, limit)] = channel
                elif channel == RecallChannel.TEXT:
                    futures[executor.submit(self._channel_text, query, limit)] = channel
                elif channel == RecallChannel.CATEGORY:
                    futures[executor.submit(self._channel_category, query, limit)] = channel
                elif channel == RecallChannel.GRAPH:
                    futures[executor.submit(self._channel_graph, query, limit)] = channel
                elif channel == RecallChannel.EMOTION:
                    futures[executor.submit(self._channel_emotion, query, limit)] = channel
            
            # 收集结果
            for future in as_completed(futures):
                channel = futures[future]
                try:
                    results = future.result(timeout=self.timeout_seconds)
                    all_results.extend(results)
                except Exception as e:
                    logger.error(f"通道 {channel.value} 检索失败: {e}")
        
        # 去重和融合
        deduplicated = self._deduplicate_results(all_results)
        
        # 计算融合分数
        for memory in deduplicated:
            memory.score = self._fusion_score(memory, query)
        
        # 按融合分数排序
        deduplicated.sort(key=lambda m: m.score, reverse=True)
        
        return deduplicated[:limit]
    
    def _channel_temperature(self, query: str, limit: int) -> List[RecalledMemory]:
        """温度通道（热记忆优先）"""
        # 简化实现
        logger.debug(f"温度通道检索: {query}")
        return []
    
    def _channel_text(self, query: str, limit: int) -> List[RecalledMemory]:
        """文本通道（语义相似度）"""
        # 简化实现
        logger.debug(f"文本通道检索: {query}")
        return []
    
    def _channel_category(self, query: str, limit: int) -> List[RecalledMemory]:
        """分类通道（同类别记忆）"""
        # 简化实现
        logger.debug(f"分类通道检索: {query}")
        return []
    
    def _channel_graph(self, query: str, limit: int) -> List[RecalledMemory]:
        """图通道（关系图谱）"""
        # 简化实现
        logger.debug(f"图通道检索: {query}")
        return []
    
    def _channel_emotion(self, query: str, limit: int) -> List[RecalledMemory]:
        """情感通道（情感相似度）
        
        检索与查询文本情感相似的记忆：
        1. 分析查询文本的情感
        2. 搜索相同情感类型的记忆
        3. 按情感强度排序
        """
        logger.debug(f"情感通道检索: {query}")
        
        if not self.memory_manager:
            return []
        
        try:
            # 分析查询情感
            from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule
            emotion_module = getattr(self.memory_manager, 'emotion_module', None)
            if not emotion_module:
                return []
            
            # 分析查询情感
            emotion_state = emotion_module.analyze_text_emotion(query)
            if not emotion_state or emotion_state.primary_emotion.value == "neutral":
                return []
            
            # 搜索相同情感的记忆
            memory_ids = emotion_module.get_emotional_memories(
                emotion_type=emotion_state.primary_emotion,
                min_intensity=0.3,
                limit=limit,
            )
            
            results = []
            for mid in memory_ids:
                mem_dict = self.memory_manager.recall(query="", limit=1)
                # 找到对应记忆
                mem_obj = self.memory_manager._memories.get(mid)
                if mem_obj:
                    mem_emotion = emotion_module.get_emotion(mid)
                    score = mem_emotion.intensity if mem_emotion else 0.5
                    
                    results.append(RecalledMemory(
                        memory_id=mid,
                        content=mem_obj.content,
                        score=score,
                        channel=RecallChannel.EMOTION,
                        metadata={
                            "emotion": emotion_state.primary_emotion.value,
                            "intensity": emotion_state.intensity,
                        },
                    ))
            
            return results
            
        except Exception as e:
            logger.debug(f"情感通道检索失败: {e}")
            return []
    
    def _fusion_score(self, memory: RecalledMemory, query: str) -> float:
        """计算融合分数"""
        # 基础分数
        base_score = memory.score
        
        # 通道权重
        channel_weight = self._channel_weights.get(memory.channel, 0.1)
        
        # 时间衰减（越新越好）
        time_decay = self._recency_score(memory.recalled_at)
        
        # 融合分数
        fusion_score = base_score * channel_weight * time_decay
        
        return fusion_score
    
    def _recency_score(self, recalled_at: datetime.datetime) -> float:
        """计算时间衰减分数"""
        now = datetime.datetime.now(datetime.timezone.utc)
        age_hours = (now - recalled_at).total_seconds() / 3600
        
        # 指数衰减
        decay_rate = 0.1  # 每小时衰减10%
        score = math.exp(-decay_rate * age_hours)
        
        return max(0.1, score)  # 最低0.1分
    
    def _deduplicate_results(self, results: List[RecalledMemory]) -> List[RecalledMemory]:
        """去重结果"""
        seen: Dict[str, RecalledMemory] = {}
        
        for memory in results:
            if memory.memory_id in seen:
                # 保留分数更高的
                if memory.score > seen[memory.memory_id].score:
                    seen[memory.memory_id] = memory
            else:
                seen[memory.memory_id] = memory
        
        return list(seen.values())
    
    def _phase2_drill(
        self,
        query: str,
        intent: DrillIntent,
        seed_memories: List[RecalledMemory],
        limit: int,
    ) -> List[RecalledMemory]:
        """
        Phase 2: 意图驱动钻取
        
        Args:
            query: 查询文本
            intent: 钻取意图
            seed_memories: 种子记忆
            limit: 返回数量限制
            
        Returns:
            钻取后的记忆列表
        """
        if not seed_memories:
            return []
        
        # 推断钻取意图
        inferred_intent = self._infer_intent(query, intent)
        
        # 根据意图选择钻取策略
        if inferred_intent == DrillIntent.EXPLORE:
            return self._drill_explore(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.DEEPEN:
            return self._drill_deepen(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.CONNECT:
            return self._drill_connect(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.CONTRAST:
            return self._drill_contrast(query, seed_memories, limit)
        elif inferred_intent == DrillIntent.VALIDATE:
            return self._drill_validate(query, seed_memories, limit)
        
        # 默认返回种子记忆
        return seed_memories[:limit]
    
    def _infer_intent(self, query: str, default_intent: DrillIntent) -> DrillIntent:
        """推断钻取意图"""
        query_lower = query.lower()
        
        # 关键词匹配
        if any(word in query_lower for word in ["什么是", "是什么", "定义", "概念"]):
            return DrillIntent.EXPLORE
        elif any(word in query_lower for word in ["为什么", "原因", "解释", "详细"]):
            return DrillIntent.DEEPEN
        elif any(word in query_lower for word in ["关联", "关系", "连接", "相关"]):
            return DrillIntent.CONNECT
        elif any(word in query_lower for word in ["区别", "不同", "对比", "比较"]):
            return DrillIntent.CONTRAST
        elif any(word in query_lower for word in ["确认", "验证", "正确", "真实"]):
            return DrillIntent.VALIDATE
        
        return default_intent
    
    def _infer_category(self, query: str) -> Optional[str]:
        """推断查询类别"""
        # 简化实现
        return None
    
    def _active_channels(self, intent: DrillIntent) -> List[RecallChannel]:
        """根据意图确定活跃通道"""
        channel_mapping = {
            DrillIntent.EXPLORE: [RecallChannel.TEMPERATURE, RecallChannel.TEXT],
            DrillIntent.DEEPEN: [RecallChannel.TEXT, RecallChannel.GRAPH],
            DrillIntent.CONNECT: [RecallChannel.GRAPH, RecallChannel.CATEGORY],
            DrillIntent.CONTRAST: [RecallChannel.TEXT, RecallChannel.CATEGORY],
            DrillIntent.VALIDATE: [RecallChannel.TEXT, RecallChannel.EMOTION],
        }
        
        return channel_mapping.get(intent, list(RecallChannel))
    
    def _drill_explore(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """探索钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_deepen(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """深化钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_connect(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """连接钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_contrast(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """对比钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]
    
    def _drill_validate(self, query: str, seed_memories: List[RecalledMemory], limit: int) -> List[RecalledMemory]:
        """验证钻取"""
        # 简化实现：返回种子记忆
        return seed_memories[:limit]