"""SessionEvent seq 契约测试（OpenOcta 启发 P0-1：WS 单调 seq + 前端 gap 检测）

背景（docs/Neurova_OpenOcta代码级对比_2026-09-04.md #1）：
  OpenOcta 的 WS Hub 给每个事件帧分配服务端单调 seq，前端 onGap 检测缺口——
  这是"断线重连 replay"可靠性的地基。Neurova 的 SessionEvent 此前完全无 seq。

设计要点（与 OpenOcta 的关键差异）：
  OpenOcta 是全局单事件流，全局 seq 即可；Neurova 的 sync WS 按 session 订阅
  （/ws/{session_id}），客户端只看到本会话事件——若用全局发号器，其他会话的
  消耗会让本会话 seq 跳号，前端永远误报 gap。因此发号器必须 **per-session
  单调**：挂在 UnifiedSession.add_event（所有事件进历史/出站的唯一咽喉，
  且全部调用点已在 SessionSyncManager._lock 内），从 1 递增。

前端契约：
  - SessionEvent 帧（含 event_type）携带 seq: int
  - 客户端收到 seq > lastSeq+1 判定缺口（丢帧数 = seq - lastSeq - 1）
  - 重连后服务端重放历史（同样带 seq），游标自然重建

账目说明：register_or_create_session 会先写一条 SESSION_CREATED 系统事件
（seq=1），后续手动事件从 2 起。
"""
from __future__ import annotations

import asyncio
import json

import pytest


@pytest.fixture
def sync_manager():
    from neurova.sync.session_sync_manager import SessionSyncManager

    return SessionSyncManager(config={"max_sessions": 100, "session_timeout": 3600})


class TestSessionEventSeqStamping:
    """seq 盖章：进历史即发号，per-session 单调。"""

    def test_add_event_stamps_monotonic_seq(self, sync_manager):
        """事件经 add_event 进历史时获得从 1 起递增的 seq（含注册时的系统事件）。"""
        session = sync_manager.register_or_create_session(session_id="s-seq-1", user_id="u-test")
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        for i in range(3):
            session.add_event(SessionEvent(event_type=EventType.USER_MESSAGE, payload={"i": i}))

        seqs = [e.seq for e in session.history]
        # 首条是 register_or_create_session 写入的 SESSION_CREATED（seq=1）
        assert seqs == [1, 2, 3, 4], f"期望 [1,2,3,4]（per-session 单调递增），got {seqs}"

    def test_seq_monotonic_via_broadcast(self, sync_manager):
        """经 manager.broadcast_event 广播的事件同样盖章（咽喉点在 add_event）。"""
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-seq-2", user_id="u-test")

        async def _run():
            for i in range(2):
                ev = SessionEvent(event_type=EventType.AGENT_REPLY, payload={"i": i})
                await sync_manager.broadcast_event("s-seq-2", ev)

        asyncio.run(_run())

        seqs = [e.seq for e in session.history]
        assert seqs == [1, 2, 3], f"广播事件应单调盖章（1=SESSION_CREATED），got {seqs}"

    def test_seq_independent_per_session(self, sync_manager):
        """不同 session 的 seq 各自独立——否则跨会话跳号会让前端误报 gap。"""
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        sa = sync_manager.register_or_create_session(session_id="s-a", user_id="u-test")
        sb = sync_manager.register_or_create_session(session_id="s-b", user_id="u-test")

        for _ in range(3):
            sa.add_event(SessionEvent(event_type=EventType.USER_MESSAGE))
        sb.add_event(SessionEvent(event_type=EventType.USER_MESSAGE))

        # sa: 1(系统)+3 = 4；sb 未受 sa 的 3 次消耗影响：1(系统)+1 = 2
        assert sa.history[-1].seq == 4
        assert sb.history[-1].seq == 2, "session-b 的发号不应受 session-a 消耗影响（独立计数器）"

    def test_session_created_event_also_stamped(self, sync_manager):
        """系统事件（SESSION_CREATED 等）也走 add_event，同样有 seq。"""
        session = sync_manager.register_or_create_session(session_id="s-sys", user_id="u-test")
        assert session.history, "register_or_create_session 应写入 SESSION_CREATED 系统事件"
        assert all(e.seq is not None for e in session.history)


class TestSessionEventSeqSerialization:
    """seq 出站契约：to_dict/to_json 带出，from_dict 兼容缺省。"""

    def test_to_dict_includes_seq(self, sync_manager):
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-dict", user_id="u-test")
        ev = SessionEvent(event_type=EventType.USER_MESSAGE, payload={"content": "hi"})
        session.add_event(ev)

        data = ev.to_dict()
        assert data["seq"] == ev.seq and isinstance(data["seq"], int)

    def test_to_json_includes_seq(self, sync_manager):
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-json", user_id="u-test")
        ev = SessionEvent(event_type=EventType.AGENT_STREAM_CHUNK, payload={"text": "x"})
        session.add_event(ev)

        parsed = json.loads(ev.to_json())
        assert parsed["seq"] == ev.seq

    def test_from_dict_tolerates_missing_seq(self):
        """旧数据（无 seq 的历史/持久化）反序列化不崩，seq 保持 None。"""
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        legacy = {"event_id": "evt_x", "event_type": "user_message", "session_id": "s", "source_channel": "web"}
        ev = SessionEvent.from_dict(legacy)
        assert ev.seq is None

    def test_history_replay_carries_seq(self, sync_manager):
        """断线重连时服务端重放 get_history()——重放帧必须带 seq 供游标重建。"""
        from neurova.sync.session_sync_manager import EventType, SessionEvent

        session = sync_manager.register_or_create_session(session_id="s-replay", user_id="u-test")
        for i in range(5):
            session.add_event(SessionEvent(event_type=EventType.AGENT_STREAM_CHUNK, payload={"i": i}))

        replayed = session.get_history(limit=50)
        assert [e.seq for e in replayed] == [1, 2, 3, 4, 5, 6]
