# -*- coding: utf-8 -*-
"""KNOW-12：聊天企业源按来源实例（agent）与租户精确过滤共享表。

捕获面与存档面都必须是 fail-closed：缺少 agentId、缺少边界列或行未归因时，
租户源不得退化为全表读取。存量未打戳行只能由显式迁移回填后消费。
"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timezone

import pytest

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue
from neurova.channels.wecom_archive import ArchiveProjectionStore
from neurova.knowledge.enterprise.connectors_chat import (
    MEDIA_REF_COLUMN,
    ROW_COLUMNS,
    ChatChannelAdapter,
)
from neurova.knowledge.enterprise.schema_mapping import MappingError, validateDescriptor


def _message(msgId: str, content: str = "正文") -> ChannelMessage:
    return ChannelMessage(
        channel_type="wecom", message_id=msgId, sender_id="sender-1",
        sender_name="发送者", content=content, chat_id="chat-1",
        timestamp=datetime.now(timezone.utc))


def _archiveRow(seq: int, msgId: str) -> dict:
    return {"seq": seq, "msgid": msgId, "publickey_ver": "", "action": "send",
            "msgtype": "text", "from_id": "u1", "tolist": "[]", "roomid": "",
            "msgtime_ms": 1700000000000, "text": "存档正文 %s" % msgId,
            "media_ref": ""}


def _mappingDescriptor(**overrides):
    descriptor = {
        "sourceType": "chat", "vendor": "wecom", "agentId": "agent-a",
        "columns": list(ROW_COLUMNS),
        "subject": {"column": "msg_id"},
        "predicate": {"termId": "says"},
        "object": {"kind": "column", "column": "sender"},
    }
    descriptor.update(overrides)
    return descriptor


class TestSourceDeclarationBoundary:
    def test_chatDescriptorRequiresAgentId(self):
        descriptor = _mappingDescriptor()
        descriptor.pop("agentId")
        with pytest.raises(MappingError, match="agentId"):
            validateDescriptor(descriptor, None, tenantId="tenant-a")

    def test_captureAndArchiveConstructorsRequireAgentId(self, tmp_path):
        with pytest.raises(MappingError, match="agentId"):
            ChatChannelAdapter(
                {"vendor": "wecom", "ingressDb": str(tmp_path / "ingress.db")},
                "src", "tenant-a")
        with pytest.raises(MappingError, match="agentId"):
            ChatChannelAdapter(
                {"vendor": "wecom", "chatSource": "archive",
                 "archiveDb": str(tmp_path / "archive.db")},
                "src", "tenant-a")


class TestCaptureFaceBoundary:
    def test_captureRowsFilteredByAgentAndTenant(self, tmp_path):
        db = tmp_path / "ingress.db"
        queue = ChannelIngressQueue(db_path=db)
        try:
            queue.enqueue(_message("m-a1"), agent_id="agent-a", tenant_id="tenant-a")
            queue.enqueue(_message("m-cross-tenant"), agent_id="agent-a",
                          tenant_id="tenant-b")
            queue.enqueue(_message("m-other-agent"), agent_id="agent-b",
                          tenant_id="tenant-a")
            queue.enqueue(_message("m-legacy"))
        finally:
            queue.close()

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "agentId": "agent-a", "ingressDb": str(db)},
            "src-a", "tenant-a")
        change = asyncio.run(adapter.fetchBatch(None, 10))
        assert {r["msg_id"] for r in change.rows} == {"m-a1"}, \
            "只读本 agent＋本 tenant；跨租户、他实例与未归因行均不得进入"

    def test_captureWithoutBoundaryColumnsRejected(self, tmp_path):
        db = tmp_path / "legacy-ingress.db"
        conn = sqlite3.connect(str(db))
        try:
            conn.execute(
                "CREATE TABLE channel_ingress_events ("
                "id INTEGER PRIMARY KEY, channel_type TEXT, payload TEXT)")
            conn.execute(
                "INSERT INTO channel_ingress_events VALUES (1, 'wecom', '{}')")
            conn.commit()
        finally:
            conn.close()

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "agentId": "agent-a", "ingressDb": str(db)},
            "src-a", "tenant-a")
        with pytest.raises(MappingError, match="边界列"):
            asyncio.run(adapter.fetchBatch(None, 10))


class TestArchiveFaceBoundary:
    def test_archiveRowsFilteredByAgentAndTenant(self, tmp_path):
        db = tmp_path / "archive.db"
        store = ArchiveProjectionStore(db)
        try:
            store.appendBatch([_archiveRow(1, "m-a1")], nextSeq=1,
                              agentId="agent-a", tenantId="tenant-a")
            store.appendBatch([_archiveRow(2, "m-cross-tenant")], nextSeq=2,
                              agentId="agent-a", tenantId="tenant-b")
            store.appendBatch([_archiveRow(3, "m-other-agent")], nextSeq=3,
                              agentId="agent-b", tenantId="tenant-a")
            store.appendBatch([_archiveRow(4, "m-legacy")], nextSeq=4,
                              agentId="", tenantId="")
        finally:
            store.close()

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "chatSource": "archive", "agentId": "agent-a",
             "archiveDb": str(db)}, "src-a", "tenant-a")
        change = asyncio.run(adapter.fetchBatch(None, 10))
        assert {r["msg_id"] for r in change.rows} == {"m-a1"}, \
            "存档源只读本 agent＋本 tenant；未归因存量行不得共享"

    def test_archiveStorePersistsBothBoundaryColumns(self, tmp_path):
        db = tmp_path / "archive.db"
        store = ArchiveProjectionStore(db)
        try:
            store.appendBatch([_archiveRow(1, "m-a1")], nextSeq=1,
                              agentId="agent-a", tenantId="tenant-a")
            row = store._conn.execute(
                "SELECT agent_id, tenant_id FROM channel_archive_messages"
                " WHERE msgid = 'm-a1'").fetchone()
            assert tuple(row) == ("agent-a", "tenant-a")
        finally:
            store.close()

    def test_archiveV3DatabaseMigratesTenantWithoutSharingLegacyRows(self, tmp_path):
        db = tmp_path / "archive-v3.db"
        store = ArchiveProjectionStore(db)
        try:
            store.appendBatch([_archiveRow(1, "m-legacy")], nextSeq=1,
                              agentId="agent-a", tenantId="")
            store._conn.execute("DROP INDEX idx_archive_source_seq")
            store._conn.execute(
                "ALTER TABLE channel_archive_messages DROP COLUMN tenant_id")
            store._conn.execute("PRAGMA user_version=3")
            store._conn.commit()
        finally:
            store.close()

        migrated = ArchiveProjectionStore(db)
        try:
            columns = {row[1] for row in migrated._conn.execute(
                "PRAGMA table_info(channel_archive_messages)").fetchall()}
            assert "tenant_id" in columns
            assert migrated._conn.execute("PRAGMA user_version").fetchone()[0] == 4
            assert migrated._conn.execute(
                "SELECT tenant_id FROM channel_archive_messages"
                " WHERE msgid = 'm-legacy'").fetchone()[0] == ""
        finally:
            migrated.close()

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "chatSource": "archive", "agentId": "agent-a",
             "archiveDb": str(db)}, "src-a", "tenant-a")
        assert asyncio.run(adapter.fetchBatch(None, 10)).rows == [], \
            "迁移后的未归因存量行仍不得进入租户源"
