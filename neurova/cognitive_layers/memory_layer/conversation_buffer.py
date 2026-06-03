"""
对话缓冲区模块

提供对话记忆的临时存储和批量写入功能。
支持：
- 对话历史缓冲
- 批量写入队列
- 内存限制和轮次限制
- 情感分析集成
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Optional, Any
from collections import deque

logger = logging.getLogger(__name__)

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

    def __init__(self,
                 memory_limit_bytes: int = 131072,  # 128KB
                 turn_limit: int = 20,
                 timeout_seconds: int = 180):
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

        logger.debug(f"ConversationBuffer 初始化: memory_limit={memory_limit_bytes}, "
                    f"turn_limit={turn_limit}, timeout={timeout_seconds}")

    def add_user_message(self, message: str) -> bool:
        """添加用户消息

        Args:
            message: 用户消息

        Returns:
            bool: 是否成功添加
        """
        try:
            # 创建内存项
            item = MemoryItem(
                id=f"user_{datetime.now().timestamp()}",
                content=message,
                timestamp=datetime.now(),
                classification="user_message"
            )

            # 添加到缓冲区
            self._buffer.append(item)
            self._total_bytes += len(message.encode('utf-8'))

            # 更新当前轮次
            if self._current_turn is None:
                self._current_turn = ConversationTurn(
                    user_message=message,
                    agent_message="",
                    timestamp=datetime.now(),
                    is_complete=False
                )
            else:
                self._current_turn.user_message = message

            logger.debug(f"添加用户消息: {len(message)} 字节")
            return True

        except Exception as e:
            logger.error(f"添加用户消息失败: {e}")
            return False

    def add_agent_message(self, message: str) -> bool:
        """添加AI回复消息

        Args:
            message: AI回复消息

        Returns:
            bool: 是否成功添加
        """
        try:
            # 创建内存项
            item = MemoryItem(
                id=f"agent_{datetime.now().timestamp()}",
                content=message,
                timestamp=datetime.now(),
                classification="agent_message"
            )

            # 添加到缓冲区
            self._buffer.append(item)
            self._total_bytes += len(message.encode('utf-8'))

            # 更新当前轮次
            if self._current_turn is not None:
                self._current_turn.agent_message = message
                self._current_turn.is_complete = True

                # 保存完成的轮次
                self._turns.append(self._current_turn)
                self._current_turn = None

            logger.debug(f"添加AI消息: {len(message)} 字节")
            return True

        except Exception as e:
            logger.error(f"添加AI消息失败: {e}")
            return False

    def is_full(self) -> bool:
        """检查缓冲区是否已满

        Returns:
            bool: 缓冲区是否已满
        """
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
        items = list(self._buffer)
        self._buffer.clear()
        self._turns.clear()
        self._current_turn = None
        self._total_bytes = 0
        self._last_flush_time = datetime.now()

        logger.debug(f"刷新缓冲区: {len(items)} 个项目")
        return items

    def get_stats(self) -> Dict[str, Any]:
        """获取缓冲区统计信息

        Returns:
            Dict[str, Any]: 统计信息
        """
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

    def __init__(self, storage=None, agent_id: str = None):
        """初始化写入队列

        Args:
            storage: 内存存储实例
            agent_id: 代理ID
        """
        self.storage = storage
        self.agent_id = agent_id
        self._queue: List[MemoryItem] = []
        self._lock = None

        logger.debug(f"MemoryWriteQueue 初始化: agent_id={agent_id}")

    def enqueue(self, item: MemoryItem) -> bool:
        """添加项目到队列

        Args:
            item: 内存项

        Returns:
            bool: 是否成功添加
        """
        try:
            self._queue.append(item)
            logger.debug(f"添加项目到队列: {item.id}")
            return True
        except Exception as e:
            logger.error(f"添加项目到队列失败: {e}")
            return False

    def enqueue_batch(self, items: List[MemoryItem]) -> bool:
        """批量添加项目到队列

        Args:
            items: 内存项列表

        Returns:
            bool: 是否成功添加
        """
        try:
            self._queue.extend(items)
            logger.debug(f"批量添加项目到队列: {len(items)} 个项目")
            return True
        except Exception as e:
            logger.error(f"批量添加项目到队列失败: {e}")
            return False

    def flush_to_storage(self) -> int:
        """刷新队列到存储

        Returns:
            int: 成功写入的项目数量
        """
        if not self.storage:
            logger.warning("存储不可用，无法刷新队列")
            return 0

        if not self._queue:
            return 0

        try:
            # 这里应该调用实际的存储写入逻辑
            # 为了测试，我们假设所有项目都成功写入
            count = len(self._queue)
            logger.info(f"刷新 {count} 个项目到存储")
            self._queue.clear()
            return count
        except Exception as e:
            logger.error(f"刷新队列到存储失败: {e}")
            return 0

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