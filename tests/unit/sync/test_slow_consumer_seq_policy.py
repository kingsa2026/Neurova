"""seq 慢消费者两条例边界纪律（OpenClaw 启发 P0-7）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-7）：
  OpenClaw 的 server-broadcast 把 seq 语义推到崩溃/慢读边界，两条铁律：
  (a) 慢消费者丢帧也推进 seq——让客户端 gap 掐测器看见丢失，重连后
      sync_resume 补发恢复；绝不为了等一个慢客户端阻塞整场广播。
  (b) 序列化失败不推进 seq——毒帧若已盖章进历史，所有客户端的 gap
      探测器会同时触发（重连风暴），且每次重连重放都会在同一帧卡壳。

Neurova 落点（与 OpenOcta P0-1 seq 盖章机制的衔接）：
  - (b)：broadcast_event / broadcast_event_sync 在 add_event 盖章**前**
    做序列化预检（to_json 无副作用），失败则不入历史不盖章。
  - (a)：_send_to_channel 单帧发送超时（slow_consumer_send_timeout），
    超时丢帧——seq 已在 add_event 盖章推进，客户端 gap 探测器看见丢失。
"""
from __future__ import annotations

import asyncio
import time

import pytest


@pytest.fixture
def sync_manager():
    from neurova.sync.session_sync_manager import SessionSyncManager

    mgr = SessionSyncManager(config={"max_sessions": 100, "session_timeout": 3600})
    mgr._slow_consumer_send_timeout = 0.1
    return mgr


def _poison_event():
    """构造在 to_json() 序列化边界真实失败的毒事件。

    _json_safe 对不可序列化对象会回退 str() 兜底——常规毒载荷（callable/
    datetime/set）都被它消化了。要让序列化真失败，对象的 __str__ 本身
    必须抛错（对抗性载荷，_json_safe 的 str() 兜底随之炸穿）。
    """
    from neurova.sync.session_sync_manager import EventType, SessionEvent

    class Boom:
        def __str__(self):
            raise RuntimeError("adversarial __str__")

    return SessionEvent(event_type=EventType.AGENT_REPLY, payload={"content": Boom()})


class TestSerializationFailureNoSeqAdvance:
    """铁律 (b)：序列化失败不推进 seq。"""

    def test_broadcast_poison_event_returns_zero(self, sync_manager):
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        sync_manager.register_or_create_session(session_id="s-poison-1", user_id="u-test")
        ev = _poison_event()

        sent = asyncio.run(sync_manager.broadcast_event("s-poison-1", ev))
        assert sent == 0

    def test_poison_event_not_stamped_not_in_history(self, sync_manager):
        session = sync_manager.register_or_create_session(session_id="s-poison-2", user_id="u-test")
        ev = _poison_event()

        asyncio.run(sync_manager.broadcast_event("s-poison-2", ev))

        assert ev.seq is None, "毒帧不得盖章（否则客户端 gap 掐测器集体触发 → 重连风暴）"
        assert all(e.event_id != ev.event_id for e in session.history), "毒帧不得进入历史（重放会在同一帧卡壳）"

    def test_seq_not_consumed_after_poison(self, sync_manager):
        """毒帧失败后发号器不前跳——后续好事件必须无 gap。"""
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-poison-3", user_id="u-test")
        baseline = session.next_seq

        asyncio.run(sync_manager.broadcast_event("s-poison-3", _poison_event()))
        assert session.next_seq == baseline, "序列化失败不得消耗 seq"

        good = SessionEvent(event_type=EventType.USER_MESSAGE, payload={"content": "ok"})
        asyncio.run(sync_manager.broadcast_event("s-poison-3", good))
        assert good.seq == baseline, "毒帧之后的好事件必须拿到毒帧本应拿到的 seq（无 gap）"

    def test_sync_broadcast_poison_event_no_seq_advance(self, sync_manager):
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-poison-4", user_id="u-test")
        baseline = session.next_seq

        sync_manager.broadcast_event_sync("s-poison-4", _poison_event())

        assert session.next_seq == baseline
        assert all(e.seq != baseline for e in session.history)

        good = SessionEvent(event_type=EventType.USER_MESSAGE, payload={"content": "ok"})
        sync_manager.broadcast_event_sync("s-poison-4", good)
        assert good.seq == baseline


class TestSlowConsumerDropFrame:
    """铁律 (a)：慢消费者丢帧也推进 seq，不阻塞其他渠道。"""

    def _make_manager_with_slow_channel(self, sync_manager):
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-slow", user_id="u-test")

        received_fast = []

        async def slow_send(event):
            await asyncio.sleep(999)

        def fast_send(event):
            received_fast.append(event)

        session.register_channel("slow", slow_send)
        session.register_channel("fast", fast_send)
        return session, received_fast

    def test_slow_channel_does_not_block_broadcast(self, sync_manager):
        session, received_fast = self._make_manager_with_slow_channel(sync_manager)

        start = time.monotonic()
        sent = asyncio.run(sync_manager.broadcast_event("s-slow", _good_event()))
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"广播被慢渠道阻塞 {elapsed:.2f}s（应为 slow_consumer_send_timeout 量级）"
        assert sent >= 1, "快渠道应正常送达"
        assert len(received_fast) == 1, "慢渠道丢帧不得影响其他渠道收帧"

    def test_dropped_frame_still_advances_seq(self, sync_manager):
        """丢帧也推进 seq：慢渠道丢的帧在历史里有 seq，客户端重连可补发。"""
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session, _ = self._make_manager_with_slow_channel(sync_manager)

        ev = SessionEvent(event_type=EventType.AGENT_REPLY, payload={"i": 0})
        asyncio.run(sync_manager.broadcast_event("s-slow", ev))

        assert ev.seq is not None, "丢帧必须已盖章 seq（gap 掐测器看见丢失）"
        assert any(e.event_id == ev.event_id for e in session.history), "丢帧必须留在历史中供 sync_resume 补发"


def _good_event():
    from neurova.sync.session_sync_manager import EventType, SessionEvent

    return SessionEvent(event_type=EventType.AGENT_REPLY, payload={"content": "ok"})
