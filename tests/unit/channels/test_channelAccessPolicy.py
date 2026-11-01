# -*- coding: utf-8 -*-
"""渠道准入判定的单源与失败方向（D-5 / N-5）。

立项理由（本仓可核实）：`channel_router` 只认 `closed`，`whitelist` 完全没被检查，
缺配置时 `or "open"` —— 于是「配置了白名单」的渠道在路由层仍对所有人放行；
未知策略（拼写错误、旧值）也一律当 open。准入判定的第二份实装在 Discord 适配器里
（同一文件甚至有两处），本判据要求：判定只有一处实现，且**缺省/未知一律拒绝**。

为什么默认 open 保留：这是既有产品默认（各适配器初始值就是 open），本批不改默认；
改的是「显式配置了 whitelist 却没人看」与「未知值当放行」这两条失败方向。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from neurova.channels import channel_router
from neurova.channels.base import ChannelMessage
from neurova.channels.manager import ChannelManager


class FakeAgent:
    def __init__(self, reply="pong"):
        self.reply = reply
        self.calls = []

    async def chat(self, user_input, session_id=None, metadata=None, **kw):
        self.calls.append(user_input)
        return {"text": self.reply}


class _CfgAdapter:
    channel_type = "feishu"
    is_connected = True

    def __init__(self, extra):
        self.config = SimpleNamespace(extra=extra)


class _AttrAdapter:
    """Gen2 形态：策略被 authenticate() 读成实例属性，config.extra 为空。"""
    channel_type = "discord"
    is_connected = True

    def __init__(self, strategy, whitelist):
        self.config = SimpleNamespace(extra={})
        self.private_chat_strategy = strategy
        self.group_chat_strategy = "open"
        self.whitelist_users = whitelist


def _msg(sender="ou_9", chat_type="p2p", content="嗨"):
    return ChannelMessage(
        channel_type="feishu", message_id="m1", sender_id=sender, sender_name=sender,
        content=content, chat_id="oc_1", chat_type=chat_type,
        metadata={"agent_id": "default"},
    )


@pytest.fixture
def manager():
    ChannelManager._instance = None
    m = ChannelManager()
    yield m
    ChannelManager._instance = None


@pytest.mark.asyncio
async def test_whitelistDeniesSenderOutsideTheList(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter(
        {"private_chat_strategy": "whitelist", "whitelist_users": "ou_ok"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_intruder")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_whitelistAllowsListedSender(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter(
        {"private_chat_strategy": "whitelist", "whitelist_users": "ou_ok,ou_2"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_ok")) == ["pong"]
    assert agent.calls == ["嗨"]


@pytest.mark.asyncio
async def test_whitelistListFormIsAccepted(manager):
    """配置面有逗号串，也有 JSON 数组；两种形态必须同一口径。"""
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter(
        {"private_chat_strategy": "whitelist", "whitelist_users": ["ou_ok"]})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_ok")) == ["pong"]
    assert await handler(_msg(sender="ou_other")) is None


@pytest.mark.asyncio
async def test_emptyWhitelistDeniesEveryone(manager):
    """配了 whitelist 却没填人＝谁都别放进来（缺省失败方向朝拒绝）。"""
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter(
        {"private_chat_strategy": "whitelist", "whitelist_users": ""})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_9")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_unknownStrategyFailsClosed(manager):
    """策略值拼错（或旧版本枚举）不得当 open 放行——失败方向朝拒绝。"""
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter({"private_chat_strategy": "opne"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_9")) is None
    assert agent.calls == []


@pytest.mark.asyncio
async def test_groupStrategyIsReadFromGroupConfigNotPrivate(manager):
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter(
        {"private_chat_strategy": "open", "group_chat_strategy": "whitelist",
         "whitelist_users": "ou_ok"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_other", chat_type="group")) is None
    assert await handler(_msg(sender="ou_ok", chat_type="group")) == ["pong"]
    # 私聊仍按 private 策略 open 放行
    assert await handler(_msg(sender="ou_other", chat_type="p2p")) == ["pong"]


@pytest.mark.asyncio
async def test_missingStrategyKeepsOpenDefault(manager):
    """未配置时保持既有产品默认 open（本批不翻默认，只堵 fail-open 的显式配置）。"""
    agent = FakeAgent()
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_9")) == ["pong"]


@pytest.mark.asyncio
async def test_instanceAttributesCarryTheStrategyWhenExtraIsEmpty(manager):
    """Gen2 适配器把策略读成实例属性：路由层必须能看到（否则配了也等于没配）。"""
    agent = FakeAgent()
    manager._adapters["feishu"] = _AttrAdapter("whitelist", ["ou_ok"])
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_intruder")) is None
    assert await handler(_msg(sender="ou_ok")) == ["pong"]


@pytest.mark.asyncio
async def test_ilinkStyleConfigKeysAreNormalized(manager):
    """iLink 配置面的键名是 `private_strategy`，同一个判定必须认它。"""
    agent = FakeAgent()
    manager._adapters["feishu"] = _CfgAdapter(
        {"private_strategy": "whitelist", "whitelist_users": "ou_ok"})
    handler = channel_router.make_handler(manager, agent_lookup=lambda aid: agent)
    assert await handler(_msg(sender="ou_intruder")) is None
    assert await handler(_msg(sender="ou_ok")) == ["pong"]
