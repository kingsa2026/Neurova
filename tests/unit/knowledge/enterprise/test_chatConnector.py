# -*- coding: utf-8 -*-
"""批 C6：聊天信息源连接器（2026-11-07 裁定 §2.4-3：企微＋微信/小微）。

判据（立项方案 §3-C6）：
- chat.vendor ∈ (wecom/wechat)，闭集外构造拒绝（闭集单点在
  schema_mapping.VARIANT_CLOSED_SETS，适配器构造二次收口）；
- 行集六列（msg_id/chat_id/chat_type/sender/sent_at/text）与 applyMapping 同构，
  附件列 media_ref 可空透传（本批不主动触发媒体管线，触发面归属报告裁定项）；
- 数据源＝既有通道捕获面 channel_ingress_events（只读拉取），游标按自增 id 推进、
  token 风格沿用 connectors_file；
- 会话存档 SDK 未接入 → health 显式 degraded 点名，不静默冒充全量。
夹具＝按真实 schema 伪造捕获面行（不依赖真实通道凭据）。
"""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

from neurova.knowledge.enterprise.connectors_chat import ChatChannelAdapter
from neurova.knowledge.enterprise.registry import buildAdapter
from neurova.knowledge.enterprise.schema_mapping import MappingError

#: 六列（与描述符 columns 对齐）；media_ref 是附件透传列，随行但可空
SIX_COLUMNS = ("msg_id", "chat_id", "chat_type", "sender", "sent_at", "text")

