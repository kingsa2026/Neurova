"""回归测试：入站持久化队列 C-06 / C-07 修复。

- C-06: ChannelManager.stop() 此前读 `_ingress_queue`（恒 None），
  排水任务永不停止 → stop() 必须能停止注入的 `ingress_queue` 排水循环。
- C-07: manager 此前把 `enqueue()` 返回 False（重复消息去重）当
  "队列不可用 fail-open" 再直发一次 → 平台重发消息被投递两次。
  修复后：False=去重丢弃；DB 故障抛 IngressQueueUnavailable 才 fail-open。
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from neurova.channels.base import ChannelEventType, ChannelMessage
from neurova.channels.channel_ingress_queue import (
    ChannelIngressQueue,
    IngressQueueUnavailable,
)
from neurova.channels.manager import ChannelManager


def _msg(mid: str = "m1", content: str = "hello") -> ChannelMessage:
    return ChannelMessage(
        channel_type="feishu",
        message_id=mid,
        sender_id="u1",
        sender_name="tester",
        content=content,
        chat_id="chat1",
    )


class TestC07DedupeNoDoubleDispatch:
    """C-07: 去重消息不得二次分发。"""

    @pytest.mark.asyncio
    async def test_pending_duplicate_not_dispatched(self, tmp_path):
        """C-07 核心：pending 状态的重复消息不得绕过队列直发（双投递）。

        此前 manager 把 enqueue()==False（去重）当"队列不可用 fail-open"
        直接 _dispatch_message，与后台排水构成双投递。
        """
        manager = ChannelManager()
        handler = AsyncMock(return_value=None)
        manager.set_message_handler(handler)
        queue = ChannelIngressQueue(tmp_path / "ingress.db")
        manager.ingress_queue = queue
        try:
            # 预置一条 pending 消息（模拟另一 worker 已入队尚未消费）
            queue.enqueue(_msg())
            # 同一消息再次到达 → enqueue 去重返回 False → 必须丢弃而非直发
            await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, _msg())
            assert handler.await_count == 0, "pending 重复消息不允许绕过队列直发"
        finally:
            queue.close()

    @pytest.mark.asyncio
    async def test_done_redelivery_reopens_by_design(self, tmp_path):
        """文档化既有语义：已 done 的平台重发重开为 pending 再投一次
        （channel_ingress_queue.enqueue 注释声明的设计行为）。"""
        manager = ChannelManager()
        handler = AsyncMock(return_value=None)
        manager.set_message_handler(handler)
        queue = ChannelIngressQueue(tmp_path / "ingress.db")
        manager.ingress_queue = queue
        try:
            await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, _msg())
            assert handler.await_count == 1
            # done 后重投 → 重开 → 再次投递（设计行为）
            assert queue.enqueue(_msg()) is True
        finally:
            queue.close()

    @pytest.mark.asyncio
    async def test_db_failure_fails_open_to_direct_dispatch(self, tmp_path):
        """DB 故障（IngressQueueUnavailable）→ fail-open 直发，消息不丢。"""
        manager = ChannelManager()
        handler = AsyncMock(return_value=None)
        manager.set_message_handler(handler)
        queue = ChannelIngressQueue(tmp_path / "ingress.db")
        manager.ingress_queue = queue
        try:
            # 模拟 DB 故障：关闭底层连接后 enqueue 必抛 IngressQueueUnavailable
            queue.close()
            with pytest.raises(IngressQueueUnavailable):
                queue.enqueue(_msg())

            await manager._on_channel_event(ChannelEventType.MESSAGE_RECEIVED, _msg())
            assert handler.await_count == 1, "队列故障时应 fail-open 直发一次"
        finally:
            pass


class TestC06StopStopsDrain:
    """C-06: stop() 停止排水任务。"""

    @pytest.mark.asyncio
    async def test_stop_uses_correct_attribute(self, tmp_path):
        manager = ChannelManager()
        queue = ChannelIngressQueue(tmp_path / "ingress.db")
        manager.ingress_queue = queue

        async def handler(msg):
            return None

        queue.start_drain(handler, poll_interval=0.05)
        await manager.stop()

        assert queue._drain_task is None or queue._drain_task.done(), (
            "stop() 后排水任务必须已停止（C-06: 此前读错属性名恒 None，排水永不停止）"
        )
        queue.close()
