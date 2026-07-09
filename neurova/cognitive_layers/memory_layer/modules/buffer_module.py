"""
BufferModule — 对话缓存 + 写入队列

包装 ConversationMemoryBuffer + MemoryWriteQueue，管理后台刷入线程
"""

from __future__ import annotations

from neurova.core.logger import get_logger
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Union

logger = get_logger(__name__)


class BufferModule:
    """
    对话缓存模块

    管理对话缓冲区和写入队列，支持：
    - 实时对话缓存
    - 批量写入持久存储
    - 后台自动刷入
    """

    def __init__(
        self,
        buffer_size: int = 100,
        flush_interval: float = 30.0,
        auto_flush: bool = True,
    ):
        """
        Args:
            buffer_size: 缓冲区大小
            flush_interval: 自动刷入间隔（秒）
            auto_flush: 是否自动刷入
        """
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._auto_flush = auto_flush

        self._buffer: List[Dict[str, Any]] = []
        # BUG-11 修复: 类型注解与实际不符, 运行时可能持有 MemoryWriteQueue 实例
        self._write_queue: Union[List[Dict[str, Any]], Any] = []
        self._lock = threading.RLock()
        self._flush_thread: Optional[threading.Thread] = None
        self._running = False
        self._initialized = False

        # 事件回调
        self._on_flush_callbacks: List[Any] = []

    @property
    def name(self) -> str:
        """模块名称"""
        return "buffer_module"

    @property
    def buffer(self) -> List[Dict[str, Any]]:
        """当前缓冲区"""
        with self._lock:
            return list(self._buffer)

    @property
    def write_queue(self) -> List[Dict[str, Any]]:
        """写入队列"""
        with self._lock:
            # 如果 _write_queue 是 MemoryWriteQueue 实例，返回其队列内容
            if hasattr(self._write_queue, "_queue"):
                return list(self._write_queue._queue)
            else:
                return list(self._write_queue)

    def init(self) -> bool:
        """
        初始化模块

        Returns:
            是否初始化成功
        """
        if self._initialized:
            return True

        try:
            self._running = True

            if self._auto_flush:
                self._flush_thread = threading.Thread(target=self._flush_loop, daemon=True, name="buffer-flush")
                self._flush_thread.start()

            self._initialized = True
            logger.info("BufferModule initialized")
            return True

        except Exception as e:
            logger.error("Failed to initialize BufferModule: %s", e)
            return False

    def shutdown(self) -> None:
        """关闭模块"""
        self._running = False

        # 最后一次刷入
        self.flush()

        if self._flush_thread and self._flush_thread.is_alive():
            self._flush_thread.join(timeout=5.0)

        self._initialized = False
        logger.info("BufferModule shutdown")

    def add_turn(
        self,
        role: str,
        content: str,
        agent_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        添加对话轮次

        Args:
            role: 角色 (user/assistant)
            content: 内容
            agent_id: Agent ID
            metadata: 额外元数据
        """
        with self._lock:
            turn = {
                "role": role,
                "content": content,
                "agent_id": agent_id,
                "timestamp": time.time(),
                "metadata": metadata or {},
            }

            self._buffer.append(turn)

            # 如果缓冲区满了，触发刷入
            if len(self._buffer) >= self._buffer_size:
                self._move_to_write_queue()

    def flush(self) -> int:
        """
        手动刷入

        Returns:
            刷入的条目数
        """
        # BUG-7 修复: 锁内只做 _move_to_write_queue 复制,
        # 释放锁后再调 flush_to_storage (SQLite I/O), 避免 add_turn 被阻塞
        # BUG-8 修复: 锁内复制回调列表, 释放锁后再遍历, 避免慢回调长时间持锁
        with self._lock:
            if not self._buffer:
                return 0

            self._move_to_write_queue()

            # 锁内获取 write_queue 引用(不持有锁做 I/O)
            write_queue = self._write_queue

            # 锁内复制回调列表, 释放锁后遍历
            callbacks = list(self._on_flush_callbacks)

        # 执行写入队列 (锁外, 避免阻塞 add_turn)
        if hasattr(write_queue, "flush_to_storage"):
            # 使用 MemoryWriteQueue 的批量写入
            count = write_queue.flush_to_storage()
        else:
            # 旧模式：清空列表
            count = len(write_queue)
            # BUG-7: 清空操作需要重新获取锁(与 add_turn/_move_to_write_queue 互斥)
            with self._lock:
                write_queue.clear()

        # 触发回调 (锁外执行, 避免慢回调阻塞 add_turn)
        for callback in callbacks:
            try:
                callback(count)
            except Exception as e:
                logger.warning("Flush callback failed: %s", e)

        return count

    def clear(self) -> int:
        """
        清空缓冲区

        Returns:
            清除的条目数
        """
        # BUG-11 修复: clear() 先设置 _running=False 阻止后台 flush_thread 继续写入,
        # 再清空数据, 避免 clear 后 flush_thread 把数据写回
        self._running = False

        with self._lock:
            # Bug C-5 修复：_write_queue 可能是 List 或 MemoryWriteQueue
            # MemoryWriteQueue 无 __len__/clear，需类型分支处理
            buffer_count = len(self._buffer)
            if hasattr(self._write_queue, "_queue"):
                # MemoryWriteQueue 实例
                queue_count = len(self._write_queue._queue)
                self._write_queue._queue.clear()
            else:
                # List 实例
                queue_count = len(self._write_queue)
                self._write_queue.clear()
            count = buffer_count + queue_count
            self._buffer.clear()
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            # Bug C-5 修复：_write_queue 可能是 MemoryWriteQueue
            if hasattr(self._write_queue, "_queue"):
                write_queue_size = len(self._write_queue._queue)
            else:
                write_queue_size = len(self._write_queue)
            return {
                "buffer_size": len(self._buffer),
                "buffer_capacity": self._buffer_size,
                "write_queue_size": write_queue_size,
                "flush_interval": self._flush_interval,
                "auto_flush": self._auto_flush,
                "running": self._running,
            }

    def add_to_write_queue(self, item: Dict[str, Any]) -> bool:
        """添加到写入队列

        注：若 _write_queue 是 MemoryWriteQueue，应通过 add_turn + flush 流程
        此方法仅兼容旧 List 模式，新模式下发出警告并返回 False

        Returns:
            bool: True 表示成功添加; False 表示不支持(MemoryWriteQueue 模式)
        """
        # BUG-10 修复: MemoryWriteQueue 模式下返回 False 而非静默忽略 None,
        # 使调用方有感知
        with self._lock:
            # Bug C-5 修复：_write_queue 可能是 MemoryWriteQueue（无 append 方法）
            if hasattr(self._write_queue, "enqueue_batch"):
                # MemoryWriteQueue 实例：Dict 项无法直接 enqueue（需 MemoryItem）
                logger.warning("add_to_write_queue 不支持 MemoryWriteQueue 模式，请用 add_turn + flush")
                return False
            else:
                # List 实例
                self._write_queue.append(item)
                return True

    def _move_to_write_queue(self) -> None:
        """将缓冲区内容移动到写入队列"""
        # 如果 _write_queue 是 MemoryWriteQueue 实例，需要转换格式
        if hasattr(self._write_queue, "enqueue_batch"):
            # 将 Dict 转换为 MemoryItem 对象
            from datetime import datetime

            from neurova.cognitive_layers.memory_layer.conversation_buffer import MemoryItem

            items = []
            for item_dict in self._buffer:
                if isinstance(item_dict, dict):
                    # 从字典创建 MemoryItem
                    metadata = item_dict.get("metadata", {})
                    classification = metadata.get("classification", "conversation")
                    categories = metadata.get("categories", ["conversation"])
                    meta_trace = metadata.get("meta_trace")

                    # 处理时间戳
                    ts = item_dict.get("timestamp")
                    if isinstance(ts, (int, float)):
                        timestamp = datetime.fromtimestamp(ts)
                    elif isinstance(ts, datetime):
                        timestamp = ts
                    else:
                        timestamp = datetime.now()

                    item = MemoryItem(
                        # BUG-9 修复: 原用 str(datetime.now().timestamp()) 同秒碰撞,
                        # 改用 uuid.uuid4().hex 保证唯一性
                        id=item_dict.get("id", uuid.uuid4().hex),
                        content=item_dict.get("content", ""),
                        timestamp=timestamp,
                        classification=classification,
                        emotion_analysis=item_dict.get("emotion_analysis"),
                        categories=categories,
                        meta_trace=meta_trace,
                    )
                    items.append(item)
                else:
                    # 已经是 MemoryItem
                    items.append(item_dict)

            self._write_queue.enqueue_batch(items)
        else:
            # 旧模式：直接扩展列表
            self._write_queue.extend(self._buffer)

        self._buffer.clear()

    def _flush_loop(self) -> None:
        """后台刷入循环"""
        while self._running:
            try:
                time.sleep(self._flush_interval)

                if not self._running:
                    break

                # BUG-6 修复: 原 TOCTOU 竞态 — with self._lock 内 _move_to_write_queue,
                # 释放锁后 if self._write_queue: 无锁访问, 可能被 clear() 清空导致漏数据。
                # 修复: 将 _write_queue 检查移入锁内, 释放锁后再调 flush()
                with self._lock:
                    if self._buffer:
                        self._move_to_write_queue()
                    has_queue = bool(self._write_queue)

                # 执行写入 (锁外, 避免阻塞 add_turn)
                if has_queue:
                    self.flush()

            except Exception as e:
                logger.warning("Flush loop error: %s", e)

    def _on_external_write(self, data: Dict[str, Any]) -> None:
        """外部写入事件处理"""
        # 可以在这里处理外部写入通知
