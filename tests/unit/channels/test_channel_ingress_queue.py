"""渠道入站持久化队列测试（OpenClaw 启发 P0-5）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-5 / §2.8）：
  OpenClaw 的入站是持久化队列（SQLite channel_ingress_events + claim 租约
  + tombstone 幂等去重 + dead-letter），重启不丢消息。Neurova 14 渠道
  入站全内存直调，handler 异常即丢、进程重启即丢——可用性硬伤。

铁律落点：
  1. _on_channel_event 的 MESSAGE_RECEIVED 入队（先持久化再分发）；
  2. claim 租约排水：按 chat_id lane 串行，attempt 计数，超限 dead-letter；
  3. tombstone 去重：同 (channel_type, message_id) 幂等；
  4. 重启恢复：排水器启动时把 pending/processing 的遗留消息重新入列。
"""
from __future__ import annotations

import asyncio
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue


@pytest.fixture
def queue(tmp_path):
    q = ChannelIngressQueue(db_path=tmp_path / "ingress.db")
    yield q
    q.close()


def _msg(mid="m1", chat="c1", channel="feishu", content="hello") -> ChannelMessage:
    return ChannelMessage(
        channel_type=channel,
        message_id=mid,
        sender_id="u1",
        sender_name="User",
        content=content,
        chat_id=chat,
    )


class TestEnqueueAndClaim:
    """入队 + claim 租约排水。"""

    def test_enqueue_persists_to_sqlite(self, queue):
        queue.enqueue(_msg())
        with sqlite3.connect(queue.db_path) as conn:
            row = conn.execute(
                "SELECT channel_type, message_id, status FROM channel_ingress_events"
            ).fetchone()
        assert row[0] == "feishu" and row[1] == "m1" and row[2] == "pending"

    def test_tombstone_dedup(self, queue):
        """同 (channel, message_id) 重复入队幂等（平台重发/重试不重复处理）。"""
        assert queue.enqueue(_msg()) is True
        assert queue.enqueue(_msg()) is False, "重复 message_id 必须被 tombstone 去重"

    def test_claim_lease_and_complete(self, queue):
        queue.enqueue(_msg())
        ev = queue.claim(worker="w1")
        assert ev is not None
        assert ev.message.message_id == "m1"
        # processing 中的消息不被二次 claim
        assert queue.claim(worker="w1") is None
        queue.ack(ev.event_id)
        assert queue.claim(worker="w1") is None, "ack 后不再投递"

    def test_nack_requeues_with_attempt(self, queue):
        queue.enqueue(_msg())
        ev = queue.claim(worker="w1")
        queue.nack(ev.event_id)
        ev2 = queue.claim(worker="w1")
        assert ev2 is not None
        assert ev2.attempt == 2, "nack 后重新入列且 attempt 递增"

    def test_dead_letter_after_max_attempts(self, queue):
        q = ChannelIngressQueue(db_path=queue.db_path, max_attempts=2)
        q.enqueue(_msg(mid="dl1"))
        for _ in range(2):
            ev = q.claim(worker="w1")
            q.nack(ev.event_id)
        assert q.claim(worker="w1") is None, "超过 max_attempts 进入 dead-letter"
        dead = q.list_dead_letters()
        assert len(dead) == 1 and dead[0]["message_id"] == "dl1"

    def test_dead_letter_requeue(self, queue):
        q = ChannelIngressQueue(db_path=queue.db_path, max_attempts=1)
        q.enqueue(_msg(mid="dl2"))
        ev = q.claim(worker="w1")
        q.nack(ev.event_id)
        assert q.list_dead_letters()
        assert q.requeue_dead_letters() == 1
        assert q.list_dead_letters() == []
        assert q.claim(worker="w1") is not None


class TestRestartRecovery:
    """重启不丢消息：遗留 pending/processing 在新实例排水时恢复。"""

    def test_processing_recovered_after_reopen(self, queue):
        queue.enqueue(_msg(mid="r1"))
        ev = queue.claim(worker="w1")
        assert ev is not None
        queue.close()  # 模拟崩溃：processing 无 ack

        q2 = ChannelIngressQueue(db_path=queue.db_path)
        ev2 = q2.claim(worker="w2")
        assert ev2 is not None, "重启后遗留 processing 必须可重新 claim"
        assert ev2.message.message_id == "r1"
        q2.close()

    def test_pending_survives_reopen(self, queue):
        queue.enqueue(_msg(mid="r2"))
        queue.enqueue(_msg(mid="r3"))
        queue.close()

        q2 = ChannelIngressQueue(db_path=queue.db_path)
        claimed = [q2.claim(worker="w").message.message_id for _ in range(2)]
        assert sorted(claimed) == ["r2", "r3"]
        q2.close()


class TestDrainLoop:
    """排水循环：入队 → handler 消费 → ack。"""

    def test_drain_processes_and_acks(self, queue):
        received = []

        async def handler(msg):
            received.append(msg.message_id)
            return "ok"

        async def _run():
            queue.start_drain(handler, poll_interval=0.01)
            queue.enqueue(_msg(mid="d1"))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if received:
                    break
            await queue.stop_drain()

        asyncio.run(_run())
        assert received == ["d1"]

    def test_handler_failure_nacks_not_drops(self, queue):
        """handler 抛异常消息不丢（nack 重新入列），最终进 dead-letter。"""
        calls = {"n": 0}

        async def handler(msg):
            calls["n"] += 1
            raise RuntimeError("boom")

        q = ChannelIngressQueue(db_path=queue.db_path, max_attempts=1)

        async def _run():
            q.start_drain(handler, poll_interval=0.01)
            q.enqueue(_msg(mid="f1"))
            for _ in range(100):
                await asyncio.sleep(0.01)
                if q.list_dead_letters():
                    break
            await q.stop_drain()

        asyncio.run(_run())
        assert calls["n"] == 1
        assert q.list_dead_letters()[0]["message_id"] == "f1"
        q.close()


class TestStats:
    """队列状态（前端渠道页展示用）。"""

    def test_stats_shape(self, queue):
        queue.enqueue(_msg(mid="s1"))
        queue.enqueue(_msg(mid="s2", chat="c2"))
        stats = queue.stats()
        assert stats["pending"] == 2
        assert stats["processing"] == 0
        assert stats["dead_letter"] == 0
        assert stats["processed_total"] == 0
