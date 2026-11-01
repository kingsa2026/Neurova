# -*- coding: utf-8 -*-
"""渠道回合期间的「人在等」窗口（D-1 ③）。

语义：入站人类消息进入分发、到本轮回复真正发出之前，这个会话处于「人在等」；
此时同会话的自动/提醒消息（当前唯一的自动渠道出口是审批通知）被压住，回合
结束后补发最新一条。压住不丢：释放时冲洗；回合异常/无回复也必须释放。

为什么挂在 `_dispatch_message`：它是「handler 执行 + 回复发送」的唯一包络，
比 handler 内部早退点更接近「回复落盘」这个事实边界。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.channels import attention_budget
from neurova.channels.attention_budget import getAttentionBudget
from neurova.channels.base import ChannelMessage
from neurova.channels.manager import ChannelManager


class _RecordingAdapter:
    channel_type = "feishu"
    is_connected = True

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, content, message_type="text", **kw):
        self.sent.append(content)
        return "mid"


def _msg(chat_id="oc_1", content="嗨"):
    return ChannelMessage(
        channel_type="feishu", message_id="m1", sender_id="ou_9", sender_name="ou_9",
        content=content, chat_id=chat_id, chat_type="p2p",
        metadata={"agent_id": "default"},
    )


@pytest.fixture
def manager():
    ChannelManager._instance = None
    attention_budget.resetAttentionBudgetForTests()
    m = ChannelManager()
    m._adapters["feishu"] = _RecordingAdapter()
    yield m
    ChannelManager._instance = None
    attention_budget.resetAttentionBudgetForTests()


@pytest.mark.asyncio
async def testTurnHoldsSameChatAutoMessagesUntilReplyIsSent(manager):
    gate = asyncio.Event()

    async def slowHandler(message):
        await gate.wait()
        return "回复"

    manager.add_message_handler(slowHandler)
    autoSent = []

    async def autoSend(text):
        autoSent.append(text)
        return "mid"

    task = asyncio.create_task(manager._dispatch_message(_msg()))
    await asyncio.sleep(0)  # 让 handler 进入等待

    result = await getAttentionBudget().deliver(
        "approval:feishu:oc_1:x", "审批请求", autoSend, holdKey="chat:feishu:oc_1")
    assert result.held, "人在等的窗口里，自动提醒应被压住"
    assert autoSent == []

    gate.set()
    await task
    assert manager._adapters["feishu"].sent == ["回复"]
    assert autoSent == ["审批请求"], "回合结束后必须补发，压住不等于丢"


@pytest.mark.asyncio
async def testTurnHoldsNothingForAnotherChat(manager):
    gate = asyncio.Event()

    async def slowHandler(message):
        await gate.wait()
        return "回复"

    manager.add_message_handler(slowHandler)
    autoSent = []

    async def autoSend(text):
        autoSent.append(text)
        return "mid"

    task = asyncio.create_task(manager._dispatch_message(_msg(chat_id="oc_1")))
    await asyncio.sleep(0)

    result = await getAttentionBudget().deliver(
        "approval:feishu:oc_2:x", "另一会话的审批", autoSend, holdKey="chat:feishu:oc_2")
    assert not result.held
    assert autoSent == ["另一会话的审批"]

    gate.set()
    await task


@pytest.mark.asyncio
async def testFailedTurnStillReleasesTheHold(manager):
    async def failingHandler(message):
        raise RuntimeError("agent 挂了")

    manager.add_message_handler(failingHandler)
    autoSent = []

    async def autoSend(text):
        autoSent.append(text)
        return "mid"

    await manager._dispatch_message(_msg())
    result = await getAttentionBudget().deliver(
        "approval:feishu:oc_1:y", "审批请求", autoSend, holdKey="chat:feishu:oc_1")
    assert not result.held, "回合已失败收场，窗口必须释放"
    assert autoSent == ["审批请求"]
