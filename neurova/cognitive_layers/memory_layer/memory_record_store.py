"""
MemoryRecordStore — 纯CRUD深度模块

职责：提供简洁的记忆记录CRUD接口，隐藏存储实现细节。
设计原则：
  - 小接口（5个核心方法）
  - 深实现（支持JSON/SQLite/内存多种后端）
  - 线程安全
  - 隔离上下文支持
"""

import threading
from typing import Any, Dict, List, Optional

from .storage import MemoryRecord, MemoryStorage
from .isolation import IsolationContext


class MemoryRecordStore:
    """
    MemoryRecordStore — 纯CRUD深度模块
    
    接口：
        save(content, memory_type, ...) -> memory_id
        get(memory_id) -> Dict | None
        delete(memory_id) -> bool
        update(memory_id, **fields) -> bool
        count() -> int
    
    隐藏的复杂度：
        - 存储后端（JSON/SQLite）
        - 索引维护
        - 线程安全
        - 隔离上下文
    """
    
    def __init__(self, storage: MemoryStorage):
        """
        初始化 MemoryRecordStore
        
        Args:
            storage: 底层存储实例
        """
        self._storage = storage
        self._lock = threading.RLock()
    
    def save(
        self,
        content: str,
        memory_type: str,
        owner: str = "default",
        tags: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        importance: float = 0.0,
        isolation_context: Optional[IsolationContext] = None,
    ) -> str:
        """
        保存记忆记录
        
        Args:
            content: 记忆内容
            memory_type: 记忆类型（episodic/semantic/procedural等）
            owner: 所有者
            tags: 标签列表
            metadata: 元数据
            importance: 重要性分数（0.0-1.0）
            isolation_context: 隔离上下文（可选）
        
        Returns:
            memory_id: 生成的记忆ID
        """
        with self._lock:
            return self._storage.save(
                content=content,
                memory_type=memory_type,
                owner=owner,
                tags=tags,
                metadata=metadata,
                importance=importance,
                isolation_context=isolation_context,
            )
    
    def get(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        获取记忆记录
        
        Args:
            memory_id: 记忆ID
        
        Returns:
            记忆记录字典，不存在返回None
        """
        with self._lock:
            return self._storage.get(memory_id)
    
    def delete(self, memory_id: str) -> bool:
        """
        删除记忆记录
        
        Args:
            memory_id: 记忆ID
        
        Returns:
            是否删除成功
        """
        with self._lock:
            return self._storage.delete(memory_id)
    
    def update(self, memory_id: str, **fields: Any) -> bool:
        """
        更新记忆记录
        
        Args:
            memory_id: 记忆ID
            **fields: 要更新的字段
        
        Returns:
            是否更新成功
        """
        with self._lock:
            return self._storage.update_memory(memory_id, **fields)
    
    def count(self) -> int:
        """
        获取记忆总数
        
        Returns:
            记忆总数
        """
        with self._lock:
            return self._storage.count()
    
    def exists(self, memory_id: str) -> bool:
        """
        检查记忆是否存在
        
        Args:
            memory_id: 记忆ID
        
        Returns:
            是否存在
        """
        with self._lock:
            return self._storage.get(memory_id) is not None
    
    def batch_save(
        self,
        records: List[Dict[str, Any]],
        isolation_context: Optional[IsolationContext] = None,
    ) -> List[str]:
        """
        批量保存记忆记录
        
        Args:
            records: 记忆记录列表
            isolation_context: 隔离上下文（可选）
        
        Returns:
            生成的记忆ID列表
        """
        with self._lock:
            # 为每条记录添加隔离上下文
            for record in records:
                if isolation_context and "isolation_context" not in record:
                    record["isolation_context"] = isolation_context
            
            return self._storage.batch_save(records)
    
    def batch_delete(self, memory_ids: List[str]) -> int:
        """
        批量删除记忆记录
        
        Args:
            memory_ids: 记忆ID列表
        
        Returns:
            删除的数量
        """
        with self._lock:
            return self._storage.batch_delete(memory_ids)


def create_memory_record_store(storage_dir: str = None) -> MemoryRecordStore:
    """
    工厂函数：创建 MemoryRecordStore 实例
    
    Args:
        storage_dir: 存储目录（可选，默认使用配置目录）
    
    Returns:
        MemoryRecordStore 实例
    """
    from .storage import get_memory_storage
    
    storage = get_memory_storage()
    return MemoryRecordStore(storage)
