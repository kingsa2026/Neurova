# -*- coding: utf-8 -*-
"""飞书渠道适配测试（阶段3.5）：mentions 解析、群回复@、机器人被移出群归档。"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.manager import ChannelManager


def _adapter():
    return FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="a", app_secret="b",
                                        use_stream=True, extra={}))


def _event(text_content, mentions=None):
    msg = SimpleNamespace(
        message_type="text", content=TextJSON(text_content), message_id="om_1",
        chat_id="oc_g1", chat_type="group", mentions=mentions or [],
    )
    sender = SimpleNamespace(sender_id=SimpleNamespace(user_id=None, open_id="ou_sender", union_id=None))
    return SimpleNamespace(event=SimpleNamespace(message=msg, sender=sender))


class TextJSON(str):
    def __new__(cls, t):
        import json
        return super().__new__(cls, json.dumps({"text": t}))


@pytest.mark.asyncio
async def test_mentions_parsed_and_placeholder_cleaned():
    ad = _adapter()
    events = []
    async def cb(et, m): events.append((et, m))
    ad.set_event_callback(cb)
    mentions = [SimpleNamespace(key="@_user_1", name="机器人小艺",
                                id=SimpleNamespace(open_id="ou_bot", user_id=None))]
    ev = _event("@_user_1 帮我查天气", mentions=mentions)
    loop = asyncio.get_running_loop()
    ad._main_loop = loop
    ad._handle_message_event(ev)
    for _ in range(50):
        if events: break
        await asyncio.sleep(0.01)
    assert events
    m = events[0][1]
    assert "帮我查天气" in m.content and "@_user_1" not in m.content  # 占位符清理
    assert "@机器人小艺" in m.content
    assert m.metadata.get("mentions") and m.metadata["mentions"][0]["open_id"] == "ou_bot"


@pytest.mark.asyncio
async def test_bot_removed_emits_event():
    ad = _adapter()
    events = []
    async def cb(et, m): events.append((et, m))
    ad.set_event_callback(cb)
    ad._main_loop = asyncio.get_running_loop()
    ad._handle_bot_removed_event(SimpleNamespace(event=SimpleNamespace(chat_id="oc_gone")))
    for _ in range(50):
        if events: break
        await asyncio.sleep(0.01)
    assert events and events[0][0] == ChannelEventType.CHAT_BOT_REMOVED
    assert events[0][1].chat_id == "oc_gone"


@pytest.mark.asyncio
async def test_archive_channel_session_calls_repo(monkeypatch):
    ChannelManager._instance = None
    mgr = ChannelManager()
    called = {}
    class FakeRepo:
        def archive_session(self, agent_id, session_id):
            called["args"] = (agent_id, session_id); return True
    monkeypatch.setattr("neurova.session_manager.SessionManager", lambda *a, **k: FakeRepo())
    from neurova.channels.base import ChannelMessage
    msg = ChannelMessage(channel_type="feishu", message_id="", sender_id="", sender_name="",
                         content="", chat_id="oc_gone", chat_type="group", metadata={"agent_id": "default"})
    ok = await mgr.archive_channel_session(msg)
    assert ok is True
    assert called["args"] == ("default", "oc_gone")  # default agent → scope=chat_id
    ChannelManager._instance = None
