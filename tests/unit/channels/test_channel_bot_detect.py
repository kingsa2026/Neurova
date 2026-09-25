"""任务2-A：channel_router 从入站消息判定"发送者是否 bot/对端 agent"。

证据字段（各平台真实 API）：telegram raw_event.from.is_bot、discord raw_event.author.bot；
以及适配器已解析进 metadata 的 is_bot / sender_is_bot。缺省/异常一律 False（=人类，安全侧）。
"""
from __future__ import annotations

from neurova.channels.base import ChannelMessage
from neurova.channels.channel_router import _detect_sender_is_bot


def _msg(**kw):
    base = dict(channel_type="x", message_id="m", sender_id="s", sender_name="n", content="c")
    base.update(kw)
    return ChannelMessage(**base)


def test_explicit_metadata_is_bot():
    assert _detect_sender_is_bot(_msg(metadata={"is_bot": True})) is True
    assert _detect_sender_is_bot(_msg(metadata={"sender_is_bot": True})) is True


def test_telegram_raw_from_is_bot():
    m = _msg(channel_type="telegram", raw_event={"from": {"id": 1, "is_bot": True}})
    assert _detect_sender_is_bot(m) is True


def test_discord_raw_author_bot():
    m = _msg(channel_type="discord", raw_event={"author": {"id": "1", "bot": True}})
    assert _detect_sender_is_bot(m) is True


def test_human_defaults_false():
    assert _detect_sender_is_bot(_msg(raw_event={"from": {"id": 1}})) is False
    assert _detect_sender_is_bot(_msg(raw_event={"from": {"is_bot": False}})) is False


def test_malformed_is_safe_false():
    assert _detect_sender_is_bot(_msg(raw_event=None, metadata=None)) is False
    assert _detect_sender_is_bot(_msg(raw_event="not-a-dict")) is False
