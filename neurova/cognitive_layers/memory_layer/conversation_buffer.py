"""
对话缓冲区模块

提供对话记忆的临时存储和批量写入功能。
支持：
- 对话历史缓冲
- 批量写入队列
- 内存限制和轮次限制
- 情感分析集成
"""

import threading

from neurova.core.logger import get_logger
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# BUG-2 修复: 引入 MemoryType 用于验证 classification 合法性
from neurova.cognitive_layers.memory_layer.models import MemoryType

logger = get_logger(__name__)


@dataclass
class MemoryItem:
    """内存项"""

    id: str
    content: str
    timestamp: datetime
    classification: str = "conversation"
    emotion_analysis: Optional[Dict[str, Any]] = None
    categories: List[str] = field(default_factory=list)
    meta_trace: Optional[Dict[str, Any]] = None


@dataclass
class ConversationTurn:
    """对话轮次"""

    user_message: str
    agent_message: str
    timestamp: datetime
    is_complete: bool = True


class ConversationBuffer:
    """对话缓冲区

    提供对话历史的临时存储，支持：
    - 内存限制（字节数）
    - 轮次限制
    - 超时自动刷新
    """

    def __init__(self, memory_limit_bytes: int = 131072, turn_limit: int = 20, timeout_seconds: int = 180):  # 128KB
        """初始化对话缓冲区

        Args:
            memory_limit_bytes: 内存限制（字节）
            turn_limit: 轮次限制
            timeout_seconds: 超时时间（秒）
        """
        self.memory_limit_bytes = memory_limit_bytes
        self.turn_limit = turn_limit
        self.timeout_seconds = timeout_seconds

        self._buffer: deque[MemoryItem] = deque()
        self._turns: List[ConversationTurn] = []
        self._current_turn: Optional[ConversationTurn] = None
        self._last_flush_time = datetime.now()
        self._total_bytes = 0
        self._lock = threading.RLock()  # 断点 M-3 修复: 保护 _buffer/_turns/_current_turn 并发访问

        logger.debug(
            f"ConversationBuffer 初始化: memory_limit={memory_limit_bytes}, "
            f"turn_limit={turn_limit}, timeout={timeout_seconds}"
        )

    def add_user_message(self, message: str) -> bool:
        """添加用户消息

        Args:
            message: 用户消息

        Returns:
            bool: 是否成功添加
        """
        try:
            # 创建内存项(不涉及共享状态, 锁外创建)
            item = MemoryItem(
                id=f"user_{datetime.now().timestamp()}",
                content=message,
                timestamp=datetime.now(),
                classification="user_message",
            )

            # 断点 M-3 修复: 用 RLock 保护 _buffer/_total_bytes/_current_turn 并发访问
            with self._lock:
                # 添加到缓冲区
                self._buffer.append(item)
                self._total_bytes += len(message.encode("utf-8"))

                # 更新当前轮次
                if self._current_turn is None:
                    self._current_turn = ConversationTurn(
                        user_message=message, agent_message="", timestamp=datetime.now(), is_complete=False
                    )
                else:
                    self._current_turn.user_message = message

            logger.debug("添加用户消息: %s 字节", len(message))
            return True

        except Exception as e:
            logger.error("添加用户消息失败: %s", e)
            return False

    def add_agent_message(self, message: str) -> bool:
        """添加AI回复消息

        Args:
            message: AI回复消息

        Returns:
            bool: 是否成功添加
        """
        try:
            # 创建内存项(不涉及共享状态, 锁外创建)
            item = MemoryItem(
                id=f"agent_{datetime.now().timestamp()}",
                content=message,
                timestamp=datetime.now(),
                classification="agent_message",
            )

            # 断点 M-3 修复: 用 RLock 保护 _buffer/_total_bytes/_current_turn/_turns 并发访问
            with self._lock:
                # 添加到缓冲区
                self._buffer.append(item)
                self._total_bytes += len(message.encode("utf-8"))

                # 更新当前轮次
                if self._current_turn is not None:
                    self._current_turn.agent_message = message
                    self._current_turn.is_complete = True

                    # 保存完成的轮次
                    self._turns.append(self._current_turn)
                    self._current_turn = None

            logger.debug("添加AI消息: %s 字节", len(message))
            return True

        except Exception as e:
            logger.error("添加AI消息失败: %s", e)
            return False

    def is_full(self) -> bool:
        """检查缓冲区是否已满

        Returns:
            bool: 缓冲区是否已满
        """
        # BUG 5 修复: 读取 _total_bytes/_turns/_last_flush_time 必须持有 _lock,
        # 与 add_user_message/add_agent_message/flush 的写入方保持互斥, 避免数据竞争。
        with self._lock:
            # 检查内存限制
            if self._total_bytes >= self.memory_limit_bytes:
                return True

            # 检查轮次限制
            if len(self._turns) >= self.turn_limit:
                return True

            # 检查超时
            time_since_flush = (datetime.now() - self._last_flush_time).total_seconds()
            if time_since_flush >= self.timeout_seconds:
                return True

            return False

    def flush(self) -> List[MemoryItem]:
        """刷新缓冲区，返回所有内存项

        Returns:
            List[MemoryItem]: 内存项列表
        """
        # 断点 M-3 修复: 用 RLock 保护清空操作, 避免与 add_*_message 并发 race
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
            self._turns.clear()
            self._current_turn = None
            self._total_bytes = 0
            self._last_flush_time = datetime.now()

        logger.debug("刷新缓冲区: %s 个项目", len(items))
        return items

    def get_stats(self) -> Dict[str, Any]:
        """获取缓冲区统计信息

        Returns:
            Dict[str, Any]: 统计信息
        """
        # BUG 6 修复: 读取 _buffer/_total_bytes/_turns/_current_turn/_last_flush_time
        # 必须持有 _lock, 与写入方保持互斥, 避免数据竞争。
        with self._lock:
            return {
                "buffer_size": len(self._buffer),
                "total_bytes": self._total_bytes,
                "memory_limit_bytes": self.memory_limit_bytes,
                "turn_limit": self.turn_limit,
                "timeout_seconds": self.timeout_seconds,
                "current_turns": len(self._turns),
                "has_current_turn": self._current_turn is not None,
                "last_flush_time": self._last_flush_time.isoformat(),
            }


