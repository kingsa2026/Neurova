"""
记忆读写管理器

核心特性:
1. 优先读缓存 - 减少数据库查询
2. 批量写入 - 定期刷新到存储
3. 记忆生命周期管理 - 创建、检索、更新、淘汰
4. 与上下文缓存集成 - 统一管理
5. 温度衰减调度 - 定期执行温度更新
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from neurova.mem_core import Memory

logger = logging.getLogger(__name__)


@dataclass
class MemoryOperation:
    """记忆操作记录。"""

    operation_type: str  # create, update, delete
    memory_id: str
    timestamp: float = field(default_factory=time.time)
    data: Dict[str, Any] = field(default_factory=dict)


class MemoryReadWriteManager:
    """
    记忆读写管理器：提供缓存、批量写入和温度衰减功能。
    """

    def __init__(
        self,
        batch_size: int = 10,
        decay_interval: float = 3600.0,  # 1 小时
        cache_size: int = 100,
        memory_manager: Optional[Any] = None,
    ):
        """初始化记忆读写管理器。

        Args:
            batch_size: 批量写入阈值
            decay_interval: 温度衰减间隔（秒）
            cache_size: 缓存大小
            memory_manager: 底层记忆管理器
        """
        self._batch_size = batch_size
        self._decay_interval = decay_interval
        self._cache_size = cache_size

        # 底层记忆管理器
        self._memory_manager = memory_manager

        # 写入队列
        self._write_queue: List[MemoryOperation] = []

        # 缓存
        self._cache: Dict[str, Memory] = {}

        # 统计信息
        self._cache_hits: int = 0
        self._cache_misses: int = 0

        # 上次衰减时间
        self._last_decay_time: float = time.time()

        # 回调函数
        self._on_batch_write: Optional[Callable] = None

        logger.debug("MemoryReadWriteManager initialized with batch_size=%s", batch_size)

    def recall_memories(self, query: str, limit: int = 10) -> List[Memory]:
        """检索记忆。

        Args:
            query: 查询文本
            limit: 返回数量限制

        Returns:
            相关记忆列表
        """
        # 先检查缓存
        cache_key = f"recall:{query}:{limit}"
        if cache_key in self._cache:
            self._cache_hits += 1
            return self._cache[cache_key]

        self._cache_misses += 1

        # 从底层管理器检索
        if self._memory_manager:
            results = self._memory_manager.search(query, limit=limit)
        else:
            # 模拟实现
            results = []

        # 更新缓存
        if len(self._cache) < self._cache_size:
            self._cache[cache_key] = results

        return results

    def get_memories(self, limit: int = 100, offset: int = 0) -> List[Memory]:
        """获取记忆列表。

        Args:
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            记忆列表
        """
        # 先检查缓存
        cache_key = f"get:{limit}:{offset}"
        if cache_key in self._cache:
            self._cache_hits += 1
            return self._cache[cache_key]

        self._cache_misses += 1

        # 从底层管理器获取
        if self._memory_manager:
            results = self._memory_manager.get_all(limit=limit, offset=offset)
        else:
            # 模拟实现
            results = []

        # 更新缓存
        if len(self._cache) < self._cache_size:
            self._cache[cache_key] = results

        return results

    def create_memory(
        self,
        content: str,
        importance: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
        temperature: float = 1.0,
    ) -> str:
        """创建新记忆。

        Args:
            content: 记忆内容
            importance: 重要性
            metadata: 元数据
            temperature: 温度

        Returns:
            记忆 ID
        """
        if self._memory_manager:
            memory_id = self._memory_manager.create(
                content=content,
                importance=importance,
                metadata=metadata or {},
                temperature=temperature,
            )
        else:
            # 模拟实现
            memory_id = f"memory_{int(time.time() * 1000)}"

        # 添加到写入队列
        operation = MemoryOperation(
            operation_type="create",
            memory_id=memory_id,
            data={
                "content": content,
                "importance": importance,
                "metadata": metadata or {},
                "temperature": temperature,
            },
        )
        self._write_queue.append(operation)

        # 检查是否需要批量写入
        self.batch_write_if_needed()

        logger.debug("Created memory %s", memory_id)
        return memory_id

    def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        importance: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
        temperature: Optional[float] = None,
    ) -> bool:
        """更新记忆。

        Args:
            memory_id: 记忆 ID
            content: 新内容
            importance: 新重要性
            metadata: 新元数据
            temperature: 新温度

        Returns:
            是否更新成功
        """
        if self._memory_manager:
            success = self._memory_manager.update(
                memory_id=memory_id,
                content=content,
                importance=importance,
                metadata=metadata,
                temperature=temperature,
            )
        else:
            # 模拟实现
            success = True

        if success:
            # 添加到写入队列
            operation = MemoryOperation(
                operation_type="update",
                memory_id=memory_id,
                data={
                    "content": content,
                    "importance": importance,
                    "metadata": metadata,
                    "temperature": temperature,
                },
            )
            self._write_queue.append(operation)

            # 清除相关缓存
            self._invalidate_cache(memory_id)

            logger.debug("Updated memory %s", memory_id)

        return success

    def delete_memory(self, memory_id: str) -> bool:
        """删除记忆。

        Args:
            memory_id: 记忆 ID

        Returns:
            是否删除成功
        """
        if self._memory_manager:
            success = self._memory_manager.delete(memory_id)
        else:
            # 模拟实现
            success = True

        if success:
            # 添加到写入队列
            operation = MemoryOperation(
                operation_type="delete",
                memory_id=memory_id,
            )
            self._write_queue.append(operation)

            # 清除相关缓存
            self._invalidate_cache(memory_id)

            logger.debug("Deleted memory %s", memory_id)

        return success

    def batch_write_if_needed(self) -> None:
        """检查是否需要批量写入。"""
        if len(self._write_queue) >= self._batch_size:
            self.batch_write()

    def batch_write(self) -> None:
        """批量写入队列中的操作。"""
        if not self._write_queue:
            return

        logger.debug("Batch writing %s operations", len(self._write_queue))

        # 按操作类型分组
        creates = []
        updates = []
        deletes = []

        for op in self._write_queue:
            if op.operation_type == "create":
                creates.append(op)
            elif op.operation_type == "update":
                updates.append(op)
            elif op.operation_type == "delete":
                deletes.append(op)

        # 执行批量操作
        if self._memory_manager:
            if creates:
                memories = [op.data for op in creates]
                self._memory_manager.batch_create(memories)

            for op in updates:
                self._memory_manager.update(op.memory_id, **op.data)

            for op in deletes:
                self._memory_manager.delete(op.memory_id)

        # 清空队列
        self._write_queue.clear()

        # 调用回调
        if self._on_batch_write:
            self._on_batch_write()

        logger.debug("Batch write completed")

    def run_decay_if_needed(self) -> None:
        """检查是否需要运行温度衰减。"""
        current_time = time.time()
        if current_time - self._last_decay_time >= self._decay_interval:
            self.run_decay_cycle()
            self._last_decay_time = current_time

    def run_decay_cycle(self) -> None:
        """运行温度衰减周期。"""
        logger.debug("Running temperature decay cycle")

        if not self._memory_manager:
            return

        # 获取所有记忆
        memories = self._memory_manager.get_all()

        current_time = time.time()
        decay_factor = 0.95  # 每小时衰减 5%

        for memory in memories:
            # 计算时间差（小时）
            time_diff_hours = (current_time - memory.last_accessed) / 3600.0

            # 应用衰减
            new_temperature = memory.temperature * (decay_factor**time_diff_hours)

            # 更新温度
            if new_temperature != memory.temperature:
                self._memory_manager.update(
                    memory_id=memory.id,
                    temperature=new_temperature,
                )

        logger.debug("Decay cycle completed for %s memories", len(memories))

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息。

        Returns:
            统计信息字典
        """
        total_requests = self._cache_hits + self._cache_misses
        cache_hit_rate = self._cache_hits / total_requests if total_requests > 0 else 0.0

        return {
            "queue_size": len(self._write_queue),
            "cache_size": len(self._cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "cache_hit_rate": cache_hit_rate,
            "last_decay_time": self._last_decay_time,
            "batch_size": self._batch_size,
            "decay_interval": self._decay_interval,
        }

    def flush_all(self) -> None:
        """清空所有缓存和队列。"""
        logger.debug("Flushing all caches and queues")

        # 批量写入队列中的操作
        if self._write_queue:
            self.batch_write()

        # 清空缓存
        self._cache.clear()

        # 重置统计
        self._cache_hits = 0
        self._cache_misses = 0

        logger.debug("Flush completed")

    def _invalidate_cache(self, memory_id: str) -> None:
        """清除与指定记忆相关的缓存。"""
        keys_to_remove = []
        for key in self._cache:
            if memory_id in key:
                keys_to_remove.append(key)

        for key in keys_to_remove:
            del self._cache[key]

    def __del__(self):
        """析构函数：确保队列被清空。"""
        try:
            if self._write_queue:
                self.batch_write()
        except:
            pass
