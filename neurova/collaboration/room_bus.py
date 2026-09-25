"""RoomBus — 协作房间实时广播（薄封装 SessionSyncManager 事件总线）。

职责单一：把房间消息/事件以 SessionEvent 广播给所有连接到该 room（session_id=room_id）
的端（多浏览器/设备/渠道），并注册房间会话。持久化不在此（见 RoomStore）。

复用既有 session_sync_manager 的广播/历史回放/断线 seq gap，不另造传输层。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    SessionSyncManager,
    get_session_sync_manager,
)

logger = get_logger(__name__)


class RoomBus:
    def __init__(self, manager: Optional[SessionSyncManager] = None) -> None:
        self._manager = manager

    @property
    def manager(self) -> SessionSyncManager:
        return self._manager or get_session_sync_manager()

    def ensure_room(
        self, room_id: str, user_id: str, members: List[str], owner: str
    ) -> None:
        """注册/复用房间会话，metadata 携带成员与群主，供订阅端渲染归属。"""
        self.manager.register_or_create_session(
            session_id=room_id,
            user_id=user_id,
            agent_id="collaboration",
            metadata={"members": members, "owner": owner},
        )

    async def publish(self, room_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        """向房间广播一条事件。event_type 取 EventType 枚举值字符串。"""
        try:
            etype = EventType(event_type)
        except ValueError:
            logger.warning("RoomBus.publish 未知 event_type: %s", event_type)
            return
        event = SessionEvent(
            event_type=etype,
            session_id=room_id,
            source_channel="room",
            payload=payload,
        )
        await self.manager.broadcast_event(room_id, event)


_bus: Optional[RoomBus] = None


def get_room_bus() -> RoomBus:
    global _bus
    if _bus is None:
        _bus = RoomBus()
    return _bus


def reset_room_bus() -> None:
    global _bus
    _bus = None
