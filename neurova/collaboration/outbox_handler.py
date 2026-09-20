"""
Transactional Outbox Pattern - Realtime Event Delivery
"""

import json
import uuid
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from neurova.core.logger import get_logger

logger = get_logger(__name__)

class EventStatus(str, Enum):
    """事件状态"""

    PENDING = "pending"          # 待发送
    SENT = "sent"               # 已发送
    FAILED = "failed"           # 发送失败
    DELIVERED = "delivered"     # 已送达
    EXPIRED = "expired"         # 已过期

@dataclass
class OutboxEvent:
    """
    Outbox Event - 待发送的事件

    Transactional outbox pattern ensures delivery guarantees
    """

    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:16]}")
    event_type: str = ""        # 事件类型 (agent_created, task_completed, etc.)
    agent_id: str = ""          # 关联的 Agent ID
    session_id: Optional[str] = None

    # Event payload
    payload: Dict[str, Any] = field(default_factory=dict)

    # Delivery info
    status: EventStatus = EventStatus.PENDING
    retry_count: int = 0
    max_retries: int = 3

    # Timing
    created_at: float = field(default_factory=time.time)
    scheduled_at: Optional[float] = None
    sent_at: Optional[float] = None
    delivered_at: Optional[float] = None
    expires_at: Optional[float] = None

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "payload": self.payload,
            "status": self.status.value,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "created_at": self.created_at,
            "scheduled_at": self.scheduled_at,
            "sent_at": self.sent_at,
            "delivered_at": self.delivered_at,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OutboxEvent":
        """从字典创建"""
        return cls(
            event_id=data.get("event_id", ""),
            event_type=data.get("event_type", ""),
            agent_id=data.get("agent_id", ""),
            session_id=data.get("session_id"),
            payload=data.get("payload", {}),
            status=EventStatus(data.get("status", "pending")),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            created_at=data.get("created_at", time.time()),
            scheduled_at=data.get("scheduled_at"),
            sent_at=data.get("sent_at"),
            delivered_at=data.get("delivered_at"),
            expires_at=data.get("expires_at"),
            metadata=data.get("metadata", {}),
        )

    def should_retry(self) -> bool:
        """检查是否应该重试"""
        return self.retry_count < self.max_retries and \
               self.status != EventStatus.EXPIRED

    def mark_sent(self) -> None:
        """标记为已发送"""
        self.status = EventStatus.SENT
        self.sent_at = time.time()

    def mark_delivered(self) -> None:
        """标记为已送达"""
        self.status = EventStatus.DELIVERED
        self.delivered_at = time.time()

    def mark_failed(self) -> None:
        """标记为发送失败"""
        self.retry_count += 1
        if self.should_retry():
            self.status = EventStatus.PENDING
        else:
            self.status = EventStatus.FAILED
            self.expires_at = time.time()

    def is_expired(self) -> bool:
        """检查是否已过期"""
        if self.expires_at is None:
            return False

        expiration_ttl = self.metadata.get("expiration_ttl", 3600)  # Default 1 hour
        return time.time() > self.expires_at + expiration_ttl

