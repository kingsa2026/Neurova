# -*- coding: utf-8 -*-
"""ChannelRouter 契约测试——渠道入站消息统一路由到 agent 并回发。

补齐"下消息通路"缺失的环：此前 ChannelManager 无任何常驻处理器把入站消息交给
agent.chat()，飞书/钉钉/微信等消息进得来却无人接、无回复（对齐 QwenPaw 统一
process 注入 + resolve_session_id 模型）。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.channels.base import ChannelConfig, ChannelMessage
from neurova.channels import channel_router
from neurova.channels.manager import ChannelManager


class FakeAgent:
    def __init__(self, reply="pong"):
        self.reply = reply
        self.calls = []

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self.calls.append({"user_input": user_input, "session_id": session_id, "metadata": metadata})
        return {"text": self.reply}


def _msg(content="嗨", channel_type="feishu", chat_id="oc_1", sender="ou_9", agent_id="default"):
    return ChannelMessage(
        channel_type=channel_type, message_id="m1", sender_id=sender, sender_name=sender,
        content=content, chat_id=chat_id, chat_type="p2p",
        metadata={"agent_id": agent_id},
    )


@pytest.fixture
def manager():
    ChannelManager._instance = None
    m = ChannelManager()
    yield m
    ChannelManager._instance = None


@pytest.mark.asyncio
async def test_handler_routes_to_agent_and_returns_reply(manager):
    agent = FakeAgent("你好，我是Neurova")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    msg = _msg("嗨")
    reply = await handler(msg)
    assert reply == "你好，我是Neurova"
    assert agent.calls[0]["user_input"] == "嗨"
    # session 用 manager 的固定作用域键（agent+渠道+chat）
    assert agent.calls[0]["session_id"] == manager.resolve_session_scope_id(msg)
    md = agent.calls[0]["metadata"]
    assert md["user_id"] == "ou_9"
    assert md["source_channel"] == "feishu"


@pytest.mark.asyncio
async def test_handler_empty_content_no_agent_call(manager):
    agent = FakeAgent()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(content="   ")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_handler_agent_missing_returns_none(manager):
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: None)
    assert await handler(_msg()) is None


@pytest.mark.asyncio
async def test_handler_non_default_agent_id_lookup(manager):
    seen = {}
    def lookup(aid):
        seen["agent_id"] = aid
        return FakeAgent("ok")
    handler = channel_router.make_handler(manager, agent_lookup=lookup)
    await handler(_msg(agent_id="agent-77"))
    assert seen["agent_id"] == "agent-77"


def test_install_registers_handler_once(manager):
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: FakeAgent())
    n1 = len(manager._message_handlers)
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: FakeAgent())
    assert len(manager._message_handlers) == n1, "install 必须幂等，不重复注册"
    assert n1 == 1


@pytest.mark.asyncio
async def test_dispatch_sends_reply_back_to_channel(manager, monkeypatch):
    """端到端：_dispatch_message 经 router handler 得回复 → send_message 回发渠道。"""
    agent = FakeAgent("回复内容")
    channel_router.install_channel_router(manager, agent_lookup=lambda aid: agent)

    sent = {}
    class FakeAdapter:
        channel_type = "feishu"
        is_connected = True
        async def send_message(self, chat_id, content, message_type="text", **kw):
            sent["chat_id"] = chat_id
            sent["content"] = content
            return "mid"
    manager._adapters["feishu"] = FakeAdapter()

    await manager._dispatch_message(_msg("嗨"))
    assert sent.get("content") == "回复内容"
    assert sent.get("chat_id") == "oc_1"
