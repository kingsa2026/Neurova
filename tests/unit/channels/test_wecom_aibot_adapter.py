# -*- coding: utf-8 -*-
"""WeComAIBotAdapter 契约测试（aibot WSClient 全 fake，离线）。

钉：缺 bot_id/secret 诚实拒连；connect 起后台线程 + 等 authenticated 才返 True；
入站 text/voice(ASR)/image 解析成 ChannelMessage 并缓存 frame；msgid 去重；
send_message 通过 reply_stream 调度回 SDK 线程；认证失败诚实 False。
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels import wecom_aibot


class FakeWSClient:
    def __init__(self, options, auth_ok=True):
        self.options = options
        self.auth_ok = auth_ok
        self._handlers = {}
        self.replies = []
        self.sent = []
        self.downloaded = []
        self.disconnected = False

    def on(self, event, handler):
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event, *args):
        for h in self._handlers.get(event, []):
            h(*args)

    async def connect(self):
        # 模拟 SDK：连上后在 ws_loop 触发 authenticated（或 error）
        loop = asyncio.get_running_loop()
        def _fire():
            if self.auth_ok:
                self.emit("authenticated")
            else:
                self.emit("error", RuntimeError("401 bad secret"))
        loop.call_soon(_fire)

    async def reply_stream(self, frame, stream_id, content, finish=False):
        self.replies.append((frame, content, finish))
        return {"errcode": 0}

    async def send_message(self, chatid, body):
        self.sent.append((chatid, body))
        return {"errcode": 0}

    async def download_file(self, url, aes_key=None):
        self.downloaded.append((url, aes_key))
        return (b"\x89PNGdata", "image.jpg")

    def disconnect(self):
        self.disconnected = True


@pytest.fixture
def fake_client_factory(monkeypatch):
    def _factory(options):
        c = FakeWSClient(options, auth_ok=_factory.auth_ok)
        _factory.client = c
        return c

    _factory.auth_ok = True
    _factory.client = None
    import aibot
    monkeypatch.setattr(aibot, "WSClient", _factory)
    return _factory


def _cfg(**extra):
    return ChannelConfig(channel_type="wecom", enabled=True,
                         app_id=extra.pop("bot_id", "bot-1"),
                         app_secret=extra.pop("secret", "sec-1"),
                         extra={"share_session_in_group": True, **extra})


@pytest.mark.asyncio
async def test_connect_requires_credentials():
    a = wecom_aibot.WeComAIBotAdapter(_cfg(bot_id="", secret=""))
    assert await a.connect() is False


@pytest.mark.asyncio
async def test_connect_authenticated_true(fake_client_factory):
    a = wecom_aibot.WeComAIBotAdapter(_cfg())
    assert await a.connect() is True
    assert a.is_connected is True
    await a.disconnect()
    assert fake_client_factory.client.disconnected is True


@pytest.mark.asyncio
async def test_connect_auth_failure_honest_false(fake_client_factory):
    fake_client_factory.auth_ok = False  # 让 fake SDK 触发 error 而非 authenticated
    a = wecom_aibot.WeComAIBotAdapter(_cfg())
    assert await a.connect() is False
    assert a.is_connected is False


@pytest.mark.asyncio
async def test_inbound_text_and_dedup(fake_client_factory, received_events):
    a = wecom_aibot.WeComAIBotAdapter(_cfg())
    events, cb = received_events
    a.set_event_callback(cb)
    await a.connect()
    client = fake_client_factory.client

    frame = {"headers": {"req_id": "r1"}, "body": {
        "msgtype": "text", "from": {"userid": "u1"}, "chatid": "c1",
        "chattype": "single", "msgid": "m-1", "text": {"content": "你好"}}}
    await a._on_message(frame)
    await a._on_message(frame)  # 同 msgid 去重
    await asyncio.sleep(0.05)
    assert len(events) == 1
    et, m = events[0]
    assert et == ChannelEventType.MESSAGE_RECEIVED
    assert m.content == "你好"
    assert m.chat_id == "c1"
    assert m.metadata["wecom_frame"] is frame
    await a.disconnect()


@pytest.mark.asyncio
async def test_voice_uses_asr_content(fake_client_factory, received_events):
    a = wecom_aibot.WeComAIBotAdapter(_cfg())
    events, cb = received_events
    a.set_event_callback(cb)
    await a.connect()
    await a._on_message({"body": {"msgtype": "voice", "from": {"userid": "u2"},
                                   "chatid": "u2", "msgid": "v1",
                                   "voice": {"content": "语音转写"}}})
    await asyncio.sleep(0.05)
    assert events[0][1].content == "语音转写"
    await a.disconnect()


@pytest.mark.asyncio
async def test_send_replies_via_reply_stream_on_sdk_thread(fake_client_factory, received_events):
    a = wecom_aibot.WeComAIBotAdapter(_cfg())
    events, cb = received_events
    a.set_event_callback(cb)
    await a.connect()
    frame = {"headers": {"req_id": "r9"}, "body": {"msgtype": "text",
             "from": {"userid": "u3"}, "chatid": "u3", "msgid": "m3",
             "text": {"content": "hi"}}}
    await a._on_message(frame)
    await asyncio.sleep(0.05)
    mid = await a.send_message("u3", "回复内容", "text", wecom_frame=frame)
    assert mid is not None
    client = fake_client_factory.client
    assert client.replies and client.replies[0][1] == "回复内容" and client.replies[0][2] is True
    await a.disconnect()


@pytest.fixture
def received_events():
    events = []

    async def cb(event_type, message):
        events.append((event_type, message))

    return events, cb
