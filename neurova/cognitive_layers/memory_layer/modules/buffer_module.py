"""
BufferModule — 对话缓存 + 写入队列

包装 ConversationMemoryBuffer + MemoryWriteQueue，管理后台刷入线程
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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
        self._write_queue: List[Dict[str, Any]] = []
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
        with self._lock:
            if not self._buffer:
                return 0

            self._move_to_write_queue()

            # 执行写入队列
            if hasattr(self._write_queue, "flush_to_storage"):
                # 使用 MemoryWriteQueue 的批量写入
                count = self._write_queue.flush_to_storage()
            else:
                # 旧模式：清空列表
                count = len(self._write_queue)
                self._write_queue.clear()

            # 触发回调
            for callback in self._on_flush_callbacks:
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
        with self._lock:
            count = len(self._buffer) + len(self._write_queue)
            self._buffer.clear()
            self._write_queue.clear()
            return count

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {
                "buffer_size": len(self._buffer),
                "buffer_capacity": self._buffer_size,
                "write_queue_size": len(self._write_queue),
                "flush_interval": self._flush_interval,
                "auto_flush": self._auto_flush,
                "running": self._running,
            }

    def add_to_write_queue(self, item: Dict[str, Any]) -> None:
        """添加到写入队列"""
        with self._lock:
            self._write_queue.append(item)

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
                        id=item_dict.get("id", str(datetime.now().timestamp())),
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

                with self._lock:
                    if self._buffer:
                        self._move_to_write_queue()

                # 执行写入
                if self._write_queue:
                    self.flush()

            except Exception as e:
                logger.warning("Flush loop error: %s", e)

    def _on_external_write(self, data: Dict[str, Any]) -> None:
        """外部写入事件处理"""
        # 可以在这里处理外部写入通知
