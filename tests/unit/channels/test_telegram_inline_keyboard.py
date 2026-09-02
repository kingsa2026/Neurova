# -*- coding: utf-8 -*-
"""telegram inline_keyboard 透传测试（补漏 Task 9 / 对比文档 P3-c）。

约定：发消息方把 Bot API 原生 reply_markup dict 放进
UnifiedMessage.metadata["reply_markup"]，sender mixin 在 payload
组装时透传——不扩 UnifiedMessage 字段（YAGNI）。
"""
from unittest.mock import MagicMock

from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage


def _msg(**meta):
    return UnifiedMessage(
        message_id="m1",
        channel=MessageChannel.TELEGRAM,
        content_type=ContentType.TEXT,
        content="hello",
        user_id="u1",
        chat_id="123",
        metadata=meta or None,
    )


def _adapter():
    from neurova.channels.telegram_sender import TelegramSenderMixin

    adapter = TelegramSenderMixin()
    adapter._ensure_initialized = MagicMock(return_value=True)
    adapter.show_typing = False
    adapter.bot_token = "TEST:TOKEN"
    captured = {}

    def fake_api(method, path, **kwargs):
        captured.update(kwargs.get("json") or {})
        return {"ok": True}

    adapter._api_request = fake_api
    return adapter, captured


def test_reply_markup_passthrough():
    adapter, captured = _adapter()
    markup = {"inline_keyboard": [[{"text": "点我", "callback_data": "cb:1"}]]}
    assert adapter.send_message(_msg(reply_markup=markup)) is True
    assert captured["reply_markup"] == markup


def test_no_markup_omits_field():
    adapter, captured = _adapter()
    assert adapter.send_message(_msg()) is True
    assert "reply_markup" not in captured
