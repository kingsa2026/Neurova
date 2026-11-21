# -*- coding: utf-8 -*-
"""P1-7：全局事件库（SwarmEventStore）补租户段（详案 §10.4 / §6 P1-7）。

断言全部落在**真实 SQLite 行为**上（tmp_path 临时文件库 + 真连接，
无 MagicMock 充当数据库）：
- append 写入带 tenant_id，读取面（readStream/replayThrough/snapshotStream）
  事件带 tenant_id，缺省空串；
- 旧库（v1 表结构、user_version=1）打开时经版本化迁移自动补列，
  历史行 tenant_id 为空串，新写入带租户；
- tenantDistribution：按事件类型跨租户计数，只采信带租户段的信号；
- mirrorFromLedger 支持租户段透传（记录自带优先，参数兜底）。

库层支持为本卡交付范围；生产唯一写入方在 swarm.py（禁碰在途件），
调用方接线登记为待办。
"""
from __future__ import annotations

import sqlite3

from neurova.agent.swarm_event_store import (
    EVENT_STORE_DB_DOMAIN,
    SwarmEventStore,
    mirrorFromLedger,
)
from neurova.core.db_migration import latest_version, schema_version

# 旧库形态（补租户段之前的 v1 表结构，不含 tenant_id 列）
_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS swarm_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    stream_id TEXT NOT NULL,
    event_id TEXT NOT NULL DEFAULT '',
    type TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    command_id TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL DEFAULT '',
    occurred_ts REAL NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_swarm_events_event_id
    ON swarm_events(event_id) WHERE event_id <> '';
CREATE INDEX IF NOT EXISTS idx_swarm_events_stream_seq
    ON swarm_events(stream_id, seq);
CREATE TABLE IF NOT EXISTS store_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


def test_appendCarriesTenantSegment(tmp_path):
    dbPath = str(tmp_path / "swarm.db")
    store = SwarmEventStore(dbPath)
    try:
        store.append("stream-a", "member_chunk", {"i": 1}, tenant_id="dept-a")
        store.append("stream-a", "member_chunk", {"i": 2})
        events = store.readStream("stream-a")

        replay = store.replayThrough(0)
        snapshot = store.snapshotStream("stream-a")
    finally:
        store.close()

    assert events[0]["tenant_id"] == "dept-a"
    assert events[1]["tenant_id"] == "", "缺省写入如实落空串段"
    assert replay["events"][0]["tenant_id"] == "dept-a"
    assert snapshot["events"][0]["tenant_id"] == "dept-a"


def test_legacyDbWithoutTenantColumnAutoMigrates(tmp_path):
    """旧库（v1 schema、user_version=1）打开时自动补列：历史行读作空串段，
    新写入带租户，user_version 推进到登记表最新版。"""
    dbPath = str(tmp_path / "legacy_swarm.db")
    conn = sqlite3.connect(dbPath)
    try:
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO swarm_events (stream_id, event_id, type, payload_json,"
            " command_id, occurred_at, occurred_ts) VALUES"
            " ('stream-old','evt-old','member_chunk','{}','',"
            " '2026-11-20T00:00:00+00:00', 1763596800.0)"
        )
        conn.execute("PRAGMA user_version = 1")
        conn.commit()
    finally:
        conn.close()

    store = SwarmEventStore(dbPath)
    try:
        legacy = store.readStream("stream-old")
        assert legacy[0]["tenant_id"] == ""

        store.append("stream-new", "member_chunk", {"n": 1}, tenant_id="dept-a")
        assert store.readStream("stream-new")[0]["tenant_id"] == "dept-a"

        conn2 = sqlite3.connect(dbPath)
        try:
            assert schema_version(conn2) == latest_version(EVENT_STORE_DB_DOMAIN)
            assert latest_version(EVENT_STORE_DB_DOMAIN) >= 2
        finally:
            conn2.close()
    finally:
        store.close()


def test_tenantDistributionCountsSegmentedOnly(tmp_path):
    """跨租户计数只采信带段信号；无段行单列 unsegmented；可按事件类型
    过滤，也可全类型统计。"""
    store = SwarmEventStore(str(tmp_path / "swarm.db"))
    try:
        store.append("s1", "member_chunk", {}, tenant_id="dept-a")
        store.append("s2", "member_chunk", {}, tenant_id="dept-a")
        store.append("s3", "spawned", {}, tenant_id="dept-b")
        store.append("s4", "member_chunk", {})

        dist = store.tenantDistribution("member_chunk")
        allDist = store.tenantDistribution("")
    finally:
        store.close()

    assert dist["event_type"] == "member_chunk"
    assert dist["distribution"] == {"dept-a": 2}
    assert dist["distinct_tenants"] == 1
    assert dist["segmented"] == 2
    assert dist["unsegmented"] == 1
    assert dist["total"] == 3
    assert allDist["total"] == 4
    assert allDist["distribution"] == {"dept-a": 2, "dept-b": 1}


def test_tenantDistributionWindowExcludesOldEvents(tmp_path):
    store = SwarmEventStore(str(tmp_path / "swarm.db"))
    try:
        store.append("s1", "member_chunk", {}, tenant_id="dept-a",
                     occurred_at="2026-01-01T00:00:00+00:00")
        store.append("s2", "member_chunk", {}, tenant_id="dept-b")

        dist = store.tenantDistribution("member_chunk", windowSeconds=7 * 86400.0)
    finally:
        store.close()

    assert dist["distribution"] == {"dept-b": 1}
    assert dist["total"] == 1


def test_mirrorFromLedgerCarriesTenant(tmp_path):
    """镜像写入支持租户段：记录自带 tenant_id 优先，参数兜底。"""
    store = SwarmEventStore(str(tmp_path / "swarm.db"))
    try:
        written = mirrorFromLedger(store, [
            {"event_id": "e1", "subagent_id": "sub-1", "type": "member_chunk",
             "payload": {}, "occurred_at": "2026-11-21T00:00:00+00:00"},
            {"event_id": "e2", "subagent_id": "sub-1", "type": "member_chunk",
             "payload": {}, "occurred_at": "2026-11-21T00:00:01+00:00",
             "tenant_id": "dept-override"},
        ], tenant_id="dept-run")
        events = store.readStream("sub-1")
    finally:
        store.close()

    assert written == 2
    assert events[0]["tenant_id"] == "dept-run"
    assert events[1]["tenant_id"] == "dept-override"
