# -*- coding: utf-8 -*-
"""企业微信自建应用回调面协议合规契约（审计 2026-11-07 判定的四项不符合＋缺口）。

红灯判据（对照官方《加解密方案说明》91144 /《发送应用消息》90236）：
- URL 验证：校验签名后**解密 echostr 并原样返回明文**（现实现返回密文原文）；
  未配 token/aes_key fail-closed（现无 token 放行）；
- 加密模式回调：body 只含 <Encrypt> → 解密后取真实消息字段并正常投递（现解析不到 Content）；
- 加密会话的被动回复 = 官方密文包装（Encrypt/MsgSignature/TimeStamp/Nonce），可解密回原文
  （现恒明文）；
- 明文模式（无 Encrypt）兼容保留：照常解析、明文回复（反向钉）；
- message/send 的 text 只有 content（mentioned_list 属群机器人 webhook 契约，应用消息不带）；
- token 失效（40014/42001）→ 刷新后重试一次；
- gettoken URL/提前失效/失效码收口 wecom_token 单源；WeComGroupBot 死代码退役。

测试向量用 `wechat_kf_crypto`（协议单源）的真实加解密构造，非 mock 业务对象。
"""
from __future__ import annotations

import asyncio
import base64
import importlib
import xml.etree.ElementTree as ET
from typing import TYPE_CHECKING

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.wechat_kf_crypto import (
    callbackSignature,
    decryptKfPayload,
    encryptKfPayload,
)

if TYPE_CHECKING:  # 类型注解面：运行期在函数内 import，注解里只作前向引用
    from neurova.channels.wecom import WeComAdapter

# 43 字符的合法 EncodingAESKey（base64 后恰为 32 字节）
AES_KEY = base64.b64encode(bytes(range(32))).decode()[:43]
CORP_ID = "ww_corp_unit"
TOKEN = "tok_unit"


def _adapter(*, token: str = TOKEN, aes_key: str = AES_KEY) -> "WeComAdapter":
    from neurova.channels.wecom import WeComAdapter

    return WeComAdapter(
        ChannelConfig(
            channel_type="wecom",
            app_id=CORP_ID,
            app_secret="sec_unit",
            webhook_token=token,
            extra={"encoding_aes_key": aes_key, "corpid": CORP_ID, "agentid": "1000002"},
        )
    )


def _innerMessageXml(content: str, msgId: str = "m_unit_1") -> str:
    """官方明文消息体形状（解密后的内层 XML）。"""
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{CORP_ID}]]></ToUserName>"
        "<FromUserName><![CDATA[u_sender]]></FromUserName>"
        "<CreateTime>1700000000</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        f"<MsgId>{msgId}</MsgId>"
        "</xml>"
    )


# ---------------------------------------------------------------------------
# URL 验证（官方：签名 → 解密 echostr → 原样返回明文）
# ---------------------------------------------------------------------------


class TestVerifyUrl:
    def test_returns_decrypted_plaintext(self):
        adapter = _adapter()
        echoPlain = "1428358092760283746echo-unit-plain"
        echostr = encryptKfPayload(AES_KEY, echoPlain, CORP_ID)
        sig = callbackSignature(TOKEN, "1700000000", "nonce1", echostr)
        result = adapter.verify_url(sig, "1700000000", "nonce1", echostr)
        assert result == echoPlain, "官方要求返回解密后的明文，不是密文原文"

    def test_rejects_bad_signature(self):
        adapter = _adapter()
        echostr = encryptKfPayload(AES_KEY, "plain", CORP_ID)
        with pytest.raises(ValueError):
            adapter.verify_url("badsig", "1700000000", "nonce1", echostr)

    def test_fail_closed_without_token(self):
        adapter = _adapter(token="")
        with pytest.raises(ValueError):
            adapter.verify_url("", "", "", "anything")

    def test_fail_closed_without_aes_key(self):
        adapter = _adapter(aes_key="")
        echostr = encryptKfPayload(AES_KEY, "plain", CORP_ID)
        sig = callbackSignature(TOKEN, "1700000000", "nonce1", echostr)
        with pytest.raises(ValueError):
            adapter.verify_url(sig, "1700000000", "nonce1", echostr)


# ---------------------------------------------------------------------------
# 加密回调：解密取真消息 + 密文回复；明文模式兼容（反向钉）
# ---------------------------------------------------------------------------