class OutboxHandler:
    """
    Outbox 事件处理器

    功能:
    1. Event persistence (事务性持久化)
    2. Delivery guarantees (投递保证)
    3. Retry mechanism (重试机制)
    4. Dead letter queue (死信队列)
    """

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self, data_dir: Optional[str] = None):
        if self._initialized:
            return

        self.data_dir = Path(data_dir) if data_dir else Path("data/outbox")

        # Thread safety
        self._lock = threading.RLock()

        # Storage: {event_id: OutboxEvent}
        self._events: Dict[str, OutboxEvent] = {}

        # Indexes
        self._agent_events: Dict[str, List[str]] = {}  # agent_id → [event_ids]
        self._pending_events: List[str] = []  # Events waiting to be sent

        # Callbacks for event processing
        self._handlers: Dict[str, Callable[[OutboxEvent], bool]] = {}

        # Statistics
        self._stats = {
            "total_events": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "retries": 0,
        }

        # Initialize
        self._on_init()

        logger.info("OutboxHandler initialized")

    def _on_init(self) -> None:
        """初始化回调"""
        self._init_dirs()
        self._load_events()

    def _init_dirs(self) -> None:
        """初始化目录结构"""
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            (self.data_dir / "events").mkdir(exist_ok=True)
            (self.data_dir / "dead-letter").mkdir(exist_ok=True)
            (self.data_dir / "backups").mkdir(exist_ok=True)

            logger.info(f"Initialized outbox directories: {self.data_dir}")
        except Exception as e:
            logger.error(f"Failed to initialize directories: {e}")

    def _load_events(self) -> None:
        """加载所有事件"""
        try:
            events_dir = self.data_dir / "events"
            if not events_dir.exists():
                return

            for event_file in events_dir.glob("*.json"):
                try:
                    with open(event_file, "r", encoding="utf-8") as f:
                        data = json.load(f)

                    event = OutboxEvent.from_dict(data)
                    self._events[event.event_id] = event

                    # Update indexes
                    if event.agent_id:
                        if event.agent_id not in self._agent_events:
                            self._agent_events[event.agent_id] = []
                        self._agent_events[event.agent_id].append(event.event_id)

                    if event.status == EventStatus.PENDING:
                        self._pending_events.append(event.event_id)

                except Exception as e:
                    logger.warning(f"Failed to load event file {event_file}: {e}")

            logger.info(f"Loaded {len(self._events)} events")

        except Exception as e:
            logger.error(f"Failed to load events: {e}")

    def _save_event(self, event: OutboxEvent) -> bool:
        """保存单个事件"""
        try:
            events_dir = self.data_dir / "events"
            event_file = events_dir / f"{event.event_id}.json"

            with open(event_file, "w", encoding="utf-8") as f:
                json.dump(event.to_dict(), f, ensure_ascii=False, indent=2)

            logger.debug(f"Saved event: {event.event_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to save event {event.event_id}: {e}")
            return False

    def publish(
        self,
        event_type: str,
        agent_id: str,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
        priority: int = 5,  # 1-10 scale
        expiration_ttl: int = 3600,  # Default 1 hour
    ) -> OutboxEvent:
        """
        发布事件到 Outbox

        Args:
            event_type: 事件类型
            agent_id: Agent ID
            payload: 事件载荷
            session_id: Session ID (可选)
            priority: 优先级 (1-10)
            expiration_ttl: 过期时间 (秒)

        Returns:
            创建的 OutboxEvent
        """
        with self._lock:
            event = OutboxEvent(
                event_type=event_type,
                agent_id=agent_id,
                session_id=session_id,
                payload=payload,
                metadata={
                    "priority": priority,
                    "expiration_ttl": expiration_ttl,
                },
            )

            # Set expiration time
            event.expires_at = time.time() + expiration_ttl

            # Store
            self._events[event.event_id] = event

            # Update indexes
            if agent_id not in self._agent_events:
                self._agent_events[agent_id] = []
            self._agent_events[agent_id].append(event.event_id)

            if event.status == EventStatus.PENDING:
                self._pending_events.append(event.event_id)

            # Save to disk
            self._save_event(event)

            # Update stats
            self._stats["total_events"] += 1

            logger.info(f"Published event {event.event_id} ({event_type}) for agent {agent_id}")

            return event

    def register_handler(
        self,
        event_type: str,
        handler: Callable[[OutboxEvent], bool],
    ) -> None:
        """
        注册事件处理器

        Args:
            event_type: 事件类型
            handler: 处理函数，返回 True 表示成功
        """
        with self._lock:
            self._handlers[event_type] = handler
            logger.info(f"Registered handler for event type: {event_type}")

    def process_pending_events(self) -> int:
        """
        处理待发送的事件

        Returns:
            处理的事件数量
        """
        with self._lock:
            processed_count = 0

            # Sort by priority (higher first)
            sorted_events = sorted(
                self._pending_events,
                key=lambda eid: self._events[eid].metadata.get("priority", 0),
                reverse=True,
            )

            for event_id in sorted_events:
                event = self._events.get(event_id)

                if not event or event.status != EventStatus.PENDING:
                    continue

                # Check if expired
                if event.is_expired():
                    logger.warning(f"Event {event_id} expired, skipping")
                    event.mark_failed()
                    self._move_to_dead_letter(event)
                    continue

                # Process event
                success = self._process_event(event)

                if success:
                    event.mark_delivered()
                    self._stats["successful_deliveries"] += 1
                    processed_count += 1
                else:
                    event.mark_failed()
                    self._stats["failed_deliveries"] += 1

                    if event.should_retry():
                        self._stats["retries"] += 1
                        # Reschedule with backoff
                        delay = min(2 ** event.retry_count * 5, 300)  # Exponential backoff
                        event.scheduled_at = time.time() + delay
                    else:
                        # Move to dead letter queue
                        self._move_to_dead_letter(event)

            # Clean up processed events from pending list
            self._pending_events = [
                eid for eid in self._pending_events
                if self._events.get(eid, OutboxEvent()).status == EventStatus.PENDING
            ]

            if processed_count > 0:
                logger.info(f"Processed {processed_count} pending events")

            return processed_count

    def _process_event(self, event: OutboxEvent) -> bool:
        """处理单个事件"""
        try:
            handler = self._handlers.get(event.event_type)

            if not handler:
                logger.warning(f"No handler registered for event type: {event.event_type}")
                return False

            # Call handler
            result = handler(event)

            if result:
                event.mark_sent()
                self._save_event(event)
                logger.debug(f"Successfully processed event: {event.event_id}")
                return True

            return False

        except Exception as e:
            logger.error(f"Error processing event {event.event_id}: {e}")
            return False

    def _move_to_dead_letter(self, event: OutboxEvent) -> None:
        """移动事件到死信队列"""
        try:
            dead_letter_dir = self.data_dir / "dead-letter"
            event_file = dead_letter_dir / f"{event.event_id}.json"

            with open(event_file, "w", encoding="utf-8") as f:
                json.dump(event.to_dict(), f, ensure_ascii=False, indent=2)

            logger.warning(f"Moved event to dead letter queue: {event.event_id}")

        except Exception as e:
            logger.error(f"Failed to move event to dead letter: {e}")

    def get_agent_events(
        self,
        agent_id: str,
        status_filter: Optional[EventStatus] = None,
    ) -> List[OutboxEvent]:
        """
        获取 agent 的所有事件

        Args:
            agent_id: Agent ID
            status_filter: 状态过滤

        Returns:
            OutboxEvent 列表
        """
        with self._lock:
            event_ids = self._agent_events.get(agent_id, [])

            events = []
            for event_id in event_ids:
                event = self._events.get(event_id)

                if event and (status_filter is None or event.status == status_filter):
                    events.append(event)

            # Sort by created_at descending
            events.sort(key=lambda e: e.created_at, reverse=True)

            return events

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            total = sum(self._stats.values())

            return {
                **self._stats,
                "pending_count": len(self._pending_events),
                "total_events_in_storage": len(self._events),
                "success_rate": round(
                    self._stats["successful_deliveries"] / max(total, 1), 3
                ),
            }

    def cleanup_old_events(self, keep_days: int = 7) -> int:
        """
        清理旧事件

        Args:
            keep_days: 保留天数

        Returns:
            清理数量
        """
        with self._lock:
            cutoff_time = time.time() - (keep_days * 24 * 60 * 60)
            cleaned_count = 0

            for event_id, event in list(self._events.items()):
                if event.created_at < cutoff_time:
                    # Keep only delivered/failed events for backup
                    if event.status in [EventStatus.DELIVERED, EventStatus.FAILED]:
                        # Move to backups
                        pass  # Could implement backup logic here

                    del self._events[event_id]

                    # Update indexes
                    if event.agent_id:
                        if event_id in self._agent_events.get(event.agent_id, []):
                            self._agent_events[event.agent_id].remove(event_id)

                    if event_id in self._pending_events:
                        self._pending_events.remove(event_id)

                    cleaned_count += 1

            if cleaned_count > 0:
                logger.info(f"Cleaned up {cleaned_count} old events")

            return cleaned_count

# Global instance management
_outbox_handler_instance: Optional[OutboxHandler] = None
_outbox_handler_lock = threading.Lock()

def get_outbox_handler() -> OutboxHandler:
    """获取全局 OutboxHandler 实例 (Singleton)"""
    global _outbox_handler_instance

    if _outbox_handler_instance is None:
        with _outbox_handler_lock:
            if _outbox_handler_instance is None:
                _outbox_handler_instance = OutboxHandler()

    return _outbox_handler_instance

def reset_outbox_handler() -> None:
    """重置 OutboxHandler 实例 (用于测试)"""
    global _outbox_handler_instance
    _outbox_handler_instance = None
