"""RoomBus 单元测试：薄封装 session_sync_manager，把房间消息以 SessionEvent 广播给所有连接端。"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from neurova.collaboration.room_bus import RoomBus
from neurova.sync.session_sync_manager import EventType


def test_publish_broadcasts_event_with_sender_payload():
    mgr = MagicMock()
    mgr.broadcast_event = AsyncMock(return_value=0)
    bus = RoomBus(manager=mgr)
    asyncio.run(bus.publish("project_x", EventType.AGENT_REPLY.value, {"sender_id": "a1", "content": "hi"}))
    args, _ = mgr.broadcast_event.call_args
    assert args[0] == "project_x"
    assert args[1].event_type == EventType.AGENT_REPLY
    assert args[1].payload["sender_id"] == "a1"


def test_ensure_room_registers_session_with_members_metadata():
    mgr = MagicMock()
    mgr.register_or_create_session = MagicMock(return_value=MagicMock())
    bus = RoomBus(manager=mgr)
    bus.ensure_room("project_x", user_id="u1", members=["a1", "a2"], owner="u1")
    mgr.register_or_create_session.assert_called_once()
    kwargs = mgr.register_or_create_session.call_args.kwargs
    assert kwargs["session_id"] == "project_x"
    assert kwargs["metadata"]["members"] == ["a1", "a2"]
    assert kwargs["metadata"]["owner"] == "u1"
