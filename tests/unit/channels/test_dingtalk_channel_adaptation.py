# -*- coding: utf-8 -*-
"""钉钉渠道适配测试（阶段3.2）：群回复路由修正 + session_webhook@ + mentions。"""
from __future__ import annotations

import asyncio

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.dingtalk import DingTalkAdapter


def _adapter():
    return DingTalkAdapter(ChannelConfig(channel_type="dingtalk", app_id="cid", app_secret="sec",
                                         use_stream=True, extra={}))


@pytest.mark.asyncio
async def test_group_reply_uses_session_webhook_with_at(monkeypatch):
    ad = _adapter()
    called = {}
    async def fake_sw(url, content, mt, at_user_id=""):
        called["url"] = url; called["at"] = at_user_id; called["content"] = content
        return "sent"
    monkeypatch.setattr(ad, "_send_via_session_webhook", fake_sw)
    # session_webhook 来自回发 metadata（阶段2 reply_metadata 透传）
    mid = await ad.send_message("cid123", "回复", "text",
                                chat_type="group", at_user_id="staff_9",
                                reply_metadata={"session_webhook": "https://hook/x"})
    assert mid == "sent"
    assert called["url"] == "https://hook/x"
    assert called["at"] == "staff_9"


@pytest.mark.asyncio
async def test_group_without_webhook_uses_group_api(monkeypatch):
    ad = _adapter()
    called = {}
    async def fake_group(cid, content, mt):
        called["args"] = (cid, content); return "gid"
    monkeypatch.setattr(ad, "send_group_message", fake_group)
    mid = await ad.send_message("cid_group", "群回复", "text", chat_type="group", reply_metadata={})
    assert mid == "gid"
    assert called["args"] == ("cid_group", "群回复")


@pytest.mark.asyncio
async def test_p2p_no_webhook_uses_single_api(monkeypatch):
    ad = _adapter()
    called = {}
    async def fake_api(cid, content, mt):
        called["cid"] = cid; return "pid"
    monkeypatch.setattr(ad, "_send_via_api", fake_api)
    monkeypatch.setattr(ad, "_refresh_access_token", lambda: asyncio.sleep(0))
    ad._access_token = "tok"; ad._token_expires_at = float("inf")
    mid = await ad.send_message("user_1", "私聊", "text", chat_type="p2p", reply_metadata={})
    assert mid == "pid" and called["cid"] == "user_1"


@pytest.mark.asyncio
async def test_handle_bot_message_parses_mentions_and_webhook():
    ad = _adapter()
    captured = {}
    async def cap_emit(et, m): captured["m"] = m
    ad._emit_event = cap_emit
    ad._main_loop = asyncio.get_running_loop()
    ad._handle_bot_message({
        "msgId": "m1", "senderId": "staff_9", "senderNick": "张三",
        "conversationId": "cid_g", "conversationType": "2", "msgtype": "text",
        "text": {"content": "你好"}, "sessionWebhook": "https://hook/y",
        "atUsers": [{"staffId": "bot"}], "isInAtList": True,
    })
    for _ in range(50):
        if "m" in captured:
            break
        await asyncio.sleep(0.01)
    m = captured["m"]
    assert m.chat_type == "group" and m.sender_id == "staff_9"
    assert m.metadata["session_webhook"] == "https://hook/y"
    assert m.metadata["is_in_at_list"] is True
    assert m.metadata["mentions"] == [{"staffId": "bot"}]
