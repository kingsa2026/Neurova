# -*- coding: utf-8 -*-
"""Telegram 渠道适配测试（阶段3.1）：base 契约发送 + getUpdates 解析 + 退群归档。"""
from __future__ import annotations

import asyncio

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.telegram_adapter import TelegramAdapter


def _ad():
    a = TelegramAdapter()
    a.bot_token = "t"
    a._initialized = True
    a._ensure_initialized = lambda: True
    return a


@pytest.mark.asyncio
async def test_send_message_base_contract_returns_str():
    a = _ad()
    a._send_text_message = lambda chat_id, text, parse_mode=None: True
    mid = await a.send_message("123", "回复内容", "text")
    assert mid == "sent"


@pytest.mark.asyncio
async def test_send_message_failure_returns_none():
    a = _ad()
    a._send_text_message = lambda *x, **k: False
    assert await a.send_message("123", "x", "text") is None


@pytest.mark.asyncio
async def test_process_update_emits_channel_message():
    a = _ad()
    events = []
    async def cap(et, m): events.append((et, m))
    a._emit_event = cap
    a._main_loop = asyncio.get_running_loop()
    a._process_update({"update_id": 1, "message": {
        "message_id": 5, "text": "你好", "chat": {"id": 777, "type": "private"},
        "from": {"id": 999, "username": "bob"}}})
    for _ in range(50):
        if events: break
        await asyncio.sleep(0.01)
    assert events
    et, m = events[0]
    assert et == ChannelEventType.MESSAGE_RECEIVED
    assert m.chat_id == "777" and m.chat_type == "p2p" and m.sender_id == "999"
    assert m.content == "你好"


@pytest.mark.asyncio
async def test_group_requires_mention_when_enabled():
    a = _ad()
    a.require_mention = True
    a._emit_event = lambda et, m: asyncio.sleep(0)
    events = []
    async def cap(et, m): events.append(m)
    a._emit_event = cap
    a._main_loop = asyncio.get_running_loop()
    # 群消息无 @mention entity → should_process_message False → 不 emit
    a._process_update({"update_id": 1, "message": {
        "message_id": 5, "text": "随便说", "chat": {"id": 1, "type": "group"},
        "from": {"id": 2}}})
    await asyncio.sleep(0.05)
    assert not events


@pytest.mark.asyncio
async def test_my_chat_member_kicked_emits_removed():
    a = _ad()
    events = []
    async def cap(et, m): events.append((et, m))
    a._emit_event = cap
    a._main_loop = asyncio.get_running_loop()
    a._process_update({"update_id": 1, "my_chat_member": {
        "chat": {"id": 555, "type": "group"},
        "new_chat_member": {"status": "kicked"}}})
    for _ in range(50):
        if events: break
        await asyncio.sleep(0.01)
    assert events and events[0][0] == ChannelEventType.CHAT_BOT_REMOVED
    assert events[0][1].chat_id == "555"


@pytest.mark.asyncio
async def test_connect_starts_poll_thread(monkeypatch):
    a = _ad()
    monkeypatch.setattr(a, "_run_poll_forever", lambda: None)
    assert await a.connect() is True
    assert a.is_connected is True
    await a.disconnect()