# channel_ingress_events 真实表结构（照抄 channels/channel_ingress_queue._SCHEMA，
# 夹具自建自插——不 import 队列类，避免真实连接与迁移注册副作用）
_INGRESS_SCHEMA = """
CREATE TABLE IF NOT EXISTS channel_ingress_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_type TEXT NOT NULL,
    message_id TEXT NOT NULL,
    chat_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    dedupe_key TEXT NOT NULL UNIQUE,
    last_error TEXT,
    claimed_by TEXT,
    claimed_at REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _msg(**overrides):
    """一条捕获消息（字段与 channels/base.ChannelMessage 一致，payload 形状同 enqueue）。"""
    message = {
        "channel_type": "wecom",
        "message_id": "m1",
        "sender_id": "zhang",
        "sender_name": "张三",
        "content": "下午三点开会",
        "message_type": "text",
        "chat_id": "zhang",
        "chat_type": "p2p",
        "timestamp": "2026-11-07T10:00:00+00:00",
        "raw_event": {},
        "metadata": {},
    }
    message.update(overrides)
    return message


def _seed(tmp_path, messages, name="channel_ingress.db"):
    """伪造既有捕获面：按真实 schema 落行（channel_ingress_queue.enqueue 的 payload 同款）。"""
    db = tmp_path / name
    conn = sqlite3.connect(str(db))
    try:
        conn.execute(_INGRESS_SCHEMA)
        for m in messages:
            payload = {
                "channel_type": m["channel_type"], "message_id": m["message_id"],
                "sender_id": m["sender_id"], "sender_name": m["sender_name"],
                "content": m["content"], "message_type": m["message_type"],
                "chat_id": m["chat_id"], "chat_type": m["chat_type"],
                "timestamp": m["timestamp"], "raw_event": m["raw_event"],
                "metadata": m["metadata"],
            }
            conn.execute(
                "INSERT INTO channel_ingress_events (channel_type, message_id, chat_id,"
                " payload, status, dedupe_key, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (m["channel_type"], m["message_id"], m["chat_id"],
                 json.dumps(payload, ensure_ascii=False), "done",
                 "%s:%s" % (m["channel_type"], m["message_id"]),
                 m["timestamp"], m["timestamp"]),
            )
        conn.commit()
    finally:
        conn.close()
    return db


def _descriptor(db_path, **overrides):
    descriptor = {
        "sourceId": "wecom_chat", "tenantId": "default", "sourceType": "chat",
        "vendor": "wecom", "ingressDb": str(db_path),
        "columns": list(SIX_COLUMNS),
        # 群聊 subject 语义＝群 id：模板由映射层拼（order:{msg_id} 同理），适配器只出行
        "subject": {"template": "chat:{chat_id}:msg:{msg_id}"},
        "predicate": {"termId": "says"},
        "object": {"column": "text", "kind": "column"},
        "qualifiers": {}, "enabled": True, "agentId": "default",
    }
    descriptor.update(overrides)
    return descriptor


class TestFactoryAndVendorClosedSet:
    def test_factoryBuildsChatAdapter(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        adapter = buildAdapter(_descriptor(db), "wecom_chat", "default")
        assert isinstance(adapter, ChatChannelAdapter), \
            "工厂位（registry.buildAdapter）应惰性接线 ChatChannelAdapter"

    def test_vendorOutsideClosedSetRejected(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        with pytest.raises(MappingError, match="vendor"):
            ChatChannelAdapter(_descriptor(db, vendor="slack"), "s", "default")
        with pytest.raises(MappingError, match="vendor"):
            ChatChannelAdapter(_descriptor(db, vendor=""), "s", "default")
        with pytest.raises(MappingError, match="vendor"):
            buildAdapter(_descriptor(db, vendor="telegram"), "s", "default")


class TestRowShape:
    def test_p2pRowSixColumns(self, tmp_path):
        db = _seed(tmp_path, [_msg(message_id="m1")])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        change = _run(adapter.fetchBatch(None, 50))
        assert change.hasMore is False
        assert len(change.rows) == 1
        row = change.rows[0]
        assert set(row) == set(SIX_COLUMNS) | {"media_ref"}, "行集＝六列＋附件透传列"
        assert row["msg_id"] == "m1"
        assert row["chat_id"] == "zhang", "私聊会话 id＝发送者（wecom 回调口径）"
        assert row["chat_type"] == "p2p"
        assert row["sender"] == "zhang"
        assert row["sent_at"] == "2026-11-07T10:00:00+00:00"
        assert row["text"] == "下午三点开会"
        assert row["media_ref"] == "", "纯文本消息无附件引用"

    def test_groupRowShape(self, tmp_path):
        db = _seed(tmp_path, [_msg(message_id="m9", chat_id="g100",
                                   chat_type="group", content="群里见")])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        change = _run(adapter.fetchBatch(None, 50))
        row = change.rows[0]
        assert row["chat_type"] == "group"
        assert row["chat_id"] == "g100", "群聊 subject 语义＝群 id（映射层模板拼）"
        assert row["sender"] == "zhang"
        assert row["text"] == "群里见"

    def test_describeSchemaColumnsAlign(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        schema = _run(adapter.describeSchema())
        assert schema.sourceType == "chat"
        assert schema.sourceId == "wecom_chat"
        columns = schema.tables[0]["columns"]
        assert columns[:6] == list(SIX_COLUMNS), "六列在前、与描述符 columns 对齐"
        assert columns[6] == "media_ref"
        assert "附件" in schema.tables[0].get("media_ref", ""), "附件能力在 schema 点名"

    def test_otherVendorRowsNotLeaked(self, tmp_path):
        db = _seed(tmp_path, [_msg(message_id="m1"),
                              _msg(message_id="m2", channel_type="feishu")])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        change = _run(adapter.fetchBatch(None, 50))
        assert [r["msg_id"] for r in change.rows] == ["m1"], "只读本 vendor 的捕获面"


class TestCursor:
    def test_paginationAndResume(self, tmp_path):
        db = _seed(tmp_path, [_msg(message_id="m%d" % i) for i in range(1, 6)])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        first = _run(adapter.fetchBatch(None, 2))
        assert [r["msg_id"] for r in first.rows] == ["m1", "m2"]
        assert first.hasMore is True
        second = _run(adapter.fetchBatch(first.nextCursor, 2))
        assert [r["msg_id"] for r in second.rows] == ["m3", "m4"]
        assert second.hasMore is True
        third = _run(adapter.fetchBatch(second.nextCursor, 2))
        assert [r["msg_id"] for r in third.rows] == ["m5"]
        assert third.hasMore is False
        fourth = _run(adapter.fetchBatch(third.nextCursor, 2))
        assert fourth.rows == []
        assert fourth.hasMore is False, "空批显式 hasMore=False，不用空列表冒充成功"
        assert fourth.nextCursor is None

    def test_newCaptureBeyondCursor(self, tmp_path):
        db = _seed(tmp_path, [_msg(message_id="m1"), _msg(message_id="m2")])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        first = _run(adapter.fetchBatch(None, 10))
        assert first.hasMore is False
        _seed(tmp_path, [_msg(message_id="m3", content="新捕获")])
        after = _run(adapter.fetchBatch(first.nextCursor, 10))
        assert [r["msg_id"] for r in after.rows] == ["m3"], "游标只向新捕获推进"
        assert after.rows[0]["text"] == "新捕获"

    def test_corruptPayloadSkippedWithoutStallingCursor(self, tmp_path):
        db = tmp_path / "channel_ingress.db"
        conn = sqlite3.connect(str(db))
        conn.execute(_INGRESS_SCHEMA)
        conn.execute(
            "INSERT INTO channel_ingress_events (channel_type, message_id, payload,"
            " dedupe_key, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            ("wecom", "bad1", "not-json{", "wecom:bad1", "t", "t"))
        conn.commit()
        conn.close()
        _seed(tmp_path, [_msg(message_id="m2"), _msg(message_id="m3")])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        change = _run(adapter.fetchBatch(None, 10))
        assert [r["msg_id"] for r in change.rows] == ["m2", "m3"], "坏 payload 行跳过不拖批"
        nxt = _run(adapter.fetchBatch(change.nextCursor, 10))
        assert nxt.rows == [], "游标推进过坏行（不卡水位、不重复消费）"


class TestMediaRef:
    def test_stagedMediaPathPassesThrough(self, tmp_path):
        staged = str(tmp_path / "staged-pic.png")
        db = _seed(tmp_path, [_msg(message_id="m1", message_type="image",
                                   metadata={"staged_media_path": staged,
                                             "file_name": "pic.png"})])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        row = _run(adapter.fetchBatch(None, 10)).rows[0]
        assert row["media_ref"] == staged, "附件引用如实透传（管线消费归属裁定项）"

    def test_pathKeyMediaRef(self, tmp_path):
        db = _seed(tmp_path, [_msg(message_id="m1", message_type="file",
                                   metadata={"file_path": "docs/spec.pdf",
                                             "file_name": "spec.pdf"})])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        row = _run(adapter.fetchBatch(None, 10)).rows[0]
        assert row["media_ref"] == "docs/spec.pdf"

    def test_healthNamesAttachmentCapability(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        health = _run(adapter.health())
        assert "media_ref" in health.reason, "附件能力在 health 点名"


class TestHealth:
    def test_wecomHistoryDegradedNamesArchiveSdk(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
        health = _run(adapter.health())
        assert health.status == "degraded", "会话存档未接入，不冒充全量可达"
        assert "会话存档" in health.reason
        assert "既有捕获面" in health.reason

    def test_wechatVendorDegradedNoHistoryChannel(self, tmp_path):
        db = _seed(tmp_path, [_msg(channel_type="wechat")], name="wechat.db")
        adapter = ChatChannelAdapter(
            _descriptor(db, vendor="wechat"), "wechat_chat", "default")
        health = _run(adapter.health())
        assert health.status == "degraded"
        assert "历史" in health.reason, "微信侧无官方历史通道也要点名"

    def test_missingCaptureDbHealthError(self, tmp_path):
        adapter = ChatChannelAdapter(
            _descriptor(tmp_path / "missing.db"), "ghost", "default")
        health = _run(adapter.health())
        assert health.status == "error"


class TestArchiveReadinessComesFromChannelLayer:
    """批 C7a（方案 §6.1/§11 第二行）：历史缺口读数改接通道层单点。

    企业源适配器仍零凭据——它只向通道层要一个 reason，自己不探测原生库、不碰私钥路径。
    夹具＝真 ChannelConfig＋真 WeComAdapter 注册进渠道管理器（生产装配点），用完摘除。
    """

    @staticmethod
    def _installWecom(extra):
        from neurova.channels.base import ChannelConfig
        from neurova.channels.manager import get_channel_manager
        from neurova.channels.wecom import WeComAdapter

        manager = get_channel_manager()
        manager.register_adapter(WeComAdapter(ChannelConfig(
            channel_type="wecom", enabled=True, app_id="ww_unit_corp",
            app_secret="unit-app-secret", extra=dict(extra),
        )), agent_id="default")
        return manager

    def test_healthReasonCarriesChannelLayerReadingVerbatim(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        ghost = tmp_path / "absent-archive-sdk.so"
        manager = self._installWecom({"corpid": "ww_unit_corp",
                                      "archiveSdkPath": str(ghost)})
        try:
            adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
            health = _run(adapter.health())
            assert str(ghost) in health.reason, (
                "历史缺口文案必须来自通道层同一读数——适配器自己不知道渠道配置里的库路径，"
                "reason 里出现它才证明真改接了单点；实得 %r" % health.reason)
            assert health.status == "error", "原生库路径在场但文件不存在＝配置错，须如实 error"
        finally:
            manager.unregister_adapter("wecom", agent_id="default")

    def test_unconfiguredArchiveStillDegradesAndNamesCaptureFace(self, tmp_path):
        db = _seed(tmp_path, [_msg()])
        manager = self._installWecom({"corpid": "ww_unit_corp"})
        try:
            adapter = ChatChannelAdapter(_descriptor(db), "wecom_chat", "default")
            health = _run(adapter.health())
            assert health.status == "degraded"
            assert "会话存档" in health.reason
            assert "既有捕获面" in health.reason
            assert "archiveSdkPath" in health.reason, "缺哪一项须点名去哪配，不笼统说「未接入」"
        finally:
            manager.unregister_adapter("wecom", agent_id="default")

    def test_wechatVendorNeverConsultsWecomArchiveFace(self, tmp_path):
        db = _seed(tmp_path, [_msg(channel_type="wechat")], name="wechat.db")
        manager = self._installWecom({"corpid": "ww_unit_corp",
                                      "archiveSdkPath": str(tmp_path / "absent.so")})
        try:
            adapter = ChatChannelAdapter(
                _descriptor(db, vendor="wechat"), "wechat_chat", "default")
            health = _run(adapter.health())
            assert health.status == "degraded", "微信侧不受企微存档配置错牵连"
            assert "历史" in health.reason
            assert "archiveSdkPath" not in health.reason
        finally:
            manager.unregister_adapter("wecom", agent_id="default")
