# -*- coding: utf-8 -*-
"""出口注意力预算（D-1 甲案：① 同键未发出被新值覆盖 ② 同键严格排队）。

立项理由（本仓可核实）：全仓节流词汇都指向上游限流/模型退避，出站侧没有任何
「同一件事不重复说 / 同键排队」的落点。本批只覆盖**显式标记的主动/提醒出口**：
调用方传 `attentionKey` 才进预算；Agent 对用户这一问的正文回复永不走这里。

甲案明确不做第三件（人未答复时压住自动输入）：本仓没有「人在等答复」信号
（`awaiting_reply/unanswered` 零命中，question_queue 的 ASKED 在聊天里不被识别），
没有信号就接线等于造假。机制不先落空壳。
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.channels.attention_budget import (
    getAttentionBudget,
    resetAttentionBudgetForTests,
)


@pytest.fixture(autouse=True)
def _freshBudget():
    resetAttentionBudgetForTests()
    yield
    resetAttentionBudgetForTests()


@pytest.mark.asyncio
async def testUnsentSameKeyIsOverwrittenByTheLatest():
    sent = []
    gate = asyncio.Event()

    async def send(text):
        sent.append(text)
        if text == "A":
            await gate.wait()
        return text

    budget = getAttentionBudget()
    first = asyncio.create_task(budget.deliver("chat:1:approval", "A", send))
    await asyncio.sleep(0)  # 让 A 进入在发状态

    r2 = await budget.deliver("chat:1:approval", "B", send)
    r3 = await budget.deliver("chat:1:approval", "C", send)
    assert r2.coalesced and r3.coalesced, "B/C 都未发出，应是合并而不是排队等发"

    gate.set()
    result = await first
    assert sent == ["A", "C"], "未发出的同名只保留最新值（B 被 C 覆盖）"
    assert result.message_id == "C"


@pytest.mark.asyncio
async def testSameKeySendsNeverOverlap():
    active = 0
    maxActive = 0

    async def send(text):
        nonlocal active, maxActive
        active += 1
        maxActive = max(maxActive, active)
        await asyncio.sleep(0.01)
        active -= 1
        return text

    budget = getAttentionBudget()
    first = asyncio.create_task(budget.deliver("k", "A", send))
    await asyncio.sleep(0)
    await budget.deliver("k", "B", send)
    await first
    assert maxActive == 1, "同键发送必须严格串行"


@pytest.mark.asyncio
async def testDifferentKeysAreIndependent():
    started = []

    async def send(text):
        started.append(text)
        await asyncio.sleep(0.05)
        return text

    budget = getAttentionBudget()
    t1 = asyncio.create_task(budget.deliver("k1", "A", send))
    t2 = asyncio.create_task(budget.deliver("k2", "B", send))
    await asyncio.sleep(0.01)
    assert set(started) == {"A", "B"}, "不同键不得互相阻塞"
    await asyncio.gather(t1, t2)


@pytest.mark.asyncio
async def testFailurePropagatesAndReleasesTheKey():
    async def boom(text):
        raise RuntimeError("send failed")

    budget = getAttentionBudget()
    with pytest.raises(RuntimeError):
        await budget.deliver("k", "A", boom)

    async def ok(text):
        return "mid"

    result = await budget.deliver("k", "B", ok)
    assert result.message_id == "mid", "失败后键必须释放，后续消息还能发"
