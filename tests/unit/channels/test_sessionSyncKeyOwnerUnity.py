# -*- coding: utf-8 -*-
"""CHAN-04 红灯：同步会话 split-brain 与属主错位（审计已内存复现）。

根因链（审计 2026-11-25 · CHAN-04）：
- ``channels/manager._sync_to_session_sync`` 以 external_id 新建 session_*，
  session_id 自动生成、user 记成渠道 sender；
- ``chat_pipeline._sync_event`` 又以 scope_id（ctx.session_id）注册同一会话；
- ``create_session`` 还按 (user, agent) 复用 active 会话——不同 external_id
  共用同一会话。

症状：同一消息两个会话、不同 external_id 共用会话、控制台与同步端互不可见、
会话属主用 sender 冒充（持久会话归 agent 属主）。

判据（修复后语义）：
1. 渠道消息的 USER_MESSAGE 与 chat_pipeline 注册侧的 AGENT_REPLY 落进
   **同一个** UnifiedSession（session_id == resolve_session_scope_id）；
2. 不同 external_id 各自成会话，互不共用；
3. 会话属主 == agent 属主（P0-08 渠道口径：meta["session_owner_id"] 同源，
   经 post_chat_pipeline.resolveSessionOwner 单源取值），不再用 sender 冒充。
"""

import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.manager import ChannelManager
from neurova.sync.session_sync_manager import (
    EventType,
    SessionEvent,
    get_session_sync_manager,
    reset_session_sync_manager,
)

AGENT_OWNER = "owner-9"
SENDER = "wx_sender_u"


@pytest.fixture(autouse=True)
def _isolatedSync():
    reset_session_sync_manager()
    yield
    reset_session_sync_manager()


@pytest.fixture
def sync_manager():
    manager = get_session_sync_manager()
    import neurova.channels.manager as cm

    cm._session_sync_manager = manager
    yield manager
    cm._session_sync_manager = None
    reset_session_sync_manager()


@pytest.fixture
def ownedAgent(monkeypatch):
    """把 agent 属主解析钉到 AGENT_OWNER（验归属语义，不验查库链）。"""
    import neurova.api.agent_access as access_mod

    monkeypatch.setattr(access_mod, "agentOwnerById", lambda agent_id: AGENT_OWNER)


@pytest.fixture
def channel_manager(sync_manager):
    adapter = MagicMock(spec=ChannelAdapter)
    adapter.channel_type = "test_channel"
    adapter.config = ChannelConfig(channel_type="test_channel", enabled=True)
    adapter.is_connected = True
    adapter.send_message = AsyncMock(return_value="msg_123")
    adapter.connect = AsyncMock(return_value=True)
    adapter.disconnect = AsyncMock()
    adapter.health_check = AsyncMock(return_value={"connected": True})

    ChannelManager._instance = None
    manager = ChannelManager()
    manager.register_adapter(adapter)
    yield manager
    ChannelManager._instance = None


def _message(chat_id: str, message_id: str, agent_id: str = "default") -> ChannelMessage:
    return ChannelMessage(
        channel_type="test_channel",
        chat_id=chat_id,
        sender_id=SENDER,
        sender_name="Sender U",
        content=f"hello from {chat_id}",
        message_type="text",
        message_id=message_id,
        metadata={"agent_id": agent_id},
    )


class TestSessionKeyUnity:
    @pytest.mark.asyncio
    async def test_sameMessageLandsInOneSession(
        self, channel_manager, sync_manager, ownedAgent
    ):
        """同一消息：渠道侧 USER_MESSAGE 与 chat_pipeline 侧 AGENT_REPLY 同会话。"""
        msg = _message("chat_A", "m1")
        await channel_manager._sync_to_session_sync(ChannelEventType.MESSAGE_RECEIVED, msg)

        # chat_pipeline._sync_event 的注册形态（S2 修复后的现役调用）：
        # 以 ctx.session_id == resolve_session_scope_id(message) 注册。
        scope_id = channel_manager.resolve_session_scope_id(msg)
        sync_manager.register_or_create_session(
            session_id=scope_id,
            user_id=SENDER,
            agent_id="default",
            metadata={"source": "chat_pipeline"},
        )
        await sync_manager.broadcast_event(
            scope_id,
            SessionEvent(event_type=EventType.AGENT_REPLY, payload={"content": "agent reply"}),
        )

        # 全程只有一个会话，且两事件同框
        sessions = sync_manager.list_sessions()
        assert len(sessions) == 1, (
            f"同一消息裂成 {len(sessions)} 个会话（split-brain）: "
            f"{[s.session_id for s in sessions]}"
        )
        session = sync_manager.get_session_by_external_id(scope_id)
        assert session is not None
        assert session.session_id == scope_id
        types = [e.event_type for e in session.history]
        assert EventType.USER_MESSAGE in types and EventType.AGENT_REPLY in types

        # 控制台/同步端按会话读消息：user + assistant 都可见
        roles = [m["role"] for m in sync_manager.get_messages(scope_id)]
        assert roles == ["user", "assistant"], f"消息面缺半边: {roles}"

    @pytest.mark.asyncio
    async def test_differentExternalIdsDoNotShareSession(
        self, channel_manager, sync_manager, ownedAgent
    ):
        """同 sender 的两个不同 chat（external_id）必须各自成会话。"""
        await channel_manager._sync_to_session_sync(
            ChannelEventType.MESSAGE_RECEIVED, _message("chat_A", "m1")
        )
        await channel_manager._sync_to_session_sync(
            ChannelEventType.MESSAGE_RECEIVED, _message("chat_B", "m2")
        )

        s1 = sync_manager.get_session_by_external_id("chat_A")
        s2 = sync_manager.get_session_by_external_id("chat_B")
        assert s1 is not None and s2 is not None
        assert s1.session_id != s2.session_id, (
            "不同 external_id 共用了同一会话（sync 按 user+agent 复用 active 会话）"
        )
        assert sync_manager.get_session_by_external_id("chat_A").session_id == "chat_A"
        assert sync_manager.get_session_by_external_id("chat_B").session_id == "chat_B"

    @pytest.mark.asyncio
    async def test_sessionOwnerIsAgentOwnerNotSender(
        self, channel_manager, sync_manager, ownedAgent
    ):
        """会话属主 = agent 属主（持久会话同源），不用渠道 sender 冒充。"""
        await channel_manager._sync_to_session_sync(
            ChannelEventType.MESSAGE_RECEIVED, _message("chat_A", "m1")
        )
        session = sync_manager.get_session_by_external_id("chat_A")
        assert session is not None
        assert session.user_id == AGENT_OWNER, (
            f"同步会话属主被记成 sender：{session.user_id!r}（应为 agent 属主 {AGENT_OWNER!r}）"
        )

    @pytest.mark.asyncio
    async def test_replySyncUsesSameSession(self, channel_manager, sync_manager, ownedAgent):
        """出站回复同步（_sync_reply_to_session）落在同一会话，不另立门户。"""
        await channel_manager._sync_to_session_sync(
            ChannelEventType.MESSAGE_RECEIVED, _message("chat_A", "m1")
        )
        await channel_manager._sync_reply_to_session("chat_A", "outbound reply", "test_channel")

        session = sync_manager.get_session_by_external_id("chat_A")
        types = [e.event_type for e in session.history]
        assert types.count(EventType.AGENT_REPLY) == 1
        assert sync_manager.get_messages("chat_A")[0]["role"] == "user"
