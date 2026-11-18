"""对照批 B9：渠道入站队列优先级。

现网 `ChannelIngressQueue.claim` 严格按 id FIFO——审批/人工高优消息与
普通消息同队排队。本批：入站行加 priority 列（v2 迁移，存量库自动补列），
claim 按 `priority DESC, id ASC`；消息 metadata.priority 作为默认优先级
（渠道适配器侧发审批/人工消息时自带，无需改调用方）。

群聊拆批不再立项：会话键单源 `resolve_session_scope_id` 已按
share_session_in_group 裁决群共享/按发送者隔离（同参照系 ACL 拆批语义）。
"""

import sqlite3

import pytest

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_ingress_queue import ChannelIngressQueue


def _msg(message_id: str, content: str, priority: int = 0) -> ChannelMessage:
    return ChannelMessage(
        channel_type="echo",
        message_id=message_id,
        sender_id="u1",
        sender_name="u1",
        content=content,
        metadata={"priority": priority},
    )


def test_high_priority_claimed_first(tmp_path):
    q = ChannelIngressQueue(tmp_path / "ingress.db")
    q.enqueue(_msg("m-low", "low", priority=0))
    q.enqueue(_msg("m-high", "high", priority=10))
    q.enqueue(_msg("m-mid", "mid", priority=5))
    order = [q.claim().message.content for _ in range(3)]
    assert order == ["high", "mid", "low"], f"应按优先级出队，实际：{order}"


def test_metadata_priority_is_honored_without_explicit_arg(tmp_path):
    q = ChannelIngressQueue(tmp_path / "ingress.db")
    q.enqueue(_msg("m-plain", "plain"))               # 无 priority 元数据 → 0
    q.enqueue(_msg("m-priority", "priority", priority=7))
    first = q.claim()
    assert first.message.content == "priority"


def test_same_priority_keeps_fifo(tmp_path):
    q = ChannelIngressQueue(tmp_path / "ingress.db")
    for i in range(3):
        q.enqueue(_msg(f"m-{i}", f"c{i}", priority=3))
    order = [q.claim().message.content for _ in range(3)]
    assert order == ["c0", "c1", "c2"]


def test_priority_column_added_to_legacy_db(tmp_path):
    """存量库（v1 schema，无 priority 列）打开即自动补列，claim 不炸。"""
    db = tmp_path / "legacy.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE channel_ingress_events ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, channel_type TEXT NOT NULL,"
        " message_id TEXT NOT NULL, chat_id TEXT NOT NULL DEFAULT '',"
        " payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',"
        " attempt INTEGER NOT NULL DEFAULT 0, dedupe_key TEXT NOT NULL UNIQUE,"
        " last_error TEXT, claimed_by TEXT, claimed_at REAL,"
        " created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT INTO channel_ingress_events (channel_type, message_id, chat_id,"
        " payload, status, dedupe_key, created_at, updated_at)"
        " VALUES ('echo','legacy-1','','{"
        '"channel_type": "echo", "message_id": "legacy-1", "sender_id": "u1",'
        ' "sender_name": "u1", "content": "legacy", "message_type": "text"'
        " }','pending','echo:legacy-1','t','t')"
    )
    conn.commit()
    conn.close()

    q = ChannelIngressQueue(db)
    q.enqueue(_msg("m-high", "high", priority=9))
    first = q.claim()
    assert first.message.content == "high", "迁移后高优先应先出"
    second = q.claim()
    assert second.message.message_id == "legacy-1", "存量行按默认优先级续排"
