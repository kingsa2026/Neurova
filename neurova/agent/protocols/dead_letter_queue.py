# -*- coding: utf-8 -*-
"""
Agent 死信队列模块

处理无法正常投递或处理失败的消息：
1. 死信消息存储
2. 自动重试机制
3. 死信消息查看和处理
4. 死信统计和分析
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from collections import defaultdict

from .message_protocol import AgentMessage, DeadLetterReason, DeadLetterMessage

logger = logging.getLogger(__name__)

@dataclass
class DLQConfig:
    """死信队列配置"""
    max_retries: int = 3                 # 最大重试次数
    retry_delay_base: float = 1.0        # 基础重试延迟（秒）
    retry_delay_max: float = 60.0       # 最大重试延迟（秒）
    retry_backoff: float = 2.0          # 退避指数
    cleanup_interval: int = 3600         # 清理间隔（秒）
    max_age_hours: int = 24              # 最大保留时间（小时）
    storage_path: str = "data/dlq"       # 存储路径
    enable_auto_retry: bool = True       # 是否自动重试
    enable_alert: bool = True            # 是否启用告警

class DeadLetterQueue:
    """死信队列处理器"""

    def __init__(self, config: DLQConfig = None):
        """
        初始化死信队列

        Args:
            config: 死信队列配置
        """
        self.config = config or DLQConfig()
        self._queue: List[DeadLetterMessage] = []
        self._retry_schedule: Dict[str, float] = {}  # message_id -> 下次重试时间
        self._retry_count: Dict[str, int] = {}  # message_id -> 重试次数
        self._handlers: List[Callable] = []  # 死信处理器
        self._stats = {
            "total_received": 0,
            "total_processed": 0,
            "total_retry": 0,
            "total_discarded": 0,
            "by_reason": defaultdict(int),
        }

        # 确保存储目录存在
        self._storage_path = Path(self.config.storage_path)
        self._storage_path.mkdir(parents=True, exist_ok=True)

        # 加载已有的死信
        self._load_from_disk()

        logger.info(f"死信队列初始化完成: max_retries={self.config.max_retries}, "
                   f"storage={self._storage_path}")

    def add(self, message: AgentMessage, reason: DeadLetterReason,
            error_details: str, handler_id: str = None) -> DeadLetterMessage:
        """
        添加死信到队列

        Args:
            message: 原始消息
            reason: 死信原因
            error_details: 错误详情
            handler_id: 处理失败的处理器ID

        Returns:
            创建的死信消息
        """
        dlq_msg = DeadLetterMessage(
            original_message=message,
            reason=reason,
            error_details=error_details,
            failed_at=time.time(),
            handler_id=handler_id,
            original_error=error_details,
        )

        self._queue.append(dlq_msg)
        self._stats["total_received"] += 1
        self._stats["by_reason"][reason.value] += 1

        # 计算下次重试时间
        retry_count = self._retry_count.get(message.message_id, 0)
        delay = min(
            self.config.retry_delay_base * (self.config.retry_backoff ** retry_count),
            self.config.retry_delay_max
        )
        self._retry_schedule[message.message_id] = time.time() + delay

        # 保存到磁盘
        self._save_to_disk(dlq_msg)

        logger.warning(
            f"死信已添加: message_id={message.message_id}, "
            f"reason={reason.value}, retry_count={retry_count}"
        )

        # 调用死信处理器
        self._notify_handlers(dlq_msg)

        return dlq_msg

    def get_pending(self) -> List[DeadLetterMessage]:
        """获取待处理死信列表"""
        return [dlq for dlq in self._queue if not self._is_processed(dlq)]

    def get_retryable(self) -> List[DeadLetterMessage]:
        """获取可重试的死信"""
        current_time = time.time()
        retryable = []

        for dlq in self._queue:
            if self._is_processed(dlq):
                continue

            msg_id = dlq.original_message.message_id
            if msg_id in self._retry_schedule:
                if current_time >= self._retry_schedule[msg_id]:
                    retryable.append(dlq)

        return retryable

    def mark_processed(self, message_id: str) -> None:
        """标记死信已处理"""
        self._stats["total_processed"] += 1
        self._remove_from_queue(message_id)
        logger.info(f"死信已处理: message_id={message_id}")

    def discard(self, message_id: str, reason: str = None) -> bool:
        """
        丢弃死信

        Args:
            message_id: 消息ID
            reason: 丢弃原因

        Returns:
            是否成功丢弃
        """
        for i, dlq in enumerate(self._queue):
            if dlq.original_message.message_id == message_id:
                self._queue.pop(i)
                self._stats["total_discarded"] += 1

                # 删除磁盘文件
                self._delete_from_disk(message_id)

                logger.info(f"死信已丢弃: message_id={message_id}, reason={reason}")
                return True
        return False

    def retry(self, message_id: str) -> Optional[AgentMessage]:
        """
        重试死信

        Args:
            message_id: 消息ID

        Returns:
            重试消息，如果不能重试则返回 None
        """
        dlq = self._find_dlq(message_id)
        if dlq is None:
            return None

        msg_id = dlq.original_message.message_id
        current_retry = self._retry_count.get(msg_id, 0)

        if current_retry >= self.config.max_retries:
            logger.warning(f"超过最大重试次数: message_id={msg_id}")
            return None

        # 创建重试消息
        retry_msg = dlq.original_message
        retry_msg.retry_count = current_retry + 1
        retry_msg.metadata["retry_reason"] = dlq.reason.value
        retry_msg.metadata["retry_error"] = dlq.error_details

        self._retry_count[msg_id] = current_retry + 1
        self._stats["total_retry"] += 1

        # 计算下次重试时间
        delay = min(
            self.config.retry_delay_base * (self.config.retry_backoff ** current_retry),
            self.config.retry_delay_max
        )
        self._retry_schedule[msg_id] = time.time() + delay

        logger.info(f"准备重试死信: message_id={msg_id}, retry_count={current_retry + 1}")
        return retry_msg

    def get_by_reason(self, reason: DeadLetterReason) -> List[DeadLetterMessage]:
        """根据原因获取死信"""
        return [dlq for dlq in self._queue if dlq.reason == reason]

    def get_stats(self) -> Dict[str, Any]:
        """获取死信统计"""
        return {
            "total_in_queue": len(self._queue),
            "pending": len(self.get_pending()),
            "retryable": len(self.get_retryable()),
            "stats": {
                **self._stats,
                "by_reason": dict(self._stats["by_reason"]),
            },
            "config": {
                "max_retries": self.config.max_retries,
                "retry_delay_base": self.config.retry_delay_base,
                "storage_path": str(self._storage_path),
            },
        }

    def cleanup(self) -> int:
        """
        清理过期死信

        Returns:
            清理的条目数
        """
        current_time = time.time()
        max_age = self.config.max_age_hours * 3600
        cleaned = 0

        to_remove = []
        for dlq in self._queue:
            if current_time - dlq.failed_at > max_age:
                to_remove.append(dlq.original_message.message_id)

        for msg_id in to_remove:
            if self.discard(msg_id, "超过最大保留时间"):
                cleaned += 1

        if cleaned > 0:
            logger.info(f"已清理 {cleaned} 条过期死信")

        return cleaned

    def register_handler(self, handler: Callable[[DeadLetterMessage], None]) -> None:
        """注册死信处理器"""
        self._handlers.append(handler)
        logger.info(f"已注册死信处理器: {handler.__name__}")

    def _notify_handlers(self, dlq_msg: DeadLetterMessage) -> None:
        """通知死信处理器"""
        for handler in self._handlers:
            try:
                handler(dlq_msg)
            except Exception as e:
                logger.error(f"死信处理器执行失败: {handler.__name__}, error={e}")

    def _is_processed(self, dlq: DeadLetterMessage) -> bool:
        """检查死信是否已处理"""
        msg_id = dlq.original_message.message_id
        if msg_id in self._retry_schedule:
            if self._retry_count.get(msg_id, 0) < self.config.max_retries:
                return False
        return False

    def _find_dlq(self, message_id: str) -> Optional[DeadLetterMessage]:
        """查找死信"""
        for dlq in self._queue:
            if dlq.original_message.message_id == message_id:
                return dlq
        return None

    def _remove_from_queue(self, message_id: str) -> None:
        """从队列中移除"""
        for i, dlq in enumerate(self._queue):
            if dlq.original_message.message_id == message_id:
                self._queue.pop(i)
                break

    def _get_storage_file(self, message_id: str) -> Path:
        """获取存储文件路径"""
        return self._storage_path / f"{message_id}.json"

    def _save_to_disk(self, dlq_msg: DeadLetterMessage) -> None:
        """保存到磁盘"""
        file_path = self._get_storage_file(dlq_msg.original_message.message_id)
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(dlq_msg.to_dict(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存死信到磁盘失败: {e}")

    def _delete_from_disk(self, message_id: str) -> None:
        """从磁盘删除"""
        file_path = self._get_storage_file(message_id)
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            logger.error(f"从磁盘删除死信失败: {e}")

    def _load_from_disk(self) -> None:
        """从磁盘加载"""
        try:
            for file_path in self._storage_path.glob("*.json"):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    original_data = data.get("original_message", {})
                    original_msg = AgentMessage.from_dict(original_data)
                    reason = DeadLetterReason(data.get("reason", "unknown_error"))

                    dlq_msg = DeadLetterMessage(
                        original_message=original_msg,
                        reason=reason,
                        error_details=data.get("error_details", ""),
                        failed_at=data.get("failed_at", time.time()),
                        handler_id=data.get("handler_id"),
                    )
                    self._queue.append(dlq_msg)

                except Exception as e:
                    logger.error(f"加载死信文件失败: {file_path}, error={e}")

            if self._queue:
                logger.info(f"已从磁盘加载 {len(self._queue)} 条死信")

        except Exception as e:
            logger.error(f"加载死信目录失败: {e}")

# 全局死信队列实例
_global_dlq: Optional[DeadLetterQueue] = None

def get_dead_letter_queue() -> DeadLetterQueue:
    """获取全局死信队列"""
    global _global_dlq
    if _global_dlq is None:
        _global_dlq = DeadLetterQueue()
    return _global_dlq
