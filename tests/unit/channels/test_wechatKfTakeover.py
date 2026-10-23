"""微信客服原生 session_status_change → 渠道接管事件。"""
from __future__ import annotations

import base64
import hashlib

from neurova.channels.base import ChannelEventType
from neurova.channels.wechat import WeChatAdapter
from neurova.channels.wechat_kf_crypto import (
    decryptKfPayload,
    encryptKfPayload,
    verifyKfSignature,
)

KEY = base64.b64encode(b"0123456789abcdef0123456789abcdef").decode()


def _signature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    return hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypt])).encode("utf-8")
    ).hexdigest()


def _kfAdapter() -> WeChatAdapter:
    adapter = WeChatAdapter()
    adapter.kf_mode = True
    adapter.humanTakeoverEvents = True
    adapter.callback_token = "callback-token"
    adapter.encoding_aes_key = KEY
    adapter.corpid = "corp-1"
    adapter.open_kfid = "kf-1"
    return adapter


def test_capabilityFollowsKfMode(monkeypatch):
    adapter = WeChatAdapter()
    monkeypatch.setattr(adapter, "_refresh_wecom_token", lambda: True)
    assert adapter.authenticate({
        "mode": "wecom", "corpid": "c", "corpsecret": "s",
        "kf_mode": "true", "open_kfid": "kf-1",
    }) is True
    assert adapter.humanTakeoverEvents is True

    plain = WeChatAdapter()
    monkeypatch.setattr(plain, "_refresh_wecom_token", lambda: True)
    assert plain.authenticate({
        "mode": "wecom", "corpid": "c", "corpsecret": "s",
    }) is True
    assert plain.humanTakeoverEvents is False


def test_crypto_roundtrip_and_signature():
    cipher = encryptKfPayload(KEY, "<xml>ok</xml>", receiveId="corp-1")
    assert decryptKfPayload(KEY, cipher, "corp-1") == "<xml>ok</xml>"
    signature = _signature("tok", "1700000000", "n", cipher)
    verifyKfSignature("tok", "1700000000", "n", cipher, signature)
    try:
        verifyKfSignature("tok", "1700000000", "n", cipher, "bad")
    except ValueError:
        pass
    else:
        raise AssertionError("错误签名必须拒绝")


def test_sessionStatusChangeMapsToTakeoverAndText():
    adapter = _kfAdapter()
    payload = {
        "msg_list": [
            {
                "msgid": "m1", "msgtype": "event", "external_userid": "user-1",
                "event": {
                    "event_type": "session_status_change", "change_type": 1,
                    "new_servicer_userid": "op-1",
                },
            },
            {
                "msgid": "m2", "msgtype": "event", "external_userid": "user-1",
                "event": {
                    "event_type": "session_status_change", "change_type": 2,
                    "old_servicer_userid": "op-1", "new_servicer_userid": "op-2",
                },
            },
            {
                "msgid": "m3", "msgtype": "event", "external_userid": "user-1",
                "event": {
                    "event_type": "session_status_change", "change_type": 3,
                    "old_servicer_userid": "op-2",
                },
            },
            {
                "msgid": "m4", "msgtype": "text", "external_userid": "user-1",
                "text": {"content": "你好"},
            },
        ]
    }

    events = adapter._kfPayloadToEvents(payload, "kf-1")

    kinds = [event_type for event_type, _ in events]
    assert kinds == [
        ChannelEventType.HUMAN_TAKEOVER_STARTED,
        ChannelEventType.HUMAN_TAKEOVER_ENDED,
        ChannelEventType.HUMAN_TAKEOVER_STARTED,
        ChannelEventType.HUMAN_TAKEOVER_ENDED,
        ChannelEventType.MESSAGE_RECEIVED,
    ]
    assert events[0][1].sender_id == "op-1"
    assert events[1][1].sender_id == "op-1"
    assert events[2][1].sender_id == "op-2"
    assert events[3][1].sender_id == "op-2"
    assert events[4][1].content == "你好"
    assert len({message.message_id for _, message in events[:4]}) == 4
    assert events[0][1].metadata["takeover_reason"] == "kf_session_status_change_1"


def test_handleKfCallback_decryptsAndDispatches(monkeypatch):
    adapter = _kfAdapter()
    inner = (
        "<xml><Event>kf_msg_or_event</Event><Token>sync-token</Token>"
        "<OpenKfId>kf-1</OpenKfId></xml>"
    )
    encrypt = encryptKfPayload(KEY, inner, receiveId="corp-1")
    xml = f"<xml><Encrypt>{encrypt}</Encrypt></xml>"
    timestamp, nonce = "1700000000", "nonce-1"
    signature = _signature("callback-token", timestamp, nonce, encrypt)
    payload = {
        "msg_list": [{
            "msgid": "m1", "msgtype": "event", "external_userid": "user-1",
            "event": {
                "event_type": "session_status_change", "change_type": 1,
                "new_servicer_userid": "op-1",
            },
        }]
    }
    monkeypatch.setattr(adapter, "sync_kf_messages", lambda token, kfid: payload)

    events = adapter.handle_kf_callback(signature, timestamp, nonce, xml)

    assert len(events) == 1
    assert events[0][0] == ChannelEventType.HUMAN_TAKEOVER_STARTED
    assert events[0][1].chat_id == "user-1"


def test_urlVerificationReturnsDecryptedEcho():
    adapter = _kfAdapter()
    echo = encryptKfPayload(KEY, "hello-echo", receiveId="corp-1")
    signature = _signature("callback-token", "1700000000", "n", echo)

    assert adapter.verify_kf_url(signature, "1700000000", "n", echo) == "hello-echo"
