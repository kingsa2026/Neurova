# -*- coding: utf-8 -*-
"""KNOW-12：聊天企业源按来源实例（agent）精确过滤共享表。

审计定位（全仓逐文件审计报告 2026-11-25 §6 KNOW-12）：connectors_chat 查询共享
入站/存档表时不带 tenant、agent 或 channel 实例——某租户源可能复制其他租户消息。
判据：共享事件模型补 agent/tenant 边界列；声明了 agentId 的源只拉本实例的行；
未打戳的存量行保持既有行为（迁移容忍）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue
from neurova.channels.wecom_archive import ArchiveProjectionStore
from neurova.knowledge.enterprise.connectors_chat import ChatChannelAdapter


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


class TestArchiveFaceBoundary:
    def test_archiveRowsFilteredByAgent(self, tmp_path):
        """存档面：声明 agentId 的源只拉本实例的行（他实例消息不串）。"""
        db = tmp_path / "archive.db"
        store = ArchiveProjectionStore(db)
        store.appendBatch([_archiveRow(1, "m-a1")], nextSeq=1, agentId="agent-a")
        store.appendBatch([_archiveRow(2, "m-b1"), _archiveRow(3, "m-b2")],
                          nextSeq=3, agentId="agent-b")
        store.close()

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "chatSource": "archive", "agentId": "agent-a",
             "archiveDb": str(db)}, "src-a", "default")
        change = asyncio.run(adapter.fetchBatch(None, 10))
        msgIds = {r["msg_id"] for r in change.rows}
        assert msgIds == {"m-a1"}, "存档源只拉本 agent 的行（m-b1/m-b2 不出现）"

    def test_archiveRowsWithoutAgentDeclarationKeepLegacyBehavior(self, tmp_path):
        """描述符未声明 agentId：保持既有全量行为（存量配置不破）。"""
        db = tmp_path / "archive.db"
        store = ArchiveProjectionStore(db)
        store.appendBatch([_archiveRow(1, "m-a1")], nextSeq=1, agentId="agent-a")
        store.close()

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "chatSource": "archive", "archiveDb": str(db)},
            "src", "default")
        change = asyncio.run(adapter.fetchBatch(None, 10))
        assert {r["msg_id"] for r in change.rows} == {"m-a1"}


class TestCaptureFaceBoundary:
    def test_enqueueStampsAgentAndTenant(self, tmp_path):
        """共享入站事件模型带 agent/tenant 边界列（KNOW-12 前置）。"""
        queue = ChannelIngressQueue(db_path=tmp_path / "ingress.db")
        assert queue.enqueue(_message("m-1"), agent_id="agent-a",
                             tenant_id="t1") is True
        row = queue._conn.execute(
            "SELECT agent_id, tenant_id FROM channel_ingress_events"
            " WHERE message_id = 'm-1'").fetchone()
        assert tuple(row) == ("agent-a", "t1")

    def test_captureRowsFilteredByAgentOnceStamped(self, tmp_path):
        """捕获面：打了戳的行按 agent 圈域；未打戳的存量行保持可读（迁移容忍）。"""
        db = tmp_path / "ingress.db"
        queue = ChannelIngressQueue(db_path=db)
        queue.enqueue(_message("m-a1"), agent_id="agent-a", tenant_id="t1")
        queue.enqueue(_message("m-b1"), agent_id="agent-b", tenant_id="t2")
        queue.enqueue(_message("m-legacy"))  # 未打戳（存量写入方形态）

        adapter = ChatChannelAdapter(
            {"vendor": "wecom", "agentId": "agent-a", "ingressDb": str(db)},
            "src-a", "default")
        change = asyncio.run(adapter.fetchBatch(None, 10))
        msgIds = {r["msg_id"] for r in change.rows}
        assert "m-b1" not in msgIds, "他实例的捕获消息不得进入本源"
        assert "m-a1" in msgIds and "m-legacy" in msgIds, \
            "本实例行与未打戳存量行照常可读"
