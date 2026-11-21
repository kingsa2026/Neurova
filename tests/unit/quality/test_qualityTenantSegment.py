# -*- coding: utf-8 -*-
"""P1-7：会话质量事件账补租户段（详案 §10.4 / §6 P1-7）。

断言全部落在**真实 SQLite 行为**上（tmp_path 临时文件库 + 真连接，
无 MagicMock 充当数据库）：
- 两条写入路径（turn_outcome / human_takeover 事件）都带 tenant_id 落库；
- metrics()/查询面按租户可选过滤（None=全部、租户串=该租户、空串=仅无段行）；
- 旧库（无 tenant_id 列）打开时经版本化迁移自动补列，历史行 tenant_id
  为空串（无段信号如实可辨，不臆造归属）；
- tenantDistribution：按事件类型跨租户计数，只采信带租户段的信号。
"""
from __future__ import annotations

import sqlite3

from neurova.core.db_migration import latest_version, registered_domains, schema_version
from neurova.quality.outcome_store import (
    QUALITY_DB_DOMAIN,
    ConversationQualityStore,
)

# 旧库形态（补租户段之前的 v1 表结构，不含 tenant_id 列）
_LEGACY_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversation_quality_events (
    event_id TEXT PRIMARY KEY,
    event_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    agent_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    source_event_id TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL DEFAULT '',
    reason_code TEXT NOT NULL DEFAULT '',
    occurred_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


def _rowTenant(dbPath: str, eventId: str) -> str:
    conn = sqlite3.connect(dbPath)
    try:
        row = conn.execute(
            "SELECT tenant_id FROM conversation_quality_events WHERE event_id = ?",
            (eventId,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None, f"事件 {eventId} 应存在"
    return str(row[0] or "")


def test_writePathsCarryTenantSegment(tmp_path):
    """turn_outcome 与人工接管事件两条写入路径都带 tenant_id；拿不到租户
    的入口如实落空串，不臆造 "default"。"""
    dbPath = str(tmp_path / "quality.db")
    store = ConversationQualityStore(dbPath)
    try:
        turn = store.recordTurnOutcome("t1", "s1", outcome="answered", tenantId="dept-a")
        takeover = store.recordEvent(
            "human_takeover_started", "s2",
            source="console_mark", sourceEventId="op-1",
            tenantId="dept-b",
        )
        noTenant = store.recordTurnOutcome("t3", "s3", outcome="unknown")
    finally:
        store.close()

    assert _rowTenant(dbPath, turn["event_id"]) == "dept-a"
    assert _rowTenant(dbPath, takeover["event_id"]) == "dept-b"
    assert _rowTenant(dbPath, noTenant["event_id"]) == ""


def test_metricsFiltersByTenant(tmp_path):
    """metrics 按租户可选过滤：不传=全部（既有行为不变）；传租户=该租户；
    传空串=仅无段行。"""
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        store.recordTurnOutcome("t1", "s1", outcome="answered", tenantId="dept-a")
        store.recordTurnOutcome("t2", "s2", outcome="tool_failure", tenantId="dept-a")
        store.recordTurnOutcome("t3", "s3", outcome="answered", tenantId="dept-b")
        store.recordTurnOutcome("t4", "s4", outcome="unknown")

        allMetrics = store.metrics()
        deptA = store.metrics(tenantId="dept-a")
        unsegmented = store.metrics(tenantId="")
        explicitAll = store.metrics(tenantId=None)
    finally:
        store.close()

    assert allMetrics["turns"] == 4
    assert explicitAll["turns"] == 4
    assert deptA["turns"] == 2
    assert deptA["outcomes"] == {"answered": 1, "tool_failure": 1}
    assert unsegmented["turns"] == 1
    assert unsegmented["outcomes"] == {"unknown": 1}


def test_legacyDbWithoutTenantColumnAutoMigrates(tmp_path):
    """旧库（无 tenant_id 列）打开时自动迁移补列：历史行如实读作空串段，
    新写入带租户，分布读数不把无段行冒充成任何租户。"""
    dbPath = str(tmp_path / "legacy.db")
    conn = sqlite3.connect(dbPath)
    try:
        conn.executescript(_LEGACY_SCHEMA)
        conn.execute(
            "INSERT INTO conversation_quality_events"
            " (event_id, event_type, session_id, agent_id, channel, source,"
            " source_event_id, actor_id, reason_code, occurred_at, recorded_at,"
            " metadata_json) VALUES"
            " ('cqe_legacy','turn_outcome','s0','','','chat_pipeline','t0','',"
            " 'answered','2026-11-20T00:00:00+00:00','2026-11-20T00:00:00+00:00','{}')"
        )
        conn.commit()
    finally:
        conn.close()

    store = ConversationQualityStore(dbPath)
    try:
        assert _rowTenant(dbPath, "cqe_legacy") == ""
        turn = store.recordTurnOutcome("t1", "s1", outcome="answered", tenantId="dept-a")
        assert _rowTenant(dbPath, turn["event_id"]) == "dept-a"

        dist = store.tenantDistribution("turn_outcome")
        assert dist["distribution"] == {"dept-a": 1}
        assert dist["unsegmented"] == 1
    finally:
        store.close()


def test_tenantDistributionCountsSegmentedOnly(tmp_path):
    """tenantDistribution：按事件类型跨租户计数；只采信带段信号进
    distribution，无段行单列 unsegmented；窗口外事件不计入。"""
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        store.recordTurnOutcome("t1", "s1", outcome="answered", tenantId="dept-a")
        store.recordTurnOutcome("t2", "s2", outcome="tool_failure", tenantId="dept-a")
        store.recordTurnOutcome("t3", "s3", outcome="answered", tenantId="dept-b")
        store.recordTurnOutcome("t4", "s4", outcome="unknown")
        store.recordTurnOutcome(
            "t-old", "s-old", outcome="answered", tenantId="dept-z",
            occurredAt="2026-01-01T00:00:00+00:00",
        )
        store.recordEvent(
            "human_takeover_started", "s5",
            source="console_mark", sourceEventId="op-1", tenantId="dept-a",
        )

        dist = store.tenantDistribution("turn_outcome")
        takeoverDist = store.tenantDistribution("human_takeover_started")
    finally:
        store.close()

    assert dist["event_type"] == "turn_outcome"
    assert dist["distribution"] == {"dept-a": 2, "dept-b": 1}
    assert dist["distinct_tenants"] == 2
    assert dist["segmented"] == 3
    assert dist["unsegmented"] == 1
    assert dist["total"] == 4
    assert "dept-z" not in dist["distribution"], "窗口外事件不计入"
    assert takeoverDist["distribution"] == {"dept-a": 1}


def test_tenantDistributionRejectsUnknownEventType(tmp_path):
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    try:
        import pytest

        with pytest.raises(ValueError):
            store.tenantDistribution("not-a-type")
    finally:
        store.close()


def test_schemaVersionRegisteredAndAdvanced(tmp_path):
    """质量库接入 db_migration 版本域：迁移链推进到含租户段的版本，
    新库 user_version 与登记表一致。"""
    assert QUALITY_DB_DOMAIN in registered_domains()
    assert latest_version(QUALITY_DB_DOMAIN) >= 2

    dbPath = str(tmp_path / "versioned.db")
    store = ConversationQualityStore(dbPath)
    try:
        conn = sqlite3.connect(dbPath)
        try:
            assert schema_version(conn) == latest_version(QUALITY_DB_DOMAIN)
        finally:
            conn.close()
    finally:
        store.close()


def test_postChatPipelinePassesTenantFromMetadata(tmp_path, monkeypatch):
    """调用方接线：post_chat 管线把请求边界注入 metadata 的 tenant_id
    传进质量事件账（HTTP 端点在 chat.py 注入，本测只验管线段）。"""
    import asyncio
    from unittest.mock import MagicMock

    from neurova.post_chat_pipeline import PostChatPipeline

    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    monkeypatch.setattr("neurova.quality.get_quality_store", lambda: store)
    agent = MagicMock()
    agent._save_to_session = MagicMock(return_value="sess-1")
    agent._collect_tool_messages = MagicMock(return_value=[])
    pipeline = PostChatPipeline(agent)

    asyncio.run(pipeline._step_save_session(
        user_input="q", reply="a", session_id="sess-1", save_memory=True,
        metadata={"finish_reason": "stop", "retrieval_hits": 2,
                  "retrieval_quality": 0.8, "tenant_id": "dept-a"},
    ))
    # metadata 未带租户的入口（如部分控制台路径）如实落空串
    asyncio.run(pipeline._step_save_session(
        user_input="q2", reply="a2", session_id="sess-2", save_memory=True,
        metadata={"finish_reason": "stop", "retrieval_hits": 2,
                  "retrieval_quality": 0.8},
    ))

    dist = store.tenantDistribution("turn_outcome")
    store.close()
    assert dist["distribution"] == {"dept-a": 1}
    assert dist["unsegmented"] == 1
