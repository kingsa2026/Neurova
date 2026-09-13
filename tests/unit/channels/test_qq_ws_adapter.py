# -*- coding: utf-8 -*-
"""QQWebSocketAdapter 契约测试（网关握手/事件解析/被动回复，网络全 fake）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels import qq_ws


class FakeWS:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send(self, data):
        self.sent.append(json.loads(data))

    async def close(self):
        self.closed = True


def _cfg(**extra):
    return ChannelConfig(channel_type="qq", enabled=True,
                         app_id="app-1", app_secret="cs-1", extra=dict(extra))


@pytest.fixture
def adapter():
    a = qq_ws.QQWebSocketAdapter(_cfg())
    a.access_token = "tok"
    a.token_expire_time = float("inf")
    return a


# ------------------------------------------------------------------
# 帧处理
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_hello_identify_frame(adapter):
    ws = FakeWS()
    adapter._ws_loop = asyncio.get_running_loop()
    adapter._handle_frame({"op": qq_ws.OP_HELLO, "d": {"heartbeat_interval": 41250}}, ws)
    await asyncio.sleep(0.05)
    assert ws.sent and ws.sent[0]["op"] == qq_ws.OP_IDENTIFY
    d = ws.sent[0]["d"]
    assert d["token"] == "QQBot tok"
    assert d["intents"] & qq_ws.INTENT_GROUP_AND_C2C
    assert d["shard"] == [0, 1]


@pytest.mark.asyncio
async def test_hello_resume_when_session_present(adapter):
    ws = FakeWS()
    adapter._ws_loop = asyncio.get_running_loop()
    adapter._session_id = "sess-1"
    adapter._last_seq = 42
    adapter._handle_frame({"op": qq_ws.OP_HELLO, "d": {}}, ws)
    await asyncio.sleep(0.05)
    assert ws.sent[0]["op"] == qq_ws.OP_RESUME
    assert ws.sent[0]["d"]["session_id"] == "sess-1" and ws.sent[0]["d"]["seq"] == 42


def test_dispatch_ready_stores_session(adapter):
    assert adapter._handle_frame(
        {"op": qq_ws.OP_DISPATCH, "t": "READY", "s": 1, "d": {"session_id": "S9"}}, FakeWS()) is None
    assert adapter._session_id == "S9" and adapter._last_seq == 1


def test_reconnect_and_invalid_session_break(adapter):
    assert adapter._handle_frame({"op": qq_ws.OP_RECONNECT}, FakeWS()) == "break"
    assert adapter._handle_frame({"op": qq_ws.OP_INVALID_SESSION, "d": False}, FakeWS()) == "break"
    assert adapter._session_id is None  # 不可恢复时清空


# ------------------------------------------------------------------
# 入站事件解析
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_c2c_message_emits_and_stores_msg_id(adapter, received):
    events, cb = received
    adapter.set_event_callback(cb)
    adapter._main_loop = asyncio.get_running_loop()
    d = {"id": "MSG1", "content": "你好呀", "author": {"user_openid": "openid-1", "username": "张三"}}
    adapter._on_msg_event("C2C_MESSAGE_CREATE", d)
    await asyncio.sleep(0.05)
    assert len(events) == 1
    et, m = events[0]
    assert et == ChannelEventType.MESSAGE_RECEIVED
    assert m.content == "你好呀"
    assert m.sender_id == "openid-1"
    assert m.chat_id == "openid-1"
    assert adapter._last_msg_id["openid-1"] == "MSG1"
    # 同 id 去重
    adapter._on_msg_event("C2C_MESSAGE_CREATE", d)
    await asyncio.sleep(0.05)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_group_message_uses_group_openid(adapter, received):
    events, cb = received
    adapter.set_event_callback(cb)
    adapter._main_loop = asyncio.get_running_loop()
    adapter._on_msg_event("GROUP_AT_MESSAGE_CREATE", {
        "id": "G1", "content": "群消息", "group_openid": "oc_group",
        "author": {"member_openid": "member-9"}})
    await asyncio.sleep(0.05)
    m = events[0][1]
    assert m.chat_type == "group"
    assert m.chat_id == "oc_group"
    assert m.metadata["qq_message_type"] == "group"


@pytest.fixture
def received():
    events = []

    async def cb(event_type, message):
        events.append((event_type, message))

    return events, cb


# ------------------------------------------------------------------
# 被动回复
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_without_msg_id_honest_none(adapter):
    assert await adapter.send_message("openid-x", "hi") is None


@pytest.mark.asyncio
async def test_send_c2c_path_and_msg_seq_increments(adapter, monkeypatch):
    captured = []

    class _R:
        status_code = 200

        def json(self):
            return {"id": "sent-1"}

    monkeypatch.setattr(qq_ws.requests, "post",
                        lambda url, json=None, headers=None, timeout=None: (captured.append((url, json, headers)) or _R()))
    adapter._last_msg_id["openid-1"] = "MSG1"
    mid = await adapter.send_message("openid-1", "回复")
    assert mid == "sent-1"
    url, body, headers = captured[0]
    assert url.endswith("/v2/users/openid-1/messages")
    assert body["msg_id"] == "MSG1" and body["msg_seq"] == 1
    assert headers["Authorization"] == "QQBot tok"
    # 第二条同 msg_id → seq 递增
    await adapter.send_message("openid-1", "再回复")
    assert captured[1][1]["msg_seq"] == 2


@pytest.mark.asyncio
async def test_send_group_path(adapter, monkeypatch):
    captured = []

    class _R:
        status_code = 200

        def json(self):
            return {"id": "g-1"}

    monkeypatch.setattr(qq_ws.requests, "post",
                        lambda url, json=None, headers=None, timeout=None: (captured.append((url, json)) or _R()))
    adapter._last_msg_id["oc_group"] = "G1"
    await adapter.send_message("oc_group", "群回复", "text", qq_message_type="group")
    assert captured[0][0].endswith("/v2/groups/oc_group/messages")


# ------------------------------------------------------------------
# connect 诚实性
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connect_requires_credentials():
    a = qq_ws.QQWebSocketAdapter(ChannelConfig(channel_type="qq", enabled=True,
                                               app_id="", app_secret="", extra={}))
    assert await a.connect() is False


@pytest.mark.asyncio
async def test_connect_starts_thread_when_verified(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_verify_credentials", lambda: True)
    # 不 patch threading.Thread（会连带打断 asyncio 默认 executor 的 to_thread）；
    # 把后台网关循环本体置空，真实 daemon 线程立即退出即可。
    started = {}

    def _noop_forever():
        started["ran"] = True

    monkeypatch.setattr(adapter, "_run_ws_forever", _noop_forever)
    assert await adapter.connect() is True
    assert adapter.is_connected is True
    await adapter.disconnect()  # 停线程 + 清 ws


@pytest.mark.asyncio
async def test_connect_fails_when_verify_fails(adapter, monkeypatch):
    monkeypatch.setattr(adapter, "_verify_credentials", lambda: False)
    assert await adapter.connect() is False
    assert adapter.is_connected is False
