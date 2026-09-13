# -*- coding: utf-8 -*-
"""ChannelRouter 契约测试——渠道入站消息统一路由到 agent 并回发。

补齐"下消息通路"缺失的环：此前 ChannelManager 无任何常驻处理器把入站消息交给
agent.chat()，飞书/钉钉/微信等消息进得来却无人接、无回复（对齐 QwenPaw 统一
process 注入 + resolve_session_id 模型）。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.channels.base import ChannelConfig, ChannelMessage
from neurova.channels import channel_router
from neurova.channels.manager import ChannelManager


class FakeAgent:
    def __init__(self, reply="pong", reasoning=""):
        self.reply = reply
        self.reasoning = reasoning
        self.calls = []

    @property
    def current_reasoning(self):
        return self.reasoning

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self.calls.append({"user_input": user_input, "session_id": session_id, "metadata": metadata})
        return {"text": self.reply}


class _CfgAdapter:
    """仅承载 config.extra 供 _channel_cfg 读取。"""
    def __init__(self, extra):
        self.config = SimpleNamespace(extra=extra)
        self.channel_type = "feishu"
        self.is_connected = True

    async def send_message(self, chat_id, content, message_type="text", **kw):
        return "mid"


def _msg(content="嗨", channel_type="feishu", chat_id="oc_1", sender="ou_9", agent_id="default", chat_type="p2p"):
    return ChannelMessage(
        channel_type=channel_type, message_id="m1", sender_id=sender, sender_name=sender,
        content=content, chat_id=chat_id, chat_type=chat_type,
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


# ------------------------------------------------------------------
# 公共参数传导（show_thinking / 访问控制 / require_mention）
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_show_thinking_prepends_reasoning(manager):
    agent = FakeAgent("答案", reasoning="先分析问题再回答")
    manager._adapters["feishu"] = _CfgAdapter({"show_thinking": True})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    reply = await handler(_msg("你好"))
    assert "先分析问题再回答" in reply and "答案" in reply
    assert reply.index("思考过程") < reply.index("答案")


@pytest.mark.asyncio
async def test_show_thinking_off_excludes_reasoning(manager):
    agent = FakeAgent("答案", reasoning="不该出现的思考")
    manager._adapters["feishu"] = _CfgAdapter({"show_thinking": False})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    reply = await handler(_msg("你好"))
    assert reply == "答案"


@pytest.mark.asyncio
async def test_private_strategy_closed_skips(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter({"private_chat_strategy": "closed"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg("你好", chat_type="p2p")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_group_require_mention_without_mention_skips(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter({"group_chat_strategy": "open", "require_mention": True})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg("随便聊天", chat_type="group")) is None
    # 带 @ 或 mentions 元数据则放行
    m = _msg("@机器人 你好", chat_type="group")
    assert await handler(m) == "pong"


@pytest.mark.asyncio
async def test_send_message_resolves_agent_instance_and_forwards_context(manager):
    """2.2：send_message 按 (agent_id,channel) 取实例，并把 at_user_id/chat_type 转发适配器。"""
    captured = {}

    class SpyAdapter:
        channel_type = "feishu"
        is_connected = True
        def set_event_callback(self, cb): pass
        async def send_message(self, chat_id, content, message_type="text", **kw):
            captured["chat_id"] = chat_id
            captured["at_user_id"] = kw.get("at_user_id")
            captured["chat_type"] = kw.get("chat_type")
            captured["has_agent_id"] = "agent_id" in kw  # agent_id 不应转发给适配器
            return "mid"

    agent_inst = SpyAdapter()
    manager._agent_adapters[("a7", "feishu")] = agent_inst
    manager._adapters["feishu"] = SpyAdapter()  # default 视图（不应被 a7 命中）

    mid = await manager.send_message("feishu", "oc_x", "回复", agent_id="a7",
                                     at_user_id="ou_9", chat_type="group")
    assert mid == "mid"
    assert captured["at_user_id"] == "ou_9" and captured["chat_type"] == "group"
    assert captured["has_agent_id"] is False, "agent_id 用于查实例，不应透传给适配器"


@pytest.mark.asyncio
async def test_dispatch_forwards_reply_kwargs(manager):
    """_dispatch_message 回发带 sender/chat_type/agent_id 上下文。"""
    seen = {}
    class SpyAdapter:
        channel_type = "feishu"
        is_connected = True
        async def send_message(self, chat_id, content, message_type="text", **kw):
            seen.update(kw); return "m"
    manager._adapters["feishu"] = SpyAdapter()
    agent = FakeAgent("回复")
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    manager.add_message_handler(handler, priority=50)
    await manager._dispatch_message(_msg("你好", chat_type="group", sender="ou_55"))
    assert seen.get("at_user_id") == "ou_55"
    assert seen.get("chat_type") == "group"
    assert "agent_id" not in seen, "agent_id 用于查实例，不透传适配器"
