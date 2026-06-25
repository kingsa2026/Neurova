"""
跨渠道会话同步管理器

实现统一的会话管理，支持多渠道实时同步对话。

核心功能：
1. 统一会话 ID 映射（user_id + agent_id → session_id）
2. 多渠道连接管理（WebSocket、SSE、轮询）
3. 事件广播（实时同步到所有活跃渠道）
4. 历史管理（内存 + 持久化）

设计原则：
- 深度模块：小接口，深实现
- 线程安全：使用 RLock 保护共享状态
- 异步优先：使用 async/await 进行并发处理
"""

from __future__ import annotations

import asyncio
import json
from neurova.core.logger import get_logger
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 枚举和数据类
# ---------------------------------------------------------------------------


class EventType(str, Enum):
    """会话事件类型"""

    # 用户输入
    USER_MESSAGE = "user_message"

    # Agent 状态
    AGENT_THINKING = "agent_thinking"
    AGENT_TOOL_CALL = "agent_tool_call"
    AGENT_TOOL_RESULT = "agent_tool_result"
    AGENT_COMMAND = "agent_command"
    AGENT_REPLY = "agent_reply"
    AGENT_ERROR = "agent_error"
    AGENT_STREAM_CHUNK = "agent_stream_chunk"

    # 会话状态
    SESSION_CREATED = "session_created"
    SESSION_RESUMED = "session_resumed"
    SESSION_PAUSED = "session_paused"
    SESSION_ENDED = "session_ended"

    # 渠道状态
    CHANNEL_CONNECTED = "channel_connected"
    CHANNEL_DISCONNECTED = "channel_disconnected"

    # 同步控制
    SYNC_REQUEST = "sync_request"
    SYNC_RESPONSE = "sync_response"
    HEARTBEAT = "heartbeat"


