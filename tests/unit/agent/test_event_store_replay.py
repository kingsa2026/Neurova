# -*- coding: utf-8 -*-
"""A2 全局事件库 + 重放/快照协议（追平 T3 Code 事件溯源，计划批二）。

被测模块：`neurova/agent/swarm_event_store.py`（独立模块，本批不接线
swarm_event_log 与 WS 面）。

断言全部落在**真实 SQLite 行为**上（tmp_path 临时文件库 + 真连接，
无 MagicMock 充当数据库）：
- 全局 seq 严格单调：跨流交错追加与并发追加都不重不回退；
- 同 event_id 幂等重写返回既有 seq（镜像双写不重放副作用）；
- readStream 按 after_seq 分页不重不漏，且只含本流；
- replayThrough 正常段/空段/超事件数降级/超字节降级——降级必为
  从 after_seq+1 起的连续前缀，绝不跳条目部分回放；
- cursor 落在 pruned-through 之下 → 明确降级快照信号；
- snapshotStream 全量快照（snapshot_sequence = 全局 high water）；
- pruneCovered 窗口外删、每流最新保留、pruned_through 先发布再删、
  窗口内不删；
- mirrorFromLedger 按 event_id 幂等（重复镜像不重写），缺 event_id
  的行跳过不计。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from neurova.agent.swarm_event_store import (
    EVENT_STORE_DB_DOMAIN,
    DEFAULT_REPLAY_MAX_BYTES,
    DEFAULT_REPLAY_MAX_EVENTS,
    SwarmEventStore,
    SwarmEventStoreError,
    mirrorFromLedger,
)
from neurova.core.db_migration import (
    SchemaVersionError,
    latest_version,
    registered_domains,
    schema_version,
)


@pytest.fixture
def store(tmp_path):
    """每个用例一份独立临时文件库；用例结束显式关闭（Windows 释放文件句柄）。"""
    s = SwarmEventStore(str(tmp_path / "swarm_events.db"))
    yield s
    s.close()


def _encodedBytes(event: dict) -> int:
    return len(json.dumps(event, ensure_ascii=False).encode("utf-8"))


def _isoAt(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


# ── 全局单调 seq ──


class TestGlobalSequence:
    def test_globalSeqStrictlyMonotonicAcrossStreams(self, store):
        """跨流交错追加：全局 seq 严格递增，各流内部也保持相对先后。"""
        streams = ["stream-a", "stream-b", "stream-c"]
        seqs = []
        for i in range(9):
            seqs.append(store.append(streams[i % 3], "member_chunk", {"i": i}))
        assert seqs == sorted(seqs), "全局 seq 应随追加严格递增"
        assert len(set(seqs)) == len(seqs), "全局 seq 不得重复"
        assert seqs == list(range(1, 10)), f"应从 1 起连续分配，实际 {seqs}"
        assert store.highWater() == 9

        # 各流内部：相对先后与全局序一致
        for sid in streams:
            streamSeqs = [e["seq"] for e in store.readStream(sid)]
            assert streamSeqs == sorted(streamSeqs)

    def test_concurrentAppendsGlobalSeqUniqueAndIncreasing(self, store):
        """多线程共享同一 store（check_same_thread=False + RLock）：seq 唯一不重。"""
        workers = 8
        perWorker = 5
        barrier = threading.Barrier(workers)
        failures = []

        def worker(index: int) -> None:
            barrier.wait()
            try:
                for i in range(perWorker):
                    store.append(f"stream-{index}", "member_chunk", {"i": i})
            except Exception as exc:  # pragma: no cover - 失败要显性化
                failures.append(repr(exc))

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(workers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not failures, f"并发追加抛错：{failures}"

        total = workers * perWorker
        assert store.highWater() == total
        allSeqs = []
        for n in range(workers):
            allSeqs.extend(e["seq"] for e in store.readStream(f"stream-{n}"))
        assert len(allSeqs) == total
        assert len(set(allSeqs)) == total, "并发写入的全局 seq 不得重复"
        assert set(allSeqs) == set(range(1, total + 1)), "全局 seq 应恰为 1..N"

    def test_highWaterEmptyStoreIsZero(self, store):
        assert store.highWater() == 0

    def test_appendRejectsEmptyStreamId(self, store):
        with pytest.raises(SwarmEventStoreError):
            store.append("", "spawned", {})


# ── event_id 幂等 ──


class TestIdempotentAppend:
    def test_duplicateEventIdReturnsExistingSeqAndKeepsFirstWrite(self, store):
        first = store.append("s1", "spawned", {"task": "第一版"}, event_id="evt-fix-1")
        # 同 event_id 再次写入：返回既有 seq，不产生新行，首次写入内容不被覆盖
        second = store.append("s1", "terminal", {"task": "重放不该覆盖"}, event_id="evt-fix-1")
        assert second == first
        events = store.readStream("s1")
        assert len(events) == 1, "重复 event_id 不得产生第二行"
        assert events[0]["payload"] == {"task": "第一版"}
        assert events[0]["type"] == "spawned"
        assert store.highWater() == first

    def test_emptyEventIdAppendsEveryTime(self, store):
        s1 = store.append("s1", "member_chunk", {"n": 1})
        s2 = store.append("s1", "member_chunk", {"n": 2})
        assert s2 == s1 + 1, "event_id 为空时不做幂等去重，每次都追加新行"


# ── readStream 分页 ──


class TestReadStream:
    def test_readStreamPaginatesByAfterSeqWithoutDupOrGap(self, store):
        for i in range(5):
            store.append("s1", "member_chunk", {"i": i})
        page1 = store.readStream("s1", after_seq=0, limit=2)
        page2 = store.readStream("s1", after_seq=page1[-1]["seq"], limit=2)
        page3 = store.readStream("s1", after_seq=page2[-1]["seq"], limit=2)
        allSeqs = [e["seq"] for e in page1 + page2 + page3]
        assert allSeqs == [1, 2, 3, 4, 5], f"分页应不重不漏，实际 {allSeqs}"
        assert [e["payload"]["i"] for e in page1 + page2 + page3] == [0, 1, 2, 3, 4]

    def test_readStreamReturnsContractShape(self, store):
        store.append(
            "s1", "tool_call", {"tool": "search"},
            event_id="evt-shape-1", command_id="cmd-9",
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        event = store.readStream("s1")[0]
        # P1-7 起契约事件带 tenant_id 租户段（缺省空串）
        assert set(event.keys()) == {
            "seq", "stream_id", "event_id", "type", "payload",
            "command_id", "occurred_at", "tenant_id",
        }
        assert event["stream_id"] == "s1"
        assert event["event_id"] == "evt-shape-1"
        assert event["type"] == "tool_call"
        assert event["payload"] == {"tool": "search"}
        assert event["command_id"] == "cmd-9"
        assert event["occurred_at"] == "2026-01-01T00:00:00+00:00"
        assert event["tenant_id"] == ""

    def test_readStreamFiltersByStream(self, store):
        store.append("s1", "spawned", {})
        store.append("s2", "spawned", {})
        store.append("s1", "terminal", {})
        s1Events = store.readStream("s1")
        assert [e["type"] for e in s1Events] == ["spawned", "terminal"]
        assert all(e["stream_id"] == "s1" for e in s1Events)
        assert len(store.readStream("never-existed")) == 0


# ── replayThrough 重放协议 ──


class TestReplayThrough:
    def test_replayNormalSegment(self, store):
        for i in range(5):
            store.append("s1", "member_chunk", {"i": i})
        result = store.replayThrough(2)
        assert result["degraded"] is False
        assert result["high_water"] == 5
        assert [e["seq"] for e in result["events"]] == [3, 4, 5]

    def test_replayIdleWhenCaughtUp(self, store):
        for i in range(3):
            store.append("s1", "member_chunk", {"i": i})
        for cursor in (3, 99):
            result = store.replayThrough(cursor)
            assert result["events"] == [], "after_seq >= high_water 应无回放"
            assert result["degraded"] is False
            assert result["high_water"] == 3

    def test_replayDegradedByEventCountKeepsContiguousPrefix(self, store):
        for i in range(10):
            store.append("s1", "member_chunk", {"i": i})
        result = store.replayThrough(0, max_events=4)
        assert result["degraded"] is True, "超事件数预算必须降级"
        assert result["high_water"] == 10
        seqs = [e["seq"] for e in result["events"]]
        assert seqs == [1, 2, 3, 4], f"降级必须是从 after_seq+1 起的连续前缀，实际 {seqs}"

    def test_replayDegradedByBytesKeepsContiguousPrefix(self, store):
        for i in range(6):
            store.append("s1", "member_chunk", {"blob": "x" * 200, "i": i})
        events = store.readStream("s1")
        sizes = [_encodedBytes(e) for e in events]
        # 预算卡在前 3 条之内：前 3 条能放下，第 4 条放不下
        budget = sum(sizes[:3]) + (sizes[3] // 2)
        result = store.replayThrough(0, max_bytes=budget)
        assert result["degraded"] is True, "超字节预算必须降级"
        seqs = [e["seq"] for e in result["events"]]
        assert seqs == [1, 2, 3], f"字节降级也应返回连续前缀，实际 {seqs}"
        assert sum(_encodedBytes(e) for e in result["events"]) <= budget

    def test_replaySingleOversizeEventDegradesWithEmptyPrefix(self, store):
        store.append("s1", "member_chunk", {"blob": "y" * 500})
        events = store.readStream("s1")
        budget = _encodedBytes(events[0]) - 1
        result = store.replayThrough(0, max_bytes=budget)
        assert result["degraded"] is True
        assert result["events"] == [], "单条即超预算：空前缀 + 降级信号，绝不部分回放"

    def test_replayWithinBudgetNotDegraded(self, store):
        for i in range(3):
            store.append("s1", "member_chunk", {"i": i})
        result = store.replayThrough(
            0,
            max_events=DEFAULT_REPLAY_MAX_EVENTS,
            max_bytes=DEFAULT_REPLAY_MAX_BYTES,
        )
        assert result["degraded"] is False
        assert [e["seq"] for e in result["events"]] == [1, 2, 3]

    def test_replayStreamFiltered(self, store):
        store.append("s1", "spawned", {})
        store.append("s2", "spawned", {})
        store.append("s1", "member_chunk", {})
        store.append("s2", "member_chunk", {})
        store.append("s1", "terminal", {})
        result = store.replayThrough(0, stream_id="s1")
        assert result["degraded"] is False
        assert result["high_water"] == 5
        assert [e["seq"] for e in result["events"]] == [1, 3, 5]
        assert all(e["stream_id"] == "s1" for e in result["events"])

    def test_replayBelowPrunedBoundaryDegradesToSnapshot(self, store):
        """cursor 落在 pruned-through 之下：区间可能有已删空洞，必须降级快照。"""
        for i in range(5):
            store.append("s1", "member_chunk", {"i": i})
        store.markPrunedThrough(3)
        stale = store.replayThrough(2)
        assert stale["degraded"] is True, "过旧 cursor 不得部分回放"
        assert stale["events"] == []
        assert stale["high_water"] == 5
        # cursor 恰在边界上：边界之后的事件齐全，正常增量回放
        fresh = store.replayThrough(3)
        assert fresh["degraded"] is False
        assert [e["seq"] for e in fresh["events"]] == [4, 5]


# ── snapshotStream 快照 ──


class TestSnapshotStream:
    def test_snapshotReturnsFullStreamWithGlobalSequence(self, store):
        store.append("s1", "spawned", {"n": 1})
        store.append("s2", "spawned", {"n": 2})
        store.append("s1", "terminal", {"n": 3})
        snapshot = store.snapshotStream("s1")
        assert snapshot["snapshot_sequence"] == store.highWater() == 3
        assert [e["seq"] for e in snapshot["events"]] == [1, 3]
        assert [e["payload"]["n"] for e in snapshot["events"]] == [1, 3]
        assert all(e["stream_id"] == "s1" for e in snapshot["events"])

    def test_snapshotUnknownStreamIsEmptyWithGlobalSequence(self, store):
        store.append("s1", "spawned", {})
        snapshot = store.snapshotStream("ghost")
        assert snapshot["events"] == []
        assert snapshot["snapshot_sequence"] == 1


# ── pruneCovered 保留窗口清理 ──


class TestPruneCovered:
    def test_pruneDeletesOutsideWindowKeepsStreamHeadAndInsideWindow(self, store):
        nowTs = 2_000_000_000.0
        oldTs = nowTs - 10 * 24 * 3600.0  # 远在窗口外
        # s1: 旧、旧、新（新的是流头，也在窗口内）
        s1Old1 = store.append("s1", "member_chunk", {"n": 1}, occurred_at=_isoAt(oldTs))
        s1Old2 = store.append("s1", "member_chunk", {"n": 2}, occurred_at=_isoAt(oldTs + 60))
        s1New = store.append("s1", "member_chunk", {"n": 3}, occurred_at=_isoAt(nowTs - 10))
        # s2: 仅一条旧事件——它是本流最新一条，必须保留
        s2Old = store.append("s2", "member_chunk", {"n": 4}, occurred_at=_isoAt(oldTs))

        deleted = store.pruneCovered(keep_window_s=100.0, now_ts=nowTs)
        assert deleted == 2, "窗口外且非流头的 s1 旧事件应被删除（s2 独苗为流头受保护）"

        remaining = {e["seq"] for e in store.readStream("s1")} | {
            e["seq"] for e in store.readStream("s2")
        }
        assert remaining == {s1New, s2Old}, f"应只剩各流头，实际 {remaining}"
        assert s1Old1 not in remaining and s1Old2 not in remaining

    def test_prunePublishesBoundaryEqualToMaxDeletedSeq(self, store):
        nowTs = 2_000_000_000.0
        oldTs = nowTs - 10 * 24 * 3600.0
        keep1 = store.append("s1", "member_chunk", {"n": 1}, occurred_at=_isoAt(oldTs))
        keep2 = store.append("s1", "member_chunk", {"n": 2}, occurred_at=_isoAt(oldTs + 1))
        head = store.append("s1", "member_chunk", {"n": 3}, occurred_at=_isoAt(nowTs - 1))
        assert store.prunedThrough() == 0

        deleted = store.pruneCovered(keep_window_s=100.0, now_ts=nowTs)
        assert deleted == 2
        # 边界 = 本次将删的最大 seq，先发布再删：调用返回时已可读
        assert store.prunedThrough() == max(keep1, keep2), (
            "pruned_through 应先推进到本次删除的最大 seq"
        )
        assert head > store.prunedThrough(), "流头 seq 必须在边界之上"

    def test_pruneKeepsEverythingInsideWindow(self, store):
        nowTs = 2_000_000_000.0
        for i in range(4):
            store.append("s1", "member_chunk", {"i": i}, occurred_at=_isoAt(nowTs - 50 + i))
        assert store.pruneCovered(keep_window_s=100.0, now_ts=nowTs) == 0
        assert store.highWater() == 4
        assert store.prunedThrough() == 0, "没有删除就不得推进边界"

    def test_pruneNoopWhenNothingOutsideWindow(self, store):
        nowTs = 2_000_000_000.0
        store.append("s1", "member_chunk", {"i": 1}, occurred_at=_isoAt(nowTs - 10))
        store.append("s2", "member_chunk", {"i": 2}, occurred_at=_isoAt(nowTs - 5))
        assert store.pruneCovered(keep_window_s=100.0, now_ts=nowTs) == 0
        assert store.prunedThrough() == 0

    def test_markPrunedThroughIsMonotonic(self, store):
        store.markPrunedThrough(5)
        assert store.prunedThrough() == 5
        store.markPrunedThrough(3)  # 更小的边界不得回退
        assert store.prunedThrough() == 5
        store.markPrunedThrough(5)
        assert store.prunedThrough() == 5

    def test_defaultKeepWindowCoversOneDay(self):
        from neurova.agent.swarm_event_store import DEFAULT_KEEP_WINDOW_S

        assert DEFAULT_KEEP_WINDOW_S == 24 * 3600.0


# ── mirrorFromLedger（H-4 JSONL 账本双写）──


class TestMirrorFromLedger:
    @staticmethod
    def _ledgerRows() -> list:
        return [
            {
                "event_id": "evt_ledger_1",
                "type": "spawned",
                "subagent_id": "run-1",
                "causation_id": "",
                "payload": {"task": "调研"},
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "seq": 1,
            },
            {
                "event_id": "evt_ledger_2",
                "type": "member_chunk",
                "subagent_id": "run-1",
                "causation_id": "evt_ledger_1",
                "payload": {"text": "进展"},
                "occurred_at": "2026-01-01T00:00:01+00:00",
                "seq": 2,
            },
            {
                "event_id": "evt_ledger_3",
                "type": "terminal",
                "subagent_id": "run-2",
                "causation_id": "",
                "payload": {"status": "completed"},
                "occurred_at": "2026-01-01T00:00:02+00:00",
                "seq": 1,
            },
        ]

    def test_mirrorWritesBySubagentStreamAndCountsNew(self, store):
        written = mirrorFromLedger(store, self._ledgerRows())
        assert written == 3
        assert store.highWater() == 3
        run1 = store.readStream("run-1")
        assert [e["event_id"] for e in run1] == ["evt_ledger_1", "evt_ledger_2"]
        assert [e["type"] for e in run1] == ["spawned", "member_chunk"]
        assert run1[0]["payload"] == {"task": "调研"}
        assert run1[0]["occurred_at"] == "2026-01-01T00:00:00+00:00"
        assert [e["event_id"] for e in store.readStream("run-2")] == ["evt_ledger_3"]

    def test_mirrorIsIdempotentOnRepeat(self, store):
        rows = self._ledgerRows()
        assert mirrorFromLedger(store, rows) == 3
        # 重复镜像（重启续传场景）：不重写、不产生新 seq
        assert mirrorFromLedger(store, rows) == 0
        assert store.highWater() == 3
        total = sum(len(store.readStream(s)) for s in ("run-1", "run-2"))
        assert total == 3

    def test_mirrorSkipsRowsWithoutEventId(self, store):
        rows = self._ledgerRows()
        rows.append({
            "type": "member_chunk",
            "subagent_id": "run-1",
            "payload": {"text": "缺 event_id"},
            "occurred_at": "2026-01-01T00:00:03+00:00",
            "seq": 3,
        })
        rows.append({"event_id": "", "type": "member_chunk", "subagent_id": "run-1",
                     "payload": {}, "occurred_at": "2026-01-01T00:00:04+00:00", "seq": 4})
        written = mirrorFromLedger(store, rows)
        assert written == 3, "缺 event_id 的行跳过且不计入返回值"
        assert store.highWater() == 3


# ── schema 登记 / 幂等重开 / 防降级 ──


class TestSchemaRegistration:
    def test_schemaRegisteredUnderDedicatedDomain(self, store):
        assert EVENT_STORE_DB_DOMAIN == "swarm_event_store"
        assert EVENT_STORE_DB_DOMAIN in registered_domains()
        # P1-7 起迁移链含租户段迁移（v2），断言取下限不写死具体版本号
        assert latest_version(EVENT_STORE_DB_DOMAIN) >= 2

    def test_reopenSameDbIsIdempotentAndKeepsData(self, tmp_path):
        dbPath = str(tmp_path / "reopen.db")
        store1 = SwarmEventStore(dbPath)
        seq = store1.append("s1", "spawned", {"n": 1})
        store1.close()

        store2 = SwarmEventStore(dbPath)
        try:
            assert store2.highWater() == seq
            assert store2.readStream("s1")[0]["payload"] == {"n": 1}
            conn = sqlite3.connect(dbPath)
            try:
                # user_version 跟随登记表最新版（P1-7 起为含租户段的 v2+）
                assert schema_version(conn) == latest_version(EVENT_STORE_DB_DOMAIN)
            finally:
                conn.close()
        finally:
            store2.close()

    def test_downgradedDatabaseIsRejected(self, tmp_path):
        dbPath = str(tmp_path / "downgrade.db")
        conn = sqlite3.connect(dbPath)
        conn.execute("PRAGMA user_version = 99")
        conn.commit()
        conn.close()
        with pytest.raises(SchemaVersionError):
            SwarmEventStore(dbPath)


# ── M5：镜像库周期清理（保留窗 env 可调）+ 生产 prune 函数 ─────────────────


class TestPruneWiring:
    def test_env_keep_window_seconds(self, monkeypatch):
        import math

        from neurova.agent.swarm_event_store import (
            DEFAULT_KEEP_WINDOW_S,
            envKeepWindowSeconds,
        )

        monkeypatch.setenv("NEUROVA_SWARM_EVENT_KEEP_WINDOW_S", "3600")
        assert envKeepWindowSeconds() == 3600.0
        monkeypatch.setenv("NEUROVA_SWARM_EVENT_KEEP_WINDOW_S", "0")
        assert envKeepWindowSeconds() == math.inf, "0 = 不清理（无限保留）"
        monkeypatch.setenv("NEUROVA_SWARM_EVENT_KEEP_WINDOW_S", "bogus")
        assert envKeepWindowSeconds() == DEFAULT_KEEP_WINDOW_S
        monkeypatch.delenv("NEUROVA_SWARM_EVENT_KEEP_WINDOW_S", raising=False)
        assert envKeepWindowSeconds() == DEFAULT_KEEP_WINDOW_S

    def test_prune_once_removes_expired_keeps_stream_head(self, tmp_path, monkeypatch):
        from datetime import datetime, timedelta, timezone

        from neurova.agent import swarm as swarm_mod
        from neurova.agent.swarm_event_store import SwarmEventStore

        store = SwarmEventStore(str(tmp_path / "evt_prune.db"))
        oldIso = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        store.append("s1", "spawned", {"n": 1}, occurred_at=oldIso)
        store.append("s1", "terminal", {"n": 2})  # 新鲜事件（流头保护）
        monkeypatch.setattr(swarm_mod, "_EVENT_STORE", store)
        monkeypatch.setenv("NEUROVA_SWARM_EVENT_KEEP_WINDOW_S", "3600")

        removed = swarm_mod.pruneSwarmEventStoreOnce()

        assert removed == 1, "超窗非流头事件应被清理"
        remaining = store.readStream("s1")
        assert [e["type"] for e in remaining] == ["terminal"]

    def test_prune_job_registered(self):
        from unittest.mock import MagicMock

        from neurova.agent import swarm as swarm_mod

        sched = MagicMock()
        assert swarm_mod.registerSwarmEventPruneJob(sched) is True
        args, kwargs = sched.addSystemJob.call_args
        assert args[1] == "swarm_event_store_prune"
        assert args[2] == 3600