class MemoryWriteQueue:
    """内存写入队列

    提供批量写入和验证功能
    """

    def __init__(self, storage=None, agent_id: str = None, memory_manager=None):
        """初始化写入队列

        Args:
            storage: 内存存储实例 (CognitiveStorageEngine)
            agent_id: 代理ID
            memory_manager: 记忆管理器 (MemoryManager) 作为降级后端
        """
        self.storage = storage
        self.agent_id = agent_id
        self._memory_manager = memory_manager
        self._queue: List[MemoryItem] = []
        self._lock = threading.RLock()  # 断点 M-2 修复: 锁初始化为 RLock(原为 None, 无同步)

        logger.debug(
            f"MemoryWriteQueue 初始化: agent_id={agent_id}, storage={'有' if storage else '无'}, memory_manager={'有' if memory_manager else '无'}"
        )

    def __bool__(self) -> bool:
        """检查队列是否非空"""
        return len(self._queue) > 0

    def enqueue(self, item: MemoryItem) -> bool:
        """添加项目到队列

        Args:
            item: 内存项

        Returns:
            bool: 是否成功添加
        """
        try:
            # 断点 M-2 修复: 用 RLock 保护 _queue 并发访问
            with self._lock:
                self._queue.append(item)
            logger.debug("添加项目到队列: %s", item.id)
            return True
        except Exception as e:
            logger.error("添加项目到队列失败: %s", e)
            return False

    def enqueue_batch(self, items: List[MemoryItem]) -> bool:
        """批量添加项目到队列

        Args:
            items: 内存项列表

        Returns:
            bool: 是否成功添加
        """
        try:
            # 断点 M-2 修复: 用 RLock 保护 _queue 批量写入
            with self._lock:
                self._queue.extend(items)
            logger.debug("批量添加项目到队列: %s 个项目", len(items))
            return True
        except Exception as e:
            logger.error("批量添加项目到队列失败: %s", e)
            return False

    def flush_to_storage(self) -> int:
        """刷新队列到存储（批量写入 SQLite）

        Returns:
            int: 成功写入的项目数量
        """
        # 数据源统一（W2 修复）: 优先写入 memory_manager（recall 可读取的
        # persist.db）；痕迹库 storage 只存不取，仅作无 manager 时的降级。
        # 原逻辑优先 storage 导致批量对话记忆进入无人检索的 JSON 库，
        # 且与 _step_save_memory 的直接 remember 形成双写分裂。
        storage = self.storage
        memory_manager = getattr(self, "_memory_manager", None)

        if not storage and not memory_manager:
            logger.warning("存储和记忆管理器均不可用，无法刷新队列")
            return 0

        written = 0
        errors = 0
        # 断点 M-2 修复: 用 RLock 保护"复制+清空"原子操作
        # 避免复制后清空前其他线程 enqueue 导致新数据丢失
        # BUG-10 修复: 原空队列检查在锁外 (TOCTOU race),
        # 检查后到获取锁之间队列可能被其他线程修改。现移入锁内。
        with self._lock:
            if not self._queue:
                return 0
            items_to_write = list(self._queue)  # 复制一份，避免写入过程中修改
            self._queue.clear()

        for item in items_to_write:
            try:
                content = item.content if hasattr(item, "content") else str(item.get("content", ""))
                if not content:
                    continue

                # 提取分类信息
                # BUG-2 修复: classification 可能是 "user_message"/"agent_message"
                # 等非法 MemoryType 枚举值, 传给 storage.save 会破坏下游枚举解析。
                # 修复: 非法值 fallback 到 EPISODIC(对话记忆), 原值保存在
                # metadata._original_classification 供回溯。
                raw_classification = getattr(item, "classification", None) or (
                    item.get("classification", "conversation") if isinstance(item, dict) else "conversation"
                )
                # 合法枚举值集合
                _valid_types = {mt.value for mt in MemoryType}
                if raw_classification in _valid_types:
                    classification = raw_classification
                else:
                    classification = MemoryType.EPISODIC.value
                categories = getattr(item, "categories", None) or (
                    item.get("categories", []) if isinstance(item, dict) else []
                )
                category = categories[0] if categories else classification or "conversation"

                # 提取元数据
                metadata = {}
                # BUG-2 修复: 非法分类原值保存在 metadata._original_classification
                if raw_classification != classification:
                    metadata["_original_classification"] = raw_classification
                meta_trace = getattr(item, "meta_trace", None) or (
                    item.get("meta_trace", None) if isinstance(item, dict) else None
                )
                if meta_trace:
                    metadata["meta_trace"] = meta_trace

                # 添加时间戳
                timestamp = getattr(item, "timestamp", None) or (
                    item.get("timestamp", None) if isinstance(item, dict) else None
                )
                if timestamp:
                    if hasattr(timestamp, "isoformat"):
                        metadata["timestamp"] = timestamp.isoformat()
                    else:
                        metadata["timestamp"] = str(timestamp)

                # 写入 MemoryManager（recall 主数据源）
                if memory_manager and hasattr(memory_manager, "remember"):
                    memory_manager.remember(
                        content=content,
                        memory_type=classification,
                        category=category,
                        metadata=metadata,
                    )
                    written += 1
                # 降级写入痕迹库（无 manager 时唯一出口）
                elif storage and hasattr(storage, "save"):
                    storage.save(
                        content=content,
                        memory_type=classification,
                        owner=self.agent_id or "default",
                        tags=categories,
                        metadata=metadata,
                        importance=0.5,
                    )
                    written += 1

            except Exception as e:
                errors += 1
                logger.warning("写入单条记忆失败: %s", e)

        if written > 0:
            # Bug C-1 修复：原代码括号位置错误导致 str + tuple → TypeError
            # 错误写法: logger.info("...%s..." + (f"...%s..." if errors else "", written, errors))
            # 正确写法：errors > 0 时附加失败信息
            if errors > 0:
                logger.info("批量写入 %s 条记忆到存储，%s 条失败", written, errors)
            else:
                logger.info("批量写入 %s 条记忆到存储", written)
        elif errors > 0:
            logger.warning("批量写入全部失败: %s 条", errors)

        return written

    def verify_write(self, item: MemoryItem) -> bool:
        """验证写入是否成功

        Args:
            item: 内存项

        Returns:
            bool: 是否成功写入
        """
        # 这里应该实现实际的验证逻辑
        # 为了测试，我们假设验证成功
        return True

    def get_queue_size(self) -> int:
        """获取队列大小

        Returns:
            int: 队列中的项目数量
        """
        return len(self._queue)


# 兼容性别名
ConversationMemoryBuffer = ConversationBuffer
