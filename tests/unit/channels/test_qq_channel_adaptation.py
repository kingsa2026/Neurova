# -*- coding: utf-8 -*-
"""QQ 渠道适配测试（阶段3.4）：频道路径/at_infos 解析/机器人被移出群事件。"""
from __future__ import annotations

import asyncio

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.qq_ws import QQWebSocketAdapter


def _ad():
    return QQWebSocketAdapter(ChannelConfig(channel_type="qq", app_id="a", app_secret="s", extra={}))


def test_reply_path_distinguishes_guild_group_c2c():
    ad = _ad()
    assert "/channels/ch_1/messages" in ad._reply_path("ch_1", "guild")
    assert "/channels/ch_1/messages" in ad._reply_path("ch_1", "dm")
    assert "/v2/groups/gr_1/messages" in ad._reply_path("gr_1", "group")
    assert "/v2/users/u_1/messages" in ad._reply_path("u_1", "c2c")


@pytest.mark.asyncio
async def test_at_infos_parsed_into_mentions():
    ad = _ad()
    captured = {}
    async def cap(et, m): captured["m"] = m
    ad._emit_event = cap
    ad._main_loop = asyncio.get_running_loop()
    ad._on_msg_event("GROUP_AT_MESSAGE_CREATE", {
        "id": "m1", "content": "hi", "group_openid": "gr_1",
        "author": {"member_openid": "mb_9", "username": "李四"},
        "at_infos": [{"type": 1, "id": "bot_openid"}],
    })
    for _ in range(50):
        if captured: break
        await asyncio.sleep(0.01)
    m = captured["m"]
    assert m.chat_type == "group" and m.chat_id == "gr_1"
    assert m.metadata.get("mentions") == [{"type": 1, "id": "bot_openid"}]


@pytest.mark.asyncio
async def test_bot_removed_emits_event():
    ad = _ad()
    events = []
    async def cap(et, m): events.append((et, m))
    ad._emit_event = cap
    ad._main_loop = asyncio.get_running_loop()
    ad._on_bot_removed({"group_openid": "gr_gone"})
    for _ in range(50):
        if events: break
        await asyncio.sleep(0.01)
    assert events and events[0][0] == ChannelEventType.CHAT_BOT_REMOVED
    assert events[0][1].chat_id == "gr_gone"
