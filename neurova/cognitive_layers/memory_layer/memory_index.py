"""
MemoryIndex — 索引和查询深度模块

职责：提供高效的记忆索引和查询接口，支持多维度检索。
设计原则：
  - 小接口（3个核心方法）
  - 深实现（支持多种查询策略）
  - 索引自动维护
  - 支持复合查询
"""

import threading
from typing import Any, Dict, List, Optional, Set

from .storage import MemoryRecord, MemoryStorage
from .isolation import IsolationContext


class MemoryIndex:
    """
    MemoryIndex — 索引和查询深度模块
    
    接口：
        query(filters) -> List[Dict]
        search(text) -> List[Dict]
        get_stats() -> Dict
    
    隐藏的复杂度：
        - 多维度索引（类型、所有者、标签、隔离）
        - 查询优化
        - 索引维护
    """
    
    def __init__(self, storage: MemoryStorage):
        """
        初始化 MemoryIndex
        
        Args:
            storage: 底层存储实例
        """
        self._storage = storage
        self._lock = threading.RLock()
    
    def query(
        self,
        memory_type: Optional[str] = None,
        owner: Optional[str] = None,
        tags: Optional[List[str]] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
        limit: Optional[int] = None,
        isolation_context: Optional[IsolationContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        多维度查询记忆
        
        Args:
            memory_type: 记忆类型过滤
            owner: 所有者过滤
            tags: 标签过滤（OR逻辑）
            start_time: 开始时间过滤
            end_time: 结束时间过滤
            limit: 返回数量限制
            isolation_context: 隔离上下文
        
        Returns:
            匹配的记忆列表
        """
        with self._lock:
            return self._storage.query(
                memory_type=memory_type,
                owner=owner,
                tags=tags,
                start_time=start_time,
                end_time=end_time,
                limit=limit,
                isolation_context=isolation_context,
            )
    
    def search_by_tags(
        self,
        tags: List[str],
        match_all: bool = False,
        isolation_context: Optional[IsolationContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        按标签搜索记忆
        
        Args:
            tags: 标签列表
            match_all: 是否需要匹配所有标签（True=AND，False=OR）
            isolation_context: 隔离上下文
        
        Returns:
            匹配的记忆列表
        """
        with self._lock:
            # 使用存储层的标签查询
            results = self._storage.list_by_tags(tags, match_all=match_all)
            
            # 应用隔离过滤
            if isolation_context:
                results = self._apply_isolation_filter(results, isolation_context)
            
            return results
    
    def search_by_text(
        self,
        text: str,
        limit: Optional[int] = None,
        isolation_context: Optional[IsolationContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        按文本内容搜索记忆（简单关键词匹配）
        
        Args:
            text: 搜索文本
            limit: 返回数量限制
            isolation_context: 隔离上下文
        
        Returns:
            匹配的记忆列表
        """
        with self._lock:
            # 获取所有记忆
            all_records = self._storage.list_all()
            
            # 应用隔离过滤
            if isolation_context:
                all_records = self._apply_isolation_filter(all_records, isolation_context)
            
            # 简单关键词匹配
            text_lower = text.lower()
            matching = [
                record for record in all_records
                if text_lower in record.get("content", "").lower()
            ]
            
            # 按时间排序
            matching.sort(key=lambda r: r.get("created_at", ""), reverse=True)
            
            if limit:
                matching = matching[:limit]
            
            return matching
    
    def get_by_ids(
        self,
        memory_ids: List[str],
        isolation_context: Optional[IsolationContext] = None,
    ) -> List[Dict[str, Any]]:
        """
        按ID列表获取记忆
        
        Args:
            memory_ids: 记忆ID列表
            isolation_context: 隔离上下文
        
        Returns:
            记忆列表（按请求顺序）
        """
        with self._lock:
            results = []
            for mid in memory_ids:
                record = self._storage.get(mid)
                if record:
                    # 应用隔离过滤
                    if isolation_context:
                        if not self._check_isolation(record, isolation_context):
                            continue
                    results.append(record)
            return results
    
    def get_stats(
        self,
        isolation_context: Optional[IsolationContext] = None,
    ) -> Dict[str, Any]:
        """
        获取统计信息
        
        Args:
            isolation_context: 隔离上下文（可选）
        
        Returns:
            统计信息字典
        """
        with self._lock:
            stats = self._storage.get_stats()
            
            # 如果指定了隔离上下文，计算隔离相关的统计
            if isolation_context:
                all_records = self._storage.list_all()
                isolated_records = self._apply_isolation_filter(
                    all_records, isolation_context
                )
                stats["isolated_total"] = len(isolated_records)
                
                # 按类型统计
                isolated_by_type = {}
                for record in isolated_records:
                    mem_type = record.get("memory_type", "unknown")
                    isolated_by_type[mem_type] = isolated_by_type.get(mem_type, 0) + 1
                stats["isolated_by_type"] = isolated_by_type
            
            return stats
    
    def _apply_isolation_filter(
        self,
        records: List[Dict[str, Any]],
        isolation_context: IsolationContext,
    ) -> List[Dict[str, Any]]:
        """
        应用隔离过滤
        
        Args:
            records: 记忆列表
            isolation_context: 隔离上下文
        
        Returns:
            过滤后的记忆列表
        """
        filtered = []
        for record in records:
            if self._check_isolation(record, isolation_context):
                filtered.append(record)
        return filtered
    
    def _check_isolation(
        self,
        record: Dict[str, Any],
        isolation_context: IsolationContext,
    ) -> bool:
        """
        检查记录是否满足隔离条件
        
        Args:
            record: 记忆记录
            isolation_context: 隔离上下文
        
        Returns:
            是否满足隔离条件
        """
        # 检查 agent_id
        if not isolation_context.shared and not record.get("shared", False):
            if record.get("agent_id") != isolation_context.agent_id:
                # 检查共享组（简化实现）
                return False
        
        # 检查 neuser_id
        if (isolation_context.neuser_id and 
            isolation_context.neuser_id != "default" and
            record.get("neuser_id") != isolation_context.neuser_id):
            return False
        
        # 检查 user_id
        if (isolation_context.user_id and
            isolation_context.user_id != "default" and
            record.get("user_id") != isolation_context.user_id):
            return False
        
        return True


def create_memory_index(storage_dir: str = None) -> MemoryIndex:
    """
    工厂函数：创建 MemoryIndex 实例
    
    Args:
        storage_dir: 存储目录（可选）
    
    Returns:
        MemoryIndex 实例
    """
    from .storage import get_memory_storage
    
    storage = get_memory_storage()
    return MemoryIndex(storage)