class TestEncryptedCallback:
    def _runCapture(self, adapter: "WeComAdapter", xml: str, sig: str, ts: str, nonce: str):
        captured: dict = {}

        async def cap(eventType, message):
            captured["message"] = message

        adapter._emit_event = cap

        async def scenario():
            loop = asyncio.get_running_loop()
            adapter._main_loop = loop
            reply = adapter.handle_callback(sig, ts, nonce, xml)
            for _ in range(80):
                if "message" in captured:
                    break
                await asyncio.sleep(0.01)
            return reply, captured.get("message")

        return asyncio.run(scenario())

    def test_encrypted_message_dispatches_real_content(self):
        adapter = _adapter()
        enc = encryptKfPayload(AES_KEY, _innerMessageXml("机密内容abc"), CORP_ID)
        outer = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>"
        sig = callbackSignature(TOKEN, "1700000000", "nonce9", enc)
        reply, message = self._runCapture(adapter, outer, sig, "1700000000", "nonce9")
        assert message is not None and message.content == "机密内容abc", (
            "加密回调必须解密后取到真实 Content（现实现解析不到）"
        )

    def test_reply_is_official_encrypted_wrapper(self):
        adapter = _adapter()
        enc = encryptKfPayload(AES_KEY, _innerMessageXml("hi"), CORP_ID)
        outer = f"<xml><Encrypt><![CDATA[{enc}]]></Encrypt></xml>"
        sig = callbackSignature(TOKEN, "1700000000", "nonce9", enc)
        reply, _ = self._runCapture(adapter, outer, sig, "1700000000", "nonce9")
        assert reply is not None
        assert "<Encrypt>" in reply and "<MsgSignature>" in reply and "<Nonce>" in reply, (
            "加密会话的被动回复必须是官方密文包装"
        )
        replyEnc = ET.fromstring(reply).findtext("Encrypt", "")
        inner = decryptKfPayload(AES_KEY, replyEnc, CORP_ID)
        assert "收到您的消息" in inner

    def test_plaintext_mode_still_parses_and_replies_plain(self):
        adapter = _adapter()
        xml = _innerMessageXml("plain-hello")
        sig = callbackSignature(TOKEN, "1700000000", "nonce8", "")  # 明文模式第 4 元为空串
        reply, message = self._runCapture(adapter, xml, sig, "1700000000", "nonce8")
        assert message is not None and message.content == "plain-hello"
        assert reply is not None and "<Encrypt>" not in reply


# ---------------------------------------------------------------------------
# 发送契约与 token 韧性
# ---------------------------------------------------------------------------


class TestSendContract:
    @pytest.mark.asyncio
    async def test_text_payload_is_official_shape(self, monkeypatch):
        adapter = _adapter()
        sent: dict = {}

        async def fakePost(url, payload):
            sent["url"] = url
            sent["payload"] = payload
            return {"errcode": 0, "msgid": 42}

        async def fakeGet(url):
            return {"errcode": 0, "access_token": "tok_live", "expires_in": 7200}

        monkeypatch.setattr(adapter, "_postJson", fakePost, raising=False)
        monkeypatch.setattr(adapter, "_getJson", fakeGet, raising=False)
        msgId = await adapter.send_message("u1", "hi", "text", chat_type="group", at_user_id="boss")
        assert msgId == "42"
        text = sent["payload"]["text"]
        assert text == {"content": "hi"}, (
            "应用消息 text 官方契约只有 content；mentioned_list 属群机器人 webhook"
        )

    @pytest.mark.asyncio
    async def test_retries_once_on_invalid_token(self, monkeypatch):
        adapter = _adapter()
        posts: list = []

        async def fakePost(url, payload):
            posts.append(url)
            if len(posts) == 1:
                return {"errcode": 40014, "errmsg": "invalid access_token"}
            return {"errcode": 0, "msgid": 7}

        async def fakeGet(url):
            return {"errcode": 0, "access_token": f"tok_refresh_{len(posts)}", "expires_in": 7200}

        monkeypatch.setattr(adapter, "_postJson", fakePost, raising=False)
        monkeypatch.setattr(adapter, "_getJson", fakeGet, raising=False)
        msgId = await adapter.send_message("u1", "hi", "text")
        assert msgId == "7", "token 失效（40014）应刷新后重试一次"
        assert len(posts) == 2
        # 首次取 token 时 posts 尚为空 → tok_refresh_0；失效刷新后 → tok_refresh_1
        assert "tok_refresh_0" in posts[0] and "tok_refresh_1" in posts[1]


# ---------------------------------------------------------------------------
# 单源收口与死代码退役
# ---------------------------------------------------------------------------


class TestSingleSourceAndRetirement:
    def test_group_bot_retired(self):
        mod = importlib.import_module("neurova.channels.wecom")
        assert not hasattr(mod, "WeComGroupBot"), "零调用方死代码按教义退役"

    def test_token_url_single_sourced(self):
        from neurova.channels import wecom_token

        assert wecom_token.WECOM_TOKEN_URL == "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        assert 40014 in wecom_token.INVALID_TOKEN_ERRCODES
        assert 42001 in wecom_token.INVALID_TOKEN_ERRCODES
        # 两个消费面都不再各自拼 gettoken URL（字面量只允许出现在单源里）
        for path in ("neurova/channels/wecom.py", "neurova/channels/wechat_auth.py"):
            with open(path, "r", encoding="utf-8") as f:
                src = f.read()
            assert "cgi-bin/gettoken" not in src, f"{path} 应消费 wecom_token 单源"

    def test_early_expiry_single_value(self):
        from neurova.channels import wecom_token

        assert wecom_token.TOKEN_EARLY_EXPIRY_SECONDS == 300