@dataclass
class SessionEvent:
    """会话事件"""

    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    event_type: EventType = EventType.USER_MESSAGE
    session_id: str = ""
    source_channel: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    payload: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        data = asdict(self)
        data["event_type"] = self.event_type.value
        data["timestamp"] = self.timestamp.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SessionEvent:
        """从字典反序列化"""
        data = data.copy()
        data["event_type"] = EventType(data["event_type"])
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        return cls(**data)

    def to_json(self) -> str:
        """序列化为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)


@dataclass
class ChannelConnection:
    """渠道连接"""

    channel_type: str
    connection_id: str = field(default_factory=lambda: f"conn_{uuid.uuid4().hex[:12]}")
    connected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_heartbeat: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    send_callback: Optional[Callable] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def is_alive(self, timeout_seconds: int = 60) -> bool:
        """检查连接是否存活"""
        elapsed = (datetime.now(timezone.utc) - self.last_heartbeat).total_seconds()
        return elapsed < timeout_seconds

    def update_heartbeat(self):
        """更新心跳时间"""
        self.last_heartbeat = datetime.now(timezone.utc)


@dataclass
class UnifiedSession:
    """统一会话"""

    session_id: str = field(default_factory=lambda: f"session_{uuid.uuid4().hex[:12]}")
    user_id: str = ""
    agent_id: str = "default"
    conversation_id: str = field(default_factory=lambda: f"conv_{uuid.uuid4().hex[:12]}")
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_activity: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    status: str = "active"  # active, paused, ended

    # 活跃渠道连接
    active_channels: Dict[str, ChannelConnection] = field(default_factory=dict)

    # 会话历史（内存中的最近事件）
    history: List[SessionEvent] = field(default_factory=list)

    # 元数据
    metadata: Dict[str, Any] = field(default_factory=dict)

    # 历史限制
    max_history_size: int = 1000

    def add_event(self, event: SessionEvent):
        """添加事件到历史"""
        event.session_id = self.session_id
        self.history.append(event)
        self.last_activity = datetime.now(timezone.utc)

        # 压缩历史
        if len(self.history) > self.max_history_size:
            self.history = self.history[-self.max_history_size :]

    def get_history(self, limit: int = 100, event_types: Optional[List[EventType]] = None) -> List[SessionEvent]:
        """获取历史事件"""
        events = self.history

        if event_types:
            events = [e for e in events if e.event_type in event_types]

        return events[-limit:]

    def register_channel(
        self, channel_type: str, send_callback: Callable, metadata: Optional[Dict[str, Any]] = None
    ) -> ChannelConnection:
        """注册渠道连接"""
        conn = ChannelConnection(channel_type=channel_type, send_callback=send_callback, metadata=metadata or {})
        self.active_channels[channel_type] = conn
        self.last_activity = datetime.now(timezone.utc)
        return conn

    def unregister_channel(self, channel_type: str) -> bool:
        """注销渠道连接"""
        if channel_type in self.active_channels:
            del self.active_channels[channel_type]
            self.last_activity = datetime.now(timezone.utc)
            return True
        return False

    def get_active_channel_types(self) -> List[str]:
        """获取活跃渠道类型列表"""
        return list(self.active_channels.keys())

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "session_id": self.session_id,
            "user_id": self.user_id,
            "agent_id": self.agent_id,
            "conversation_id": self.conversation_id,
            "created_at": self.created_at.isoformat(),
            "last_activity": self.last_activity.isoformat(),
            "status": self.status,
            "active_channels": list(self.active_channels.keys()),
            "history_size": len(self.history),
            "metadata": self.metadata,
        }


# ---------------------------------------------------------------------------
# SessionSyncManager 主类
# ---------------------------------------------------------------------------


class SessionSyncManager:
    """
    会话同步管理器

    核心功能：
    1. 统一会话 ID 映射（user_id + agent_id → session_id）
    2. 多渠道连接管理
    3. 事件广播
    4. 历史管理
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._lock = threading.RLock()

        # 会话存储
        self._sessions: Dict[str, UnifiedSession] = {}

        # 用户会话映射：(user_id, agent_id) → session_id
        self._user_sessions: Dict[Tuple[str, str], str] = {}

        # 外部 ID 映射：external_id → session_id
        self._external_mapping: Dict[str, str] = {}

        # 配置
        self._max_sessions = self._config.get("max_sessions", 1000)
        self._session_timeout = self._config.get("session_timeout", 3600)  # 1小时
        self._max_history_size = self._config.get("max_history_size", 1000)

        # 异步事件循环引用
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        logger.info("SessionSyncManager initialized")

    # -----------------------------------------------------------------------
    # 会话管理
    # -----------------------------------------------------------------------

    def create_session(
        self,
        user_id: str,
        agent_id: str = "default",
        external_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> UnifiedSession:
        """
        创建或获取会话

        如果 user_id + agent_id 已有活跃会话，返回现有会话。
        否则创建新会话。

        Args:
            user_id: 用户 ID
            agent_id: Agent ID
            external_id: 外部 ID（渠道特定）
            metadata: 会话元数据

        Returns:
            UnifiedSession 实例
        """
        with self._lock:
            key = (user_id, agent_id)

            # 检查是否已有活跃会话
            if key in self._user_sessions:
                session_id = self._user_sessions[key]
                session = self._sessions.get(session_id)

                if session and session.status == "active":
                    # 更新外部 ID 映射
                    if external_id:
                        self._external_mapping[external_id] = session_id

                    logger.debug("Reusing existing session: %s", session_id)
                    return session

            # 创建新会话
            session = UnifiedSession(
                user_id=user_id, agent_id=agent_id, max_history_size=self._max_history_size, metadata=metadata or {}
            )

            # 注册映射
            self._sessions[session.session_id] = session
            self._user_sessions[key] = session.session_id

            if external_id:
                self._external_mapping[external_id] = session.session_id

            # 发送会话创建事件
            event = SessionEvent(
                event_type=EventType.SESSION_CREATED,
                session_id=session.session_id,
                source_channel="system",
                payload={"user_id": user_id, "agent_id": agent_id},
            )
            session.add_event(event)

            logger.info("Created new session: %s for user=%s, agent=%s", session.session_id, user_id, agent_id)
            return session

    def get_session(self, session_id: str) -> Optional[UnifiedSession]:
        """获取会话"""
        return self._sessions.get(session_id)

    def get_session_by_user(self, user_id: str, agent_id: str = "default") -> Optional[UnifiedSession]:
        """通过用户 ID 获取会话"""
        key = (user_id, agent_id)
        session_id = self._user_sessions.get(key)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def get_session_by_external_id(self, external_id: str) -> Optional[UnifiedSession]:
        """通过外部 ID 获取会话"""
        session_id = self._external_mapping.get(external_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    def end_session(self, session_id: str) -> bool:
        """结束会话"""
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            session.status = "ended"

            # 发送会话结束事件
            event = SessionEvent(event_type=EventType.SESSION_ENDED, session_id=session_id, source_channel="system")
            session.add_event(event)

            # 清理映射
            key = (session.user_id, session.agent_id)
            if self._user_sessions.get(key) == session_id:
                del self._user_sessions[key]

            # 清理外部 ID 映射
            to_remove = [k for k, v in self._external_mapping.items() if v == session_id]
            for k in to_remove:
                del self._external_mapping[k]

            logger.info("Ended session: %s", session_id)
            return True

    def list_sessions(
        self, user_id: Optional[str] = None, agent_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[UnifiedSession]:
        """列出会话"""
        sessions = list(self._sessions.values())

        if user_id:
            sessions = [s for s in sessions if s.user_id == user_id]
        if agent_id:
            sessions = [s for s in sessions if s.agent_id == agent_id]
        if status:
            sessions = [s for s in sessions if s.status == status]

        return sessions

    # -----------------------------------------------------------------------
    # 渠道连接管理
    # -----------------------------------------------------------------------

    def register_channel(
        self, session_id: str, channel_type: str, send_callback: Callable, metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[ChannelConnection]:
        """
        注册渠道连接

        Args:
            session_id: 会话 ID
            channel_type: 渠道类型
            send_callback: 发送回调函数
            metadata: 连接元数据

        Returns:
            ChannelConnection 实例，失败返回 None
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                logger.warning("Session not found: %s", session_id)
                return None

            conn = session.register_channel(channel_type, send_callback, metadata)

            # 发送渠道连接事件
            event = SessionEvent(
                event_type=EventType.CHANNEL_CONNECTED,
                session_id=session_id,
                source_channel=channel_type,
                payload={"connection_id": conn.connection_id},
            )
            session.add_event(event)

            logger.info("Registered channel %s to session %s", channel_type, session_id)
            return conn

    def unregister_channel(self, session_id: str, channel_type: str) -> bool:
        """
        注销渠道连接

        Args:
            session_id: 会话 ID
            channel_type: 渠道类型

        Returns:
            是否成功
        """
        with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return False

            if session.unregister_channel(channel_type):
                # 发送渠道断开事件
                event = SessionEvent(
                    event_type=EventType.CHANNEL_DISCONNECTED, session_id=session_id, source_channel=channel_type
                )
                session.add_event(event)

                logger.info("Unregistered channel %s from session %s", channel_type, session_id)
                return True

            return False

    def update_heartbeat(self, session_id: str, channel_type: str) -> bool:
        """更新渠道心跳"""
        session = self._sessions.get(session_id)
        if not session:
            return False

        conn = session.active_channels.get(channel_type)
        if conn:
            conn.update_heartbeat()
            return True

        return False

    # -----------------------------------------------------------------------
    # 事件广播
    # -----------------------------------------------------------------------

    async def broadcast_event(self, session_id: str, event: SessionEvent, exclude_channel: Optional[str] = None) -> int:
        """
        广播事件到所有活跃渠道

        Args:
            session_id: 会话 ID
            event: 会话事件
            exclude_channel: 排除的渠道类型

        Returns:
            成功发送的渠道数量
        """
        session = self._sessions.get(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return 0

        # 设置事件属性
        event.session_id = session_id

        # 保存到历史
        session.add_event(event)

        # 并发发送到所有渠道
        sent_count = 0
        tasks = []

        for channel_type, conn in session.active_channels.items():
            if exclude_channel and channel_type == exclude_channel:
                continue

            if conn.send_callback:
                tasks.append(self._send_to_channel(conn, event))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            sent_count = sum(1 for r in results if r is True)

        logger.debug("Broadcast event %s to %s channels in session %s", event.event_type, sent_count, session_id)
        return sent_count

    async def _send_to_channel(self, conn: ChannelConnection, event: SessionEvent) -> bool:
        """发送事件到单个渠道"""
        try:
            import inspect

            if inspect.iscoroutinefunction(conn.send_callback):
                await conn.send_callback(event)
            else:
                conn.send_callback(event)
            return True
        except Exception as e:
            logger.error("Failed to send to channel %s: %s", conn.channel_type, e)
            return False

    def broadcast_event_sync(self, session_id: str, event: SessionEvent, exclude_channel: Optional[str] = None) -> int:
        """
        同步广播事件（用于非异步上下文）

        注意：这会阻塞当前线程，仅在无法使用异步时使用。
        """
        session = self._sessions.get(session_id)
        if not session:
            return 0

        event.session_id = session_id
        session.add_event(event)

        sent_count = 0
        for channel_type, conn in session.active_channels.items():
            if exclude_channel and channel_type == exclude_channel:
                continue

            if conn.send_callback:
                try:
                    conn.send_callback(event)
                    sent_count += 1
                except Exception as e:
                    logger.error("Failed to send to channel %s: %s", channel_type, e)

        return sent_count

    # -----------------------------------------------------------------------
    # 历史管理
    # -----------------------------------------------------------------------

    def get_history(
        self, session_id: str, limit: int = 100, event_types: Optional[List[EventType]] = None
    ) -> List[SessionEvent]:
        """获取会话历史"""
        session = self._sessions.get(session_id)
        if not session:
            return []

        return session.get_history(limit, event_types)

    def get_history_by_user(self, user_id: str, agent_id: str = "default", limit: int = 100) -> List[SessionEvent]:
        """通过用户 ID 获取历史"""
        session = self.get_session_by_user(user_id, agent_id)
        if not session:
            return []

        return session.get_history(limit)

    # -----------------------------------------------------------------------
    # 映射管理
    # -----------------------------------------------------------------------

    def map_external_id(self, external_id: str, session_id: str):
        """映射外部 ID 到会话 ID"""
        self._external_mapping[external_id] = session_id

    def resolve_external_id(self, external_id: str) -> Optional[str]:
        """解析外部 ID 到会话 ID"""
        return self._external_mapping.get(external_id)

    # -----------------------------------------------------------------------
    # 清理和维护
    # -----------------------------------------------------------------------

    def cleanup_expired_sessions(self) -> int:
        """清理过期会话"""
        with self._lock:
            now = datetime.now(timezone.utc)
            expired = []

            for session_id, session in self._sessions.items():
                if session.status == "ended":
                    expired.append(session_id)
                    continue

                elapsed = (now - session.last_activity).total_seconds()
                if elapsed > self._session_timeout:
                    expired.append(session_id)

            for session_id in expired:
                self.end_session(session_id)

            if expired:
                logger.info("Cleaned up %s expired sessions", len(expired))

            return len(expired)

    def get_statistics(self) -> Dict[str, Any]:
        """获取统计信息"""
        active_sessions = sum(1 for s in self._sessions.values() if s.status == "active")
        total_channels = sum(len(s.active_channels) for s in self._sessions.values())

        return {
            "total_sessions": len(self._sessions),
            "active_sessions": active_sessions,
            "total_channels": total_channels,
            "user_mappings": len(self._user_sessions),
            "external_mappings": len(self._external_mapping),
        }


# ---------------------------------------------------------------------------
# 全局单例
# ---------------------------------------------------------------------------

_manager_instance: Optional[SessionSyncManager] = None
_manager_lock = threading.Lock()


def get_session_sync_manager(config: Optional[Dict[str, Any]] = None) -> SessionSyncManager:
    """获取全局 SessionSyncManager 实例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = SessionSyncManager(config=config)
    return _manager_instance


def reset_session_sync_manager() -> None:
    """重置全局 SessionSyncManager 实例（用于测试）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
