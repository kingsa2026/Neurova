# -*- coding: utf-8 -*-
"""CHAN-09：入站去重键必须包含渠道实例与聊天边界。

Telegram 等平台的消息 ID 只在会话内唯一；原键仅含 channel_type/message_id，
会把其他聊天或 agent 的合法消息误判为重投。渠道实例身份由 (channel_type,
agent_id) 唯一确定，聊天边界由 chat_id 确定。
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from neurova.channels.base import ChannelEventType, ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue
from neurova.channels.manager import ChannelManager


def _message(messageId="m1", chatId="chat-a", agentId="agent-a"):
    return ChannelMessage(
        channel_type="telegram",
        message_id=messageId,
        sender_id="user-1",
        sender_name="用户",
        content="正文",
        chat_id=chatId,
        metadata={"agent_id": agentId, "tenant_id": "tenant-a"},
    )


def testSameMessageIdInDifferentChatsIsNotDeduplicated(tmp_path):
    queue = ChannelIngressQueue(tmp_path / "ingress.db")
    try:
        assert queue.enqueue(_message(chatId="chat-a"), agent_id="agent-a") is True
        assert queue.enqueue(_message(chatId="chat-b"), agent_id="agent-a") is True
        assert queue.stats()["pending"] == 2
    finally:
        queue.close()


def testSameMessageIdInDifferentAgentInstancesIsNotDeduplicated(tmp_path):
    queue = ChannelIngressQueue(tmp_path / "ingress.db")
    try:
        assert queue.enqueue(_message(), agent_id="agent-a") is True
        assert queue.enqueue(_message(), agent_id="agent-b") is True
        assert queue.stats()["pending"] == 2
    finally:
        queue.close()


def testSameInstanceChatAndMessageIsStillDeduplicated(tmp_path):
    queue = ChannelIngressQueue(tmp_path / "ingress.db")
    try:
        assert queue.enqueue(_message(), agent_id="agent-a") is True
        assert queue.enqueue(_message(), agent_id="agent-a") is False
        assert queue.stats()["pending"] == 1
    finally:
        queue.close()


def testManagerPassesInstanceBoundaryIntoQueue(tmp_path):
    manager = ChannelManager()
    queue = ChannelIngressQueue(tmp_path / "ingress.db")
    manager.ingress_queue = queue
    received = []

    async def handle(message):
        received.append(message)

    manager.set_message_handler(handle)
    try:
        import asyncio

        asyncio.run(manager._on_channel_event(
            ChannelEventType.MESSAGE_RECEIVED, _message()
        ))
        row = queue._conn.execute(
            "SELECT agent_id, tenant_id, dedupe_key FROM channel_ingress_events"
        ).fetchone()
        assert tuple(row[:2]) == ("agent-a", "tenant-a")
        assert json.loads(row[2]) == ["telegram", "chat-a", "agent-a", "m1"]
        assert len(received) == 1
    finally:
        queue.close()


def testLegacyDedupeKeyIsMigratedWithoutReprocessing(tmp_path):
    db = tmp_path / "legacy.db"
    queue = ChannelIngressQueue(db)
    queue.enqueue(_message(), agent_id="agent-a", tenant_id="tenant-a")
    with queue._lock, queue._conn:
        queue._conn.execute(
            "UPDATE channel_ingress_events SET dedupe_key='telegram:m1'"
        )
        queue._conn.execute("PRAGMA user_version=3")
    queue.close()

    reopened = ChannelIngressQueue(db)
    try:
        key = reopened._conn.execute(
            "SELECT dedupe_key FROM channel_ingress_events"
        ).fetchone()[0]
        assert json.loads(key) == ["telegram", "chat-a", "agent-a", "m1"]
        assert reopened.enqueue(_message(), agent_id="agent-a") is False
        assert reopened.stats()["pending"] == 1
    finally:
        reopened.close()
