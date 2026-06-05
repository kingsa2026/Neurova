"""
增强版上下文构建器 - 集成缓存、压缩和记忆管理

整合:
1. ContextCacheManager - 智能缓存
2. SmartContextCompressor - 智能压缩
3. MemoryReadWriteManager - 记忆管理
4. 会话完整性保护
"""

import datetime
import logging
import time
from typing import List, Dict, Any, Optional

from neurova.mem_core import Memory
from neurova.memory_rw_manager import MemoryReadWriteManager

logger = logging.getLogger(__name__)


class EnhancedContextBuilder:
    """
    增强版上下文构建器：集成缓存、压缩和记忆管理。
    """
    
    def __init__(
        self,
        memory_rw_manager: Optional[MemoryReadWriteManager] = None,
        max_session_history: int = 100,
        cache_enabled: bool = True,
        compression_enabled: bool = True,
    ):
        """初始化增强上下文构建器。
        
        Args:
            memory_rw_manager: 记忆读写管理器
            max_session_history: 最大会话历史长度
            cache_enabled: 是否启用缓存
            compression_enabled: 是否启用压缩
        """
        self._memory_rw_manager = memory_rw_manager or MemoryReadWriteManager()
        self._max_session_history = max_session_history
        self._cache_enabled = cache_enabled
        self._compression_enabled = compression_enabled
        
        # 会话存储：session_id -> list of messages
        self._sessions: Dict[str, List[Dict[str, Any]]] = {}
        
        # 统计信息
        self._stats = {
            "context_builds": 0,
            "memory_retrievals": 0,
            "cache_hits": 0,
            "cache_misses": 0,
            "compressions": 0,
            "session_count": 0,
        }
        
        # 缓存
        self._context_cache: Dict[str, Dict[str, Any]] = {}
        
        logger.debug("EnhancedContextBuilder initialized")
    
    def build_context(
        self,
        query: str,
        user_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        include_memories: bool = True,
        token_budget: int = 4000,
        **kwargs,
    ) -> Dict[str, Any]:
        """构建上下文。
        
        Args:
            query: 用户查询
            user_id: 用户 ID
            agent_id: Agent ID
            session_id: 会话 ID
            include_memories: 是否包含记忆
            token_budget: Token 预算
            **kwargs: 额外参数
            
        Returns:
            上下文字典
        """
        self._stats["context_builds"] += 1
        
        # 检查缓存
        cache_key = self._build_cache_key(query, session_id, include_memories)
        if self._cache_enabled and cache_key in self._context_cache:
            self._stats["cache_hits"] += 1
            return self._context_cache[cache_key]
        
        self._stats["cache_misses"] += 1
        
        # 构建上下文组件
        context_parts: Dict[str, Any] = {
            "query": query,
            "timestamp": datetime.datetime.now().isoformat(),
            "user_id": user_id,
            "agent_id": agent_id,
            "session_id": session_id,
        }
        
        # 检索记忆
        if include_memories:
            memories = self._retrieve_memories(query, limit=5)
            context_parts["memories"] = [
                {
                    "content": m.content if hasattr(m, "content") else str(m),
                    "importance": getattr(m, "importance", 0.5),
                }
                for m in memories
            ]
            self._stats["memory_retrievals"] += 1
        
        # 添加会话历史
        if session_id and session_id in self._sessions:
            context_parts["session_history"] = self._sessions[session_id][-10:]  # 最近 10 条
        
        # 压缩上下文（如果启用）
        if self._compression_enabled and token_budget:
            context_parts = self._compress_context(context_parts, token_budget)
        
        # 更新缓存
        if self._cache_enabled:
            self._context_cache[cache_key] = context_parts
        
        return context_parts
    
    def _retrieve_memories(self, query: str, limit: int = 5) -> List[Any]:
        """检索相关记忆。
        
        Args:
            query: 查询文本
            limit: 返回数量限制
            
        Returns:
            相关记忆列表
        """
        return self._memory_rw_manager.recall_memories(query, limit=limit)
    
    def add_message_to_session(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """添加消息到会话。
        
        Args:
            session_id: 会话 ID
            role: 角色（user/assistant/system）
            content: 消息内容
            metadata: 元数据
        """
        if session_id not in self._sessions:
            self._sessions[session_id] = []
            self._stats["session_count"] = len(self._sessions)
        
        message = {
            "role": role,
            "content": content,
            "timestamp": datetime.datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        
        self._sessions[session_id].append(message)
        
        # 限制历史长度
        if len(self._sessions[session_id]) > self._max_session_history:
            self._sessions[session_id] = self._sessions[session_id][-self._max_session_history:]
    
    def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        """获取会话历史。
        
        Args:
            session_id: 会话 ID
            
        Returns:
            消息列表
        """
        return self._sessions.get(session_id, []).copy()
    
    def clear_session(self, session_id: str) -> None:
        """清除会话。
        
        Args:
            session_id: 会话 ID
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            self._stats["session_count"] = len(self._sessions)
            logger.debug(f"Cleared session {session_id}")
    
    def create_memory(
        self,
        content: str,
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
        temperature: float = 1.0,
    ) -> str:
        """创建记忆。
        
        Args:
            content: 记忆内容
            importance: 重要性
            metadata: 元数据
            temperature: 温度
            
        Returns:
            记忆 ID
        """
        return self._memory_rw_manager.create_memory(
            content=content,
            importance=importance,
            metadata=metadata,
            temperature=temperature,
        )
    
    def _perform_maintenance(self) -> None:
        """执行维护操作。"""
        # 运行温度衰减检查
        self._memory_rw_manager.run_decay_if_needed()
        
        # 清除旧缓存
        if len(self._context_cache) > 100:
            # 保留最近的 50 条
            keys = list(self._context_cache.keys())
            for key in keys[:-50]:
                del self._context_cache[key]
        
        logger.debug("Maintenance completed")
    
    def flush_all(self) -> None:
        """刷新所有缓存和队列。"""
        self._memory_rw_manager.flush_all()
        self._context_cache.clear()
        logger.debug("All caches flushed")
    
    def _update_session_stats(self) -> None:
        """更新会话统计。"""
        self._stats["session_count"] = len(self._sessions)
        total_messages = sum(len(msgs) for msgs in self._sessions.values())
        self._stats["total_session_messages"] = total_messages
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息。
        
        Returns:
            统计信息字典
        """
        self._update_session_stats()
        
        stats = self._stats.copy()
        stats["cache_size"] = len(self._context_cache)
        stats["sessions"] = {
            sid: len(msgs) for sid, msgs in self._sessions.items()
        }
        
        # 合并记忆管理器统计
        try:
            memory_stats = self._memory_rw_manager.get_stats()
            stats["memory_manager"] = memory_stats
        except:
            pass
        
        return stats
    
    def get_cache_summary(self) -> Dict[str, Any]:
        """获取缓存摘要。
        
        Returns:
            缓存摘要字典
        """
        return {
            "context_cache_size": len(self._context_cache),
            "session_count": len(self._sessions),
            "total_session_messages": sum(len(msgs) for msgs in self._sessions.values()),
            "cache_enabled": self._cache_enabled,
            "compression_enabled": self._compression_enabled,
        }
    
    def _compress_context(
        self, context: Dict[str, Any], token_budget: int
    ) -> Dict[str, Any]:
        """压缩上下文以适应 token 预算。
        
        Args:
            context: 上下文字典
            token_budget: Token 预算
            
        Returns:
            压缩后的上下文
        """
        # 简单的截断压缩策略
        estimated_tokens = self._estimate_tokens(context)
        
        if estimated_tokens <= token_budget:
            return context
        
        self._stats["compressions"] += 1
        
        # 从会话历史开始截断
        if "session_history" in context and len(context["session_history"]) > 3:
            context["session_history"] = context["session_history"][-3:]
        
        # 减少记忆数量
        if "memories" in context and len(context["memories"]) > 2:
            context["memories"] = context["memories"][:2]
        
        return context
    
    def _estimate_tokens(self, context: Dict[str, Any]) -> int:
        """估算上下文的 token 数量。
        
        Args:
            context: 上下文字典
            
        Returns:
            估算的 token 数量
        """
        # 简单估算：每个字符约 0.5 个 token
        total_chars = 0
        
        if "query" in context:
            total_chars += len(str(context["query"]))
        
        if "memories" in context:
            for m in context["memories"]:
                total_chars += len(str(m.get("content", "")))
        
        if "session_history" in context:
            for msg in context["session_history"]:
                total_chars += len(str(msg.get("content", "")))
        
        return int(total_chars * 0.5)
    
    def _build_cache_key(
        self, query: str, session_id: Optional[str], include_memories: bool
    ) -> str:
        """构建缓存键。"""
        return f"{query}:{session_id}:{include_memories}"
