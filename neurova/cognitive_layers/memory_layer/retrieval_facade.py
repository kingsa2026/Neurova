"""
统一记忆检索门面

提供统一的记忆检索接口，协调多个检索组件：
- NeurovaRecallEngine (6通道检索)
- VolumeRenderer (NeRF融合)
- MuscleMemory (肌肉记忆)
- ToolMemoryIntegration (工具记忆)

支持三层隔离机制：
1. Agent隔离 (agent_id) - 不同Agent的记忆完全隔离
2. 系统用户隔离 (neuser_id) - 同一Agent下不同系统用户的记忆隔离
3. 对话用户隔离 (user_id) - 同一系统用户下不同对话的记忆隔离

设计模式: Facade + 4级降级策略
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__)


@dataclass
class UnifiedRecallResult:
    """统一检索结果"""
    memories: List[Dict[str, Any]]  # 统一格式的记忆列表
    scores: Dict[str, float]  # 各通道/来源的分数
    metadata: Dict[str, Any]  # 元数据（意图、耗时等）
    source: str  # 主要来源（recall/nerf/muscle/tool/fallback）
    confidence: float  # 整体置信度 0.0-1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "memories": self.memories,
            "scores": self.scores,
            "metadata": self.metadata,
            "source": self.source,
            "confidence": self.confidence,
        }


class MemoryRetrievalFacade:
    """
    统一记忆检索门面
    
    提供简单的检索接口，内部协调多个检索组件。
    支持4级降级策略保证可用性。
    
    使用示例:
        facade = MemoryRetrievalFacade(...)
        result = facade.retrieve("what happened yesterday")
        for memory in result.memories:
            print(memory["content"])
    """
    
    def __init__(
        self,
        recall_engine=None,
        volume_renderer=None,
        muscle_memory=None,
        tool_memory=None,
        use_nerf_fusion: bool = True,
        cache_ttl: int = 300,
        max_workers: int = 2,
    ):
        """
        初始化检索门面
        
        Args:
            recall_engine: NeurovaRecallEngine实例
            volume_renderer: VolumeRenderer实例
            muscle_memory: MuscleMemory实例
            tool_memory: ToolMemoryIntegration实例
            use_nerf_fusion: 是否使用NeRF融合
            cache_ttl: 缓存过期时间（秒）
            max_workers: 并行检索最大线程数
        """
        self._recall_engine = recall_engine
        self._volume_renderer = volume_renderer
        self._muscle_memory = muscle_memory
        self._tool_memory = tool_memory
        self._use_nerf_fusion = use_nerf_fusion
        self._cache_ttl = cache_ttl
        self._max_workers = max_workers
        
        # 简单缓存 (key -> (result, timestamp))
        self._cache: Dict[str, Tuple[UnifiedRecallResult, float]] = {}
        
        logger.info(
            "MemoryRetrievalFacade初始化: nerf=%s, cache_ttl=%d",
            use_nerf_fusion, cache_ttl
        )
    
    def retrieve(
        self,
        query: str,
        intent=None,
        limit: int = 10,
        use_cache: bool = True,
        agent_id: Optional[str] = None,
        neuser_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> UnifiedRecallResult:
        """
        统一检索入口
        
        自动选择最佳检索策略，支持4级降级。
        支持三层隔离机制（agent_id, neuser_id, user_id）。
        
        Args:
            query: 查询文本
            intent: 查询意图（可选，自动检测）
            limit: 返回结果数量
            use_cache: 是否使用缓存
            agent_id: Agent ID（第1层隔离）
            neuser_id: 系统用户ID（第2层隔离）
            user_id: 对话用户ID（第3层隔离）
            
        Returns:
            UnifiedRecallResult: 统一检索结果
        """
        start_time = time.time()
        
        # 构建隔离键（用于缓存）
        isolation_key = f"{agent_id or 'default'}:{neuser_id or 'default'}:{user_id or 'default'}"
        
        # 1. 检查缓存
        if use_cache:
            cache_key = f"{query}:{intent}:{limit}:{isolation_key}"
            cached = self._get_from_cache(cache_key)
            if cached:
                logger.debug("缓存命中: %s", query[:50])
                return cached
        
        # 2. 尝试各级检索
        result = None
        
        # Level 0: 完整功能（NeRF + 6通道 + 肌肉记忆）
        try:
            result = self._retrieve_full(query, intent, limit, agent_id, neuser_id, user_id)
            source = "nerf" if self._use_nerf_fusion else "weighted"
        except Exception as e:
            logger.warning("Level 0 failed: %s", e)
            source = None
        
        # Level 1: 传统融合（加权求和 + 6通道 + 肌肉记忆）
        if result is None:
            try:
                result = self._retrieve_weighted(query, intent, limit)
                source = "weighted"
            except Exception as e:
                logger.warning("Level 1 failed: %s", e)
        
        # Level 2: 简单检索（文本通道 + 关键词匹配）
        if result is None:
            try:
                result = self._retrieve_simple(query, limit)
                source = "simple"
            except Exception as e:
                logger.warning("Level 2 failed: %s", e)
        
        # Level 3: 返回空结果
        if result is None:
            result = UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"error": "All retrieval levels failed"},
                source="fallback",
                confidence=0.0,
            )
            source = "fallback"
        
        # 3. 设置来源和元数据
        result.source = source
        result.metadata["query"] = query
        result.metadata["latency_ms"] = (time.time() - start_time) * 1000
        
        # 4. 缓存结果
        if use_cache and result.memories:
            self._set_cache(cache_key, result)
        
        return result
    
    def match_tool(self, user_input: str) -> UnifiedRecallResult:
        """
        工具记忆匹配
        
        用于工具选择决策。
        
        Args:
            user_input: 用户输入
            
        Returns:
            UnifiedRecallResult: 工具匹配结果
        """
        if self._tool_memory is None:
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"error": "ToolMemory not available"},
                source="tool",
                confidence=0.0,
            )
        
        try:
            tool_memory, decision = self._tool_memory.check_tool_memory(user_input)
            
            memories = []
            if tool_memory:
                memories.append({
                    "tool_name": tool_memory.get("tool_name", ""),
                    "confidence": tool_memory.get("confidence", 0.0),
                    "decision": decision,
                })
            
            return UnifiedRecallResult(
                memories=memories,
                scores={"tool": tool_memory.get("confidence", 0.0) if tool_memory else 0.0},
                metadata={"decision": decision},
                source="tool",
                confidence=tool_memory.get("confidence", 0.0) if tool_memory else 0.0,
            )
        except Exception as e:
            logger.error("工具记忆匹配失败: %s", e)
            return UnifiedRecallResult(
                memories=[],
                scores={},
                metadata={"error": str(e)},
                source="tool",
                confidence=0.0,
            )
    
    def get_related_memories(
        self,
        memory_id: str,
        max_depth: int = 2,
    ) -> UnifiedRecallResult:
        """
        获取关联记忆
        
        基于图谱关系检索关联记忆。
        
        Args:
            memory_id: 记忆ID
            max_depth: 最大遍历深度
            
        Returns:
            UnifiedRecallResult: 关联记忆结果
        """
        # TODO: 实现图谱关联检索
        return UnifiedRecallResult(
            memories=[],
            scores={},
            metadata={"memory_id": memory_id, "max_depth": max_depth},
            source="graph",
            confidence=0.0,
        )
    
    def search_by_emotion(
        self,
        emotion: str,
        limit: int = 10,
    ) -> UnifiedRecallResult:
        """
        按情感检索
        
        Args:
            emotion: 情感标签
            limit: 返回结果数量
            
        Returns:
            UnifiedRecallResult: 情感检索结果
        """
        # TODO: 实现情感检索
        return UnifiedRecallResult(
            memories=[],
            scores={},
            metadata={"emotion": emotion},
            source="emotion",
            confidence=0.0,
        )
    
    def clear_cache(self):
        """清空缓存"""
        self._cache.clear()
        logger.debug("检索缓存已清空")
    
    # ============ 内部方法 ============
    
    def _retrieve_full(
        self,
        query: str,
        intent,
        limit: int,
        agent_id: Optional[str] = None,
        neuser_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> UnifiedRecallResult:
        """Level 0: 完整检索（NeRF + 6通道 + 肌肉记忆）"""
        # 1. 并行检索（6通道 + 肌肉记忆）
        channel_results = None
        muscle_results = None
        
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {}
            
            # 通道检索（传递隔离上下文）
            if self._recall_engine:
                futures[executor.submit(
                    self._recall_engine.retrieve, query, limit,
                    agent_id=agent_id, neuser_id=neuser_id, user_id=user_id
                )] = "channel"
            
            # 肌肉记忆检索（传递隔离上下文）
            if self._muscle_memory:
                futures[executor.submit(
                    self._muscle_memory.match_by_query, query, limit,
                    agent_id=agent_id, neuser_id=neuser_id, user_id=user_id
                )] = "muscle"
            
            # 等待结果
            for future in as_completed(futures):
                result_type = futures[future]
                try:
                    result = future.result()
                    if result_type == "channel":
                        channel_results = result
                    elif result_type == "muscle":
                        muscle_results = result
                except Exception as e:
                    logger.warning("检索失败 (%s): %s", result_type, e)
        
        # 2. 融合策略选择
        memories = []
        scores = {}
        
        if channel_results:
            if self._use_nerf_fusion and self._volume_renderer:
                # NeRF体渲染融合
                try:
                    rendered = self._volume_renderer.render(
                        channel_results, str(intent), limit
                    )
                    memories = self._rendered_to_dict(rendered)
                    source = "nerf"
                except Exception as e:
                    logger.warning("NeRF融合失败: %s", e)
                    memories = self._channel_to_dict(channel_results, limit)
                    source = "weighted"
            else:
                # 传统加权求和
                memories = self._channel_to_dict(channel_results, limit)
                source = "weighted"
        
        # 3. 合并肌肉记忆结果
        if muscle_results:
            muscle_memories = self._muscle_to_dict(muscle_results)
            memories = self._merge_memories(memories, muscle_memories)
        
        # 4. 构建统一结果
        return UnifiedRecallResult(
            memories=memories[:limit],
            scores=scores,
            metadata={"fusion_mode": "nerf" if self._use_nerf_fusion else "weighted"},
            source="nerf" if self._use_nerf_fusion else "weighted",
            confidence=self._calculate_confidence(memories),
        )
    
    def _retrieve_weighted(
        self,
        query: str,
        intent,
        limit: int,
        agent_id: Optional[str] = None,
        neuser_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> UnifiedRecallResult:
        """Level 1: 传统融合（加权求和）"""
        if not self._recall_engine:
            raise ValueError("RecallEngine not available")
        
        result = self._recall_engine.retrieve(query, limit, agent_id=agent_id, neuser_id=neuser_id, user_id=user_id)
        memories = self._channel_to_dict(result, limit)
        
        return UnifiedRecallResult(
            memories=memories,
            scores={},
            metadata={"fusion_mode": "weighted"},
            source="weighted",
            confidence=self._calculate_confidence(memories),
        )
    
    def _retrieve_simple(
        self,
        query: str,
        limit: int,
        agent_id: Optional[str] = None,
        neuser_id: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> UnifiedRecallResult:
        """Level 2: 简单检索（文本通道）"""
        if not self._recall_engine:
            raise ValueError("RecallEngine not available")
        
        # 只使用文本通道
        try:
            result = self._recall_engine._channel_text(query, limit)
            memories = self._simple_to_dict(result, limit)
            
            return UnifiedRecallResult(
                memories=memories,
                scores={"text": 1.0},
                metadata={"mode": "simple_text"},
                source="simple",
                confidence=self._calculate_confidence(memories),
            )
        except Exception as e:
            raise ValueError(f"Simple retrieval failed: {e}")
    
    def _get_from_cache(self, key: str) -> Optional[UnifiedRecallResult]:
        """从缓存获取"""
        if key in self._cache:
            result, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return result
            else:
                del self._cache[key]
        return None
    
    def _set_cache(self, key: str, result: UnifiedRecallResult):
        """设置缓存"""
        self._cache[key] = (result, time.time())
        # 简单清理：超过100条时清理一半
        if len(self._cache) > 100:
            sorted_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k][1]
            )
            for k in sorted_keys[:50]:
                del self._cache[k]
    
    def _rendered_to_dict(self, rendered: List) -> List[Dict[str, Any]]:
        """渲染结果转字典"""
        memories = []
        for item in rendered:
            memories.append({
                "memory_id": getattr(item, "memory_id", ""),
                "content": getattr(item, "content", ""),
                "score": getattr(item, "score", 0.0),
                "source": "nerf",
            })
        return memories
    
    def _channel_to_dict(self, channel_results, limit: int) -> List[Dict[str, Any]]:
        """通道结果转字典"""
        memories = []
        if hasattr(channel_results, "memories"):
            for mem in channel_results.memories[:limit]:
                memories.append({
                    "memory_id": getattr(mem, "memory_id", ""),
                    "content": getattr(mem, "content", ""),
                    "score": getattr(mem, "score", 0.0),
                    "source": "channel",
                })
        return memories
    
    def _muscle_to_dict(self, muscle_results: List) -> List[Dict[str, Any]]:
        """肌肉记忆结果转字典"""
        memories = []
        for item, confidence in muscle_results:
            memories.append({
                "memory_id": getattr(item, "id", ""),
                "content": getattr(item, "content", ""),
                "score": confidence,
                "source": "muscle",
            })
        return memories
    
    def _simple_to_dict(self, results: List, limit: int) -> List[Dict[str, Any]]:
        """简单结果转字典"""
        memories = []
        for item in results[:limit]:
            if isinstance(item, dict):
                memories.append(item)
            else:
                memories.append({
                    "memory_id": getattr(item, "memory_id", ""),
                    "content": getattr(item, "content", ""),
                    "score": getattr(item, "score", 0.0),
                    "source": "simple",
                })
        return memories
    
    def _merge_memories(
        self,
        primary: List[Dict],
        secondary: List[Dict],
    ) -> List[Dict[str, Any]]:
        """合并记忆列表"""
        # 简单合并，去重
        seen_ids = set()
        merged = []
        
        for mem in primary:
            mid = mem.get("memory_id", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                merged.append(mem)
        
        for mem in secondary:
            mid = mem.get("memory_id", "")
            if mid and mid not in seen_ids:
                seen_ids.add(mid)
                merged.append(mem)
        
        return merged
    
    def _calculate_confidence(self, memories: List[Dict]) -> float:
        """计算整体置信度"""
        if not memories:
            return 0.0
        
        scores = [m.get("score", 0.0) for m in memories]
        return sum(scores) / len(scores) if scores else 0.0


# 全局单例
_facade_instance: Optional[MemoryRetrievalFacade] = None


def get_memory_retrieval_facade(
    recall_engine=None,
    volume_renderer=None,
    muscle_memory=None,
    tool_memory=None,
    **kwargs,
) -> MemoryRetrievalFacade:
    """
    获取记忆检索门面单例
    
    Args:
        recall_engine: NeurovaRecallEngine实例
        volume_renderer: VolumeRenderer实例
        muscle_memory: MuscleMemory实例
        tool_memory: ToolMemoryIntegration实例
        
    Returns:
        MemoryRetrievalFacade: 门面实例
    """
    global _facade_instance
    if _facade_instance is None:
        _facade_instance = MemoryRetrievalFacade(
            recall_engine=recall_engine,
            volume_renderer=volume_renderer,
            muscle_memory=muscle_memory,
            tool_memory=tool_memory,
            **kwargs,
        )
    return _facade_instance


def reset_memory_retrieval_facade():
    """重置门面单例（用于测试）"""
    global _facade_instance
    _facade_instance = None
