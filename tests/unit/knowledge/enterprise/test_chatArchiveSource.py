# -*- coding: utf-8 -*-
"""批 C7b：存档投影面的只读消费契约（方案 §11 C7b 第三行 / §4 甲案）。

判据：
- **六列同体形状**：存档面与捕获面行集同一六列（ROW_COLUMNS＋media_ref），
  避免两套列名——消费方（applyMapping/页面）不感知来源差别；
- **`media_ref` 值形态点名是 `sdkfileid`**：与捕获面 `media_id` 不是同一种引用，
  describeSchema 必须写明（「有引用」不得被读成「既有媒体管线可达」，方案 §5/§10）；
- **游标 `since=` 承载 `seq`**：token 形状沿用 connectors_file 风格
  （`src=<vendor>:since=<seq>`），形状兼容、语义按面切换；
- **只认 action=send 入账**：recall/switch 留在投影（诚实存档），不出行集；
- **chatSource 闭集**：capture（缺省，存量行为不变）/ archive；越界即 MappingError；
  wechat 无存档面，chatSource=archive 构造期即拒；
- 健康读数：凭据面不就绪＝degraded（如实点名），不冒充 ok。

夹具＝真 ArchiveProjectionStore（生产 DDL 自建自插，tmp_path）；不建
channel_ingress.db——存档面适配器不得触碰捕获面落点。
"""

import asyncio
from pathlib import Path

import pytest

from neurova.channels import wecom_archive
from neurova.knowledge.enterprise.connectors_chat import (
    MEDIA_REF_COLUMN,
    ROW_COLUMNS,
    ChatChannelAdapter,
)
from neurova.knowledge.enterprise.schema_mapping import MappingError


def _row(seq, msgid, *, action="send", msgtype="text", fromId="userid_a",
         tolist='["userid_b"]', roomid="", msgtimeMs=1700000000000,
         text="", mediaRef=""):
    return {
        "seq": seq, "msgid": msgid, "publickey_ver": "v1", "action": action,
        "msgtype": msgtype, "from_id": fromId, "tolist": tolist, "roomid": roomid,
        "msgtime_ms": msgtimeMs, "text": text, "media_ref": mediaRef,
    }


@pytest.fixture()
def store(tmp_path: Path):
    store = wecom_archive.ArchiveProjectionStore(tmp_path / "archive.db")
    try:
        yield store
    finally:
        store.close()


def _archiveAdapter(dbPath, vendor="wecom", **extra):
    descriptor = {
        "sourceType": "chat", "vendor": vendor, "chatSource": "archive",
        "columns": list(ROW_COLUMNS) + [MEDIA_REF_COLUMN],
        "archiveDb": str(dbPath),
    }
    descriptor.update(extra)
    return ChatChannelAdapter(descriptor, "src_archive")


def test_six_column_shape_parity_with_capture_face(store):
    """存档面与捕获面同一六列行形状（同体判据，避免两套列名）。"""
    store.appendBatch([
        _row(1, "msg_1", roomid="wrRoom1", text="群里说"),
        _row(2, "msg_2", msgtype="image", mediaRef="sdkfileid_IMG_1"),
    ], nextSeq=2)
    adapter = _archiveAdapter(store.path)
    batch = asyncio.run(adapter.fetchBatch(None, 10))
    assert len(batch.rows) == 2
    expected = set(ROW_COLUMNS) | {MEDIA_REF_COLUMN}
    for row in batch.rows:
        assert set(row.keys()) == expected, (
            "存档面必须与捕获面同一六列＋media_ref（避免两套列名）")
    assert batch.rows[0]["msg_id"] == "msg_1"
    assert batch.rows[0]["chat_id"] == "wrRoom1"
    assert batch.rows[0]["chat_type"] == "group"
    assert batch.rows[0]["sender"] == "userid_a"
    assert batch.rows[0]["sent_at"] == "2023-11-14T22:13:20+00:00"
    assert batch.rows[0]["text"] == "群里说"
    assert batch.rows[0][MEDIA_REF_COLUMN] == ""
    assert batch.rows[1][MEDIA_REF_COLUMN] == "sdkfileid_IMG_1"


def test_media_ref_names_sdkfileid_shape(store):
    """media_ref 值形态＝sdkfileid，且 describeSchema 点名与捕获面 media_id 不同源。"""
    store.appendBatch([_row(2, "msg_2", msgtype="image", mediaRef="sdkfileid_IMG_1")],
                      nextSeq=2)
    adapter = _archiveAdapter(store.path)
    batch = asyncio.run(adapter.fetchBatch(None, 10))
    assert batch.rows[0][MEDIA_REF_COLUMN] == "sdkfileid_IMG_1"
    assert batch.rows[0]["text"] == ""
    schema = asyncio.run(adapter.describeSchema())
    table = schema.tables[0]
    assert "channel_archive_messages" in table["name"], (
        "存档面 schema 必须点名投影表来源")
    assert "sdkfileid" in str(table.get("media_ref")), (
        "存档面 media_ref 语义必须点名 sdkfileid 形态（与捕获面 media_id 不同源）")


