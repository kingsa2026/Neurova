"""EventBus 异步订阅在不完整运行态下的"不静默丢"契约（交接文档 2026-10-31 §6）。

两个分支都必须留下可检索痕迹：
1. 没有异步队列（总线不在运行中的事件循环里 start）→ 计数 + 告警；
2. 队列在、但归属 loop 未知（仅防御分支）→ debug 痕迹，且不吞事件。
"""

import asyncio
import logging

from neurova.core.event_bus import EventBus


async def _asyncHandler(event):  # noqa: ANN001 - 事件对象形状由 EventBus 决定
    return None


def test_no_async_queue_is_counted_and_logged(caplog):
    bus = EventBus()
    bus.subscribe("no.loop", _asyncHandler)

    with caplog.at_level(logging.WARNING, logger="neurova.core.event_bus"):
        bus.publish("no.loop")

    assert bus.droppedAsyncCount() == 1
    assert any("无异步队列" in record.getMessage() for record in caplog.records)
    bus.stop()


def test_queue_without_owner_loop_leaves_a_trace(caplog):
    bus = EventBus()
    bus.subscribe("ownerless.loop", _asyncHandler)
    bus._async_queue = asyncio.Queue()  # 仅构造防御分支所需状态：队列在、归属 loop 未知

    with caplog.at_level(logging.DEBUG, logger="neurova.core.event_bus"):
        bus.publish("ownerless.loop")

    assert any("no owner loop" in record.getMessage() for record in caplog.records)
    assert bus._async_queue.qsize() == 1
    bus.stop()
