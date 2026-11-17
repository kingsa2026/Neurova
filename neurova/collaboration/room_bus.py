"""RoomBus — 协作房间实时广播（薄封装 SessionSyncManager 事件总线）。

职责单一：把房间消息/事件以 SessionEvent 广播给所有连接到该 room（session_id=room_id）
的端（多浏览器/设备/渠道），并注册房间会话。持久化不在此（见 RoomStore）。

复用既有 session_sync_manager 的广播/历史回放/断线 seq gap，不另造传输层。

S9：蜂群→房间的系统消息投递出口（审批卡/升级/候选事件）。sender_type=system，
广播复用既有 AGENT_REPLY 事件通道（零新协议），持久化复用 RoomStore（零新表）。
"""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger
from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    SessionSyncManager,
    get_session_sync_manager,
)
from neurova.core.lazy_singleton import lazySingleton

logger = get_logger(__name__)

#: 蜂群系统消息在房间里的发送者标识（sender_id；sender_type 恒为 "system"）
SWARM_SYSTEM_SENDER = "swarm"


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


@lazySingleton("_bus")
def get_room_bus() -> RoomBus:
    return RoomBus()


def reset_room_bus() -> None:
    global _bus
    _bus = None


def publishRoomSystemMessage(room_id: str, content: str, meta: Optional[Dict[str, Any]] = None) -> bool:
    """蜂群→房间系统消息（S9）：先落库（RoomStore，可回看），再尽力广播（实时刷新）。

    sender_type=system；广播复用既有 ``AGENT_REPLY`` 事件通道并在 payload 平铺
    ``sender_type="system"`` 与 ``meta``（kind=request_id 等），前端据 kind 渲染卡片——
    **零新表、零新事件类型**。

    同步入口（供 swarm.recordEscalation 等同步路径调用）：无运行事件循环时只落库、
    跳过广播（房间历史仍可查，实时性尽力而为）；有循环时 create_task 派发广播，
    不阻塞调用方。房间存储故障不抛出——投递失败由调用侧日志可见。
    """
    try:
        from neurova.collaboration.room_store import get_room_store

        get_room_store().append(room_id, "system", SWARM_SYSTEM_SENDER, content, meta=meta)
    except Exception as e:  # noqa: BLE001 - 落库失败不阻断蜂群主流程
        logger.warning("RoomBus: 蜂群系统消息落库失败 (room=%s): %s", room_id, e)
        return False
    payload: Dict[str, Any] = {
        "sender_id": SWARM_SYSTEM_SENDER, "sender_type": "system", "content": content,
    }
    for k, v in (meta or {}).items():
        payload.setdefault(k, v)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return True  # 无事件循环（同步上下文）：仅落库
    try:
        loop.create_task(get_room_bus().publish(room_id, EventType.AGENT_REPLY.value, payload))
    except Exception as e:  # noqa: BLE001 - 广播派发失败不影响已落库消息
        logger.debug("RoomBus: 蜂群系统消息广播派发失败 (room=%s): %s", room_id, e)
    return True