def test_p2p_chat_id_is_stable_sorted_pair(store):
    """roomid 空＝p2p；chat_id 取双方排序对（同会话双向同键，不随消息方向漂）。"""
    store.appendBatch([
        _row(1, "m1", fromId="userid_a", tolist='["userid_b"]', text="a→b"),
        _row(2, "m2", fromId="userid_b", tolist='["userid_a"]', text="b→a"),
    ], nextSeq=2)
    adapter = _archiveAdapter(store.path)
    rows = asyncio.run(adapter.fetchBatch(None, 10)).rows
    assert rows[0]["chat_type"] == "p2p"
    assert rows[0]["chat_id"] == rows[1]["chat_id"] == "p2p:userid_a:userid_b"


def test_cursor_since_carries_seq(store):
    """游标 token 形状沿用 `src=<vendor>:since=<seq>`，第二批只取新 seq。"""
    store.appendBatch([
        _row(1, "m1", text="第一批"),
        _row(2, "m2", text="第一批"),
    ], nextSeq=2)
    adapter = _archiveAdapter(store.path)
    batch1 = asyncio.run(adapter.fetchBatch(None, 10))
    assert batch1.hasMore is False
    assert batch1.nextCursor is not None
    assert batch1.nextCursor.token == "src=wecom:since=2"
    store.appendBatch([_row(3, "m3", text="第二批")], nextSeq=3)
    batch2 = asyncio.run(adapter.fetchBatch(batch1.nextCursor, 10))
    assert [row["msg_id"] for row in batch2.rows] == ["m3"]
    assert batch2.nextCursor.token == "src=wecom:since=3"


def test_has_more_probe_and_limit(store):
    """limit+1 探测 hasMore（与捕获面同款），不整表捞。"""
    store.appendBatch([_row(i, "m%d" % i, text="x") for i in range(1, 6)], nextSeq=5)
    adapter = _archiveAdapter(store.path)
    batch = asyncio.run(adapter.fetchBatch(None, 4))
    assert len(batch.rows) == 4
    assert batch.hasMore is True
    assert batch.nextCursor.token == "src=wecom:since=4"


def test_only_send_action_enters_rows(store):
    """recall/switch 留在投影（诚实存档）但不出行集——归一入账只认 send。"""
    store.appendBatch([
        _row(1, "m1", text="正常消息"),
        _row(2, "m2", action="recall", text="被撤回的"),
        _row(3, "m3", action="switch"),
    ], nextSeq=3)
    adapter = _archiveAdapter(store.path)
    batch = asyncio.run(adapter.fetchBatch(None, 10))
    assert [row["msg_id"] for row in batch.rows] == ["m1"]
    assert batch.nextCursor.token == "src=wecom:since=3", (
        "游标越过 recall/switch 行（它们已如实留档，不需要重复消费）")


def test_missing_projection_db_reads_empty_not_crash(tmp_path):
    """投影库尚未落盘（worker 未拉过）→ 空批诚实返回，不炸、不冒充有数。"""
    adapter = _archiveAdapter(tmp_path / "not_yet.db")
    batch = asyncio.run(adapter.fetchBatch(None, 10))
    assert batch.rows == []
    assert batch.hasMore is False
    assert batch.nextCursor is None


def test_chat_source_closed_set(tmp_path):
    with pytest.raises(MappingError):
        _archiveAdapter(tmp_path / "x.db", chatSource="wat")
    with pytest.raises(MappingError):
        # 微信侧无会话存档面（§1 表），chatSource=archive 构造期即拒
        _archiveAdapter(tmp_path / "x.db", vendor="wechat")
    capture = ChatChannelAdapter(
        {"sourceType": "chat", "vendor": "wecom",
         "columns": list(ROW_COLUMNS) + [MEDIA_REF_COLUMN]},
        "src_capture")
    assert capture._sourceFace == "capture", "缺省＝capture（存量描述符行为不变）"


def test_archive_health_is_degraded_without_channel(tmp_path):
    """凭据面/装配面未就绪 → degraded 如实点名；报 ok 即冒充全量可达。"""
    adapter = _archiveAdapter(tmp_path / "archive.db")
    health = asyncio.run(adapter.health())
    assert health.status == "degraded"
    assert "存档" in health.reason or "会话存档" in health.reason
