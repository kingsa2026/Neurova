# -*- coding: utf-8 -*-
"""D6 接线做实判据（2026-11-14 死码退役批 B-5）。

EventBusEnhanced 转正当作全局总线（get_event_bus() 即增强版），并补完两处半成品：
- 死信自动落库：handler 异常不再只记日志，自动进死信队列（同步/异步/队列消费三路）
- 事件超时真实现：set_event_timeout 对异步处理器以 asyncio.wait_for 强制执行，
  超时异常走同一死信通道（同步处理器不可安全打断——如实限定异步路径）
"""
from __future__ import annotations

import asyncio

import pytest

from neurova.core.event_bus import get_event_bus, reset_event_bus
from neurova.core.event_bus_enhanced import (
    EventBusEnhanced,
    get_event_bus_enhanced,
)


@pytest.fixture
def bus():
    module = EventBusEnhanced()
    module.start()
    yield module
    module.stop()


def testGlobalBusIsEnhancedAndSingletonsShareOneInstance():
    try:
        bus = get_event_bus()
        assert isinstance(bus, EventBusEnhanced)
        assert get_event_bus_enhanced() is bus
    finally:
        reset_event_bus()


def testSyncHandlerFailureAutoDeadLetters(bus):
    def boom(_event):
        raise ValueError("同步处理器爆炸")

    bus.subscribe("x", boom)
    bus.publish("x", data="payload")
    letters = bus.get_dead_letters()
    assert len(letters) == 1
    assert letters[0].event.name == "x"
    assert isinstance(letters[0].error, ValueError)


def testAsyncHandlerFailureAutoDeadLetters(bus):
    async def boom(_event):
        raise RuntimeError("异步处理器爆炸")

    bus.subscribe("x", boom)
    asyncio.run(bus.publish_async("x", data="payload"))
    letters = bus.get_dead_letters()
    assert len(letters) == 1
    assert isinstance(letters[0].error, RuntimeError)


def testTimeoutEnforcedOnAsyncHandler(bus):
    async def slow(_event):
        await asyncio.sleep(0.5)
        return "done"

    bus.subscribe("slow_event", slow)
    bus.set_event_timeout("slow_event", 0.05)
    asyncio.run(bus.publish_async("slow_event", data="payload"))
    letters = bus.get_dead_letters()
    assert len(letters) == 1
    assert isinstance(letters[0].error, asyncio.TimeoutError)


def testTimeoutNotAppliedWhenUnset(bus):
    async def fast(_event):
        return "ok"

    bus.subscribe("fast_event", fast)
    results = asyncio.run(bus.publish_async("fast_event", data="payload"))
    assert results == ["ok"]
    assert len(bus.get_dead_letters()) == 0
