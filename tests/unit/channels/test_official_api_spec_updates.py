"""
渠道官方接口规范对比更新测试（2026-08 审计）

对照各渠道官方最新文档修正的接口行为（TDD）:

1. 钉钉: Stream 机器人消息 topic 应为 `/v1.0/im/bot/messages/get`
   （官方 dingtalk-stream Python/Java/Node SDK 的 ChatbotMessage.TOPIC 一致）
2. 钉钉: sampleMarkdown 的 msgParam 应为 {"title","text"}，sampleText 为 {"content"}
   （官方 API 元数据示例 / alibabacloud-go/dingtalk robot_1_0）
3. 钉钉: 群聊消息官方接口 POST /v1.0/robot/groupMessages/send
4. QQ: 鉴权改用 POST https://bots.qq.com/app/getAppAccessToken，
   请求头 Authorization: QQBot {access_token}（Bot {appid}.{token} 已官方废弃）
5. QQ: v2 群聊/私聊消息接口 POST /v2/groups/{group_openid}/messages、
   POST /v2/users/{openid}/messages（2025-04-21 起主动推送下线，被动回复为主）
6. QQ: Webhook 验签改用 Ed25519（X-Signature-Ed25519 / X-Signature-Timestamp，
   Bot Secret 倍增截断 32 字节派生密钥对），并提供 op 13 回调地址验证应答
7. 企业微信: 回调签名公式 sha1(sort(token,timestamp,nonce,encrypt))（官方文档 90968）。
   注: SHA1 为平台强制互操作公式，非本实现的安全选择；
   测试使用按该公式离线预计算的签名常量做非循环验证
8. 微信公众号: access_token 改用官方推荐的 POST /cgi-bin/stable_token
9. Telegram: parse_mode 可配置，解析失败（400 can't parse entities）回退纯文本重发
"""

import json
import sys
import types

import pytest

from ecdsa import SigningKey
from ecdsa.curves import Ed25519

# 测试专用假值（非真实凭据）
_FAKE_QQ_TOKEN = "unittest-fake-qq-token"
_FAKE_OA_TOKEN = "unittest-fake-oa-token"
_FAKE_DT_TOKEN = "unittest-fake-dingtalk-token"


# ============================================================
# 钉钉规范
# ============================================================


class _FakeResponse:
    def __init__(self, payload=None, status=200):
        self._payload = payload
        self.status = status

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_aiohttp(monkeypatch, captured, payload=None, status=200):
    fake = types.ModuleType("aiohttp")

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class ClientSession:
        def post(self, url, json=None, headers=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return _FakeResponse(payload, status)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    fake.ClientTimeout = ClientTimeout
    fake.ClientSession = ClientSession
    monkeypatch.setitem(sys.modules, "aiohttp", fake)


def _make_dingtalk_adapter():
    from neurova.channels.dingtalk import DingTalkAdapter
    from neurova.channels.base import ChannelConfig

    adapter = DingTalkAdapter(
        ChannelConfig(channel_type="dingtalk", app_id="app123", app_secret="sec456", use_stream=True)
    )
    adapter._access_token = _FAKE_DT_TOKEN
    adapter._token_expires_at = float("inf")
    return adapter


class TestDingTalkStreamTopic:
    """钉钉 Stream 模式机器人消息 topic 必须为官方 /v1.0/im/bot/messages/get"""

    def test_topic_constant_matches_official(self):
        from neurova.channels.dingtalk import DingTalkAdapter

        assert DingTalkAdapter.STREAM_BOT_MESSAGE_TOPIC == "/v1.0/im/bot/messages/get"

    def test_connect_stream_registers_official_topic(self, monkeypatch):
        import asyncio
        import importlib

        registered = {}

        class FakeClient:
            def __init__(self, credential):
                pass

            def register_callback_listener(self, topic, handler):
                registered["topic"] = topic

            def start(self):
                pass

        fake = types.ModuleType("dingtalk_stream")

        class Credential:
            def __init__(self, app_id, secret):
                pass

        fake.Credential = Credential
        fake.DingtalkStreamClient = FakeClient
        monkeypatch.setitem(sys.modules, "dingtalk_stream", fake)

        # 重新加载模块，使模块级 `import dingtalk_stream` 绑定到假模块
        import neurova.channels.dingtalk as dingtalk_mod

        dingtalk_mod = importlib.reload(dingtalk_mod)

        from neurova.channels.base import ChannelConfig

        adapter = dingtalk_mod.DingTalkAdapter(
            ChannelConfig(channel_type="dingtalk", app_id="app123", app_secret="sec456", use_stream=True)
        )
        adapter._access_token = _FAKE_DT_TOKEN
        adapter._token_expires_at = float("inf")

        asyncio.run(adapter._connect_stream())

        assert registered["topic"] == "/v1.0/im/bot/messages/get", (
            "钉钉官方三语言 SDK 的机器人回调 topic 均为 /v1.0/im/bot/messages/get，"
            "注册其他 topic 将收不到任何机器人消息"
        )


class TestDingTalkMsgParam:
    """OpenAPI msgKey/msgParam 规范: sampleText→{"content"}, sampleMarkdown→{"title","text"}"""

    @pytest.mark.asyncio
    async def test_markdown_msg_param_official_format(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured, payload={"processQueryKey": "pqk0"})
        adapter = _make_dingtalk_adapter()

        result = await adapter._send_via_api("user123", "# 标题\n正文内容", "markdown")

        assert result is not None
        assert captured["url"] == "https://api.dingtalk.com/v1.0/robot/oToMessages/batchSend"
        assert captured["json"]["msgKey"] == "sampleMarkdown"
        msg_param = json.loads(captured["json"]["msgParam"])
        assert "title" in msg_param, "sampleMarkdown 的 msgParam 必须含 title（官方规范）"
        assert "text" in msg_param, "sampleMarkdown 的 msgParam 必须含 text（官方规范）"
        assert msg_param["text"] == "# 标题\n正文内容"

    @pytest.mark.asyncio
    async def test_text_msg_param_official_format(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured, payload={"processQueryKey": "pqk0"})
        adapter = _make_dingtalk_adapter()

        result = await adapter._send_via_api("user123", "hello", "text")

        assert result is not None
        assert captured["json"]["msgKey"] == "sampleText"
        msg_param = json.loads(captured["json"]["msgParam"])
        assert msg_param == {"content": "hello"}

    @pytest.mark.asyncio
    async def test_auth_header_official_name(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured, payload={"processQueryKey": "pqk0"})
        adapter = _make_dingtalk_adapter()

        await adapter._send_via_api("user123", "hello", "text")

        assert captured["headers"]["x-acs-dingtalk-access-token"] == _FAKE_DT_TOKEN


class TestDingTalkGroupMessage:
    """钉钉群聊消息官方接口 /v1.0/robot/groupMessages/send"""

    @pytest.mark.asyncio
    async def test_send_group_message_uses_official_api(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured, payload={"processQueryKey": "pqk1"})
        adapter = _make_dingtalk_adapter()

        result = await adapter.send_group_message("cidXXXX==", "大家好", "text")

        assert result == "pqk1"
        assert captured["url"] == "https://api.dingtalk.com/v1.0/robot/groupMessages/send"
        assert captured["json"]["robotCode"] == "app123"
        assert captured["json"]["openConversationId"] == "cidXXXX=="
        assert captured["json"]["msgKey"] == "sampleText"
        assert json.loads(captured["json"]["msgParam"]) == {"content": "大家好"}

    @pytest.mark.asyncio
    async def test_send_group_message_markdown_param(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured, payload={"processQueryKey": "pqk2"})
        adapter = _make_dingtalk_adapter()

        await adapter.send_group_message("cidXXXX==", "# 公告\n内容", "markdown")

        assert captured["json"]["msgKey"] == "sampleMarkdown"
        msg_param = json.loads(captured["json"]["msgParam"])
        assert "title" in msg_param and "text" in msg_param


# ============================================================
# QQ 频道/群聊规范
# ============================================================


class _FakeQQResponse:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


def _make_qq_adapter():
    from neurova.channels.qq import QQAdapter

    adapter = QQAdapter()
    adapter.app_id = "123456"
    adapter.secret = "my_secret"
    adapter._initialized = True
    adapter.access_token = _FAKE_QQ_TOKEN
    adapter.token_expire_time = float("inf")
    return adapter


class TestQQAuthSpec:
    """QQ 开放平台鉴权: getAppAccessToken + QQBot 请求头（Bot {appid}.{token} 已废弃）"""

    def test_get_access_token_official_endpoint(self, monkeypatch):
        import neurova.channels.qq as qq_mod

        calls = {}

        def fake_post(url, json=None, timeout=None):
            calls["url"] = url
            calls["json"] = json
            return _FakeQQResponse({"access_token": _FAKE_QQ_TOKEN, "expires_in": 7200})

        monkeypatch.setattr(qq_mod.requests, "post", fake_post)
        adapter = _make_qq_adapter()

        assert adapter._fetch_access_token() is True
        assert calls["url"] == "https://bots.qq.com/app/getAppAccessToken"
        assert calls["json"] == {"appId": "123456", "clientSecret": "my_secret"}
        assert adapter.access_token == _FAKE_QQ_TOKEN

    def test_auth_header_uses_qqbot_scheme(self):
        from neurova.channels.qq import QQAdapter

        adapter = QQAdapter()
        adapter.app_id = "123456"
        adapter.access_token = _FAKE_QQ_TOKEN

        headers = adapter._auth_headers()

        assert headers["Authorization"] == f"QQBot {_FAKE_QQ_TOKEN}", (
            "官方已废弃 Bot {appid}.{token}，现行为 Authorization: QQBot {access_token}"
        )
        assert "User-Agent" in headers

    def test_gateway_verify_uses_qqbot_header(self, monkeypatch):
        import neurova.channels.qq as qq_mod

        captured = {}

        def fake_get(url, headers=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            return _FakeQQResponse({"url": "wss://api.sgroup.qq.com/websocket"}, status=200)

        monkeypatch.setattr(qq_mod.requests, "get", fake_get)
        adapter = _make_qq_adapter()

        assert adapter._verify_connection() is True
        assert captured["url"] == "https://api.sgroup.qq.com/gateway/bot"
        assert captured["headers"]["Authorization"] == f"QQBot {_FAKE_QQ_TOKEN}"


class TestQQV2MessageSpec:
    """QQ v2 群聊/私聊消息接口与频道消息发送"""

    def _msg(self, chat_type=None, **meta):
        from neurova.channels.models import ContentType, MessageChannel, UnifiedMessage

        metadata = dict(meta)
        if chat_type:
            metadata["chat_type"] = chat_type
        return UnifiedMessage(
            message_id="MSGID1",
            channel=MessageChannel.QQ,
            content_type=ContentType.TEXT,
            content="hello",
            user_id="u1",
            chat_id="TARGET123",
            metadata=metadata or None,
        )

    def _patch_send(self, monkeypatch, status=200):
        import neurova.channels.qq as qq_mod

        captured = {}

        def fake_post(url, headers=None, json=None, timeout=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return _FakeQQResponse({"id": "M1", "timestamp": "2026-08-29"}, status=status)

        monkeypatch.setattr(qq_mod.requests, "post", fake_post)
        return captured

    def test_group_message_uses_v2_groups_api(self, monkeypatch):
        captured = self._patch_send(monkeypatch)
        adapter = _make_qq_adapter()

        assert adapter.send_message(self._msg("group")) is True

        assert captured["url"] == "https://api.sgroup.qq.com/v2/groups/TARGET123/messages"
        assert captured["json"]["content"] == "hello"
        assert captured["json"]["msg_type"] == 0
        assert captured["json"]["msg_id"] == "MSGID1", "被动回复必须携带 msg_id"
        assert captured["headers"]["Authorization"] == f"QQBot {_FAKE_QQ_TOKEN}"

    def test_c2c_message_uses_v2_users_api(self, monkeypatch):
        captured = self._patch_send(monkeypatch)
        adapter = _make_qq_adapter()

        assert adapter.send_message(self._msg("c2c")) is True

        assert captured["url"] == "https://api.sgroup.qq.com/v2/users/TARGET123/messages"
        assert captured["json"]["msg_id"] == "MSGID1"

    def test_guild_message_uses_channel_api(self, monkeypatch):
        captured = self._patch_send(monkeypatch)
        adapter = _make_qq_adapter()

        assert adapter.send_message(self._msg()) is True

        assert captured["url"] == "https://api.sgroup.qq.com/channels/TARGET123/messages"

    @pytest.mark.parametrize("status", [200, 202, 204])
    def test_success_status_codes(self, monkeypatch, status):
        """官方 HTTP 约定: 200 成功、204 成功无包体、202 异步成功（如消息审核）"""
        self._patch_send(monkeypatch, status=status)
        adapter = _make_qq_adapter()

        assert adapter.send_message(self._msg()) is True

    def test_msg_seq_and_msg_type_override(self, monkeypatch):
        captured = self._patch_send(monkeypatch)
        adapter = _make_qq_adapter()

        adapter.send_message(self._msg("group", msg_seq=2, msg_type=2))

        assert captured["json"]["msg_seq"] == 2
        assert captured["json"]["msg_type"] == 2


class TestQQWebhookEd25519:
    """QQ Webhook 验签: Ed25519（官方 sign.md），密钥由 Bot Secret 派生"""

    SECRET = "naOC0ocQE3shWLAfffVLB1rhYPG7"
    BODY = '{"op":0,"d":{},"t":"GATEWAY_EVENT_NAME"}'
    TS = "1725442341"

    def _derived_key(self):
        # 官方派生规则: Secret 倍增至 >=32 字节后截取前 32 字节作为 Ed25519 seed
        seed = self.SECRET
        while len(seed) < 32:
            seed = seed * 2
        return SigningKey.from_string(seed[:32].encode("utf-8"), curve=Ed25519)

    def _headers(self, sig, ts=None):
        return {"X-Signature-Ed25519": sig, "X-Signature-Timestamp": ts or self.TS}

    def test_verify_valid_signature(self):
        from neurova.channels.qq import QQAdapter

        adapter = QQAdapter()
        adapter.secret = self.SECRET

        sk = self._derived_key()
        sig = sk.sign((self.TS + self.BODY).encode("utf-8")).hex()

        assert adapter.verify_webhook_signature(self._headers(sig), self.BODY) is True

    def test_verify_rejects_tampered_body(self):
        from neurova.channels.qq import QQAdapter

        adapter = QQAdapter()
        adapter.secret = self.SECRET

        sk = self._derived_key()
        sig = sk.sign((self.TS + self.BODY).encode("utf-8")).hex()

        assert adapter.verify_webhook_signature(self._headers(sig), self.BODY + "x") is False

    def test_verify_rejects_malformed_signature(self):
        from neurova.channels.qq import QQAdapter

        adapter = QQAdapter()
        adapter.secret = self.SECRET

        assert adapter.verify_webhook_signature(self._headers("zz-not-hex"), self.BODY) is False
        assert adapter.verify_webhook_signature(self._headers(""), self.BODY) is False

    def test_validation_response_op13(self):
        """op 13 回调地址验证: 用派生私钥对 event_ts + plain_token 签名应答"""
        from neurova.channels.qq import QQAdapter

        adapter = QQAdapter()
        adapter.secret = self.SECRET

        plain_token = "Arq0D5A61EgUu4OxUvOp"
        event_ts = "1725442341"
        resp = adapter.build_webhook_validation_response(plain_token, event_ts)

        assert resp["plain_token"] == plain_token
        vk = self._derived_key().get_verifying_key()
        assert vk.verify(bytes.fromhex(resp["signature"]), (event_ts + plain_token).encode("utf-8"))


# ============================================================
# 企业微信回调签名规范
# ============================================================

# 以下签名常量按企业微信官方公式（文档 90968）
#   msg_signature = SHA1(sort(token, timestamp, nonce, encrypt))
# 对固定输入离线预计算（SHA1 为平台强制互操作算法，非本实现的安全选择），
# 用于对被测实现做非循环验证:
#   输入1: token="callback_token", timestamp="1756400000", nonce="nonce1",
#          encrypt="RypEvHKD8QQKFhvQ6Qle3c795XQrM3klTQVh2knRGwEw="
_WECOM_SIG_ENCRYPTED = "e89fcb7904917c4845e355f2b84f8d43eddafa10"
#   输入2: 第 4 元为加密 echostr "ENCRYPTED_ECHOSTR_B64"（URL 验证场景）
_WECOM_SIG_ECHOSTR_OK = "cd6d84de5168deab4b3e0007b31be7312580b9bd"
#   输入3: 第 4 元为被篡改值 "TAMPERED"（用于拒绝路径）
_WECOM_SIG_ECHOSTR_BAD = "f468e26aca7748dc6ed307d6f77c219baa9e6a43"
#   输入4: 明文模式（无 Encrypt 字段，等价于第 4 元为空串）
_WECOM_SIG_PLAINTEXT = "2fd73c7161f72dd11a4dc7c323d95f9add1ec994"


def _make_wecom_adapter():
    from neurova.channels.base import ChannelConfig
    from neurova.channels.wecom import WeComAdapter

    config = ChannelConfig(channel_type="wecom", app_id="corp1", app_secret="sec1", use_stream=False)
    adapter = WeComAdapter(config)
    adapter._callback_token = "callback_token"
    return adapter


class TestWeComCallbackSignature:
    """官方公式: msg_signature = sha1(sort(token, timestamp, nonce, msg_encrypt))"""

    ENCRYPT = "RypEvHKD8QQKFhvQ6Qle3c795XQrM3klTQVh2knRGwEw="

    def _xml(self):
        return (
            "<xml><ToUserName><![CDATA[toUser]]></ToUserName>"
            "<FromUserName><![CDATA[fromUser]]></FromUserName>"
            "<CreateTime>1756400000</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[hi]]></Content>"
            f"<Encrypt><![CDATA[{self.ENCRYPT}]]></Encrypt>"
            "</xml>"
        )

    def test_callback_accepts_official_four_element_signature(self):
        adapter = _make_wecom_adapter()

        reply = adapter.handle_callback(_WECOM_SIG_ENCRYPTED, "1756400000", "nonce1", self._xml())

        assert reply is not None, "官方四元组签名（含 Encrypt）必须验签通过"

    def test_callback_rejects_bad_signature(self):
        adapter = _make_wecom_adapter()
        # 用不同 token 计算的签名（错误签名）
        wrong_sig = "0" * 40

        reply = adapter.handle_callback(wrong_sig, "1756400000", "nonce1", self._xml())

        assert reply is None, "签名不匹配必须拒绝回调"

    def test_verify_url_includes_encrypted_echostr(self):
        adapter = _make_wecom_adapter()
        echostr = "ENCRYPTED_ECHOSTR_B64"

        assert (
            adapter.verify_url(_WECOM_SIG_ECHOSTR_OK, "1756400000", "nonce1", echostr) == echostr
        )

        with pytest.raises(ValueError):
            adapter.verify_url(_WECOM_SIG_ECHOSTR_BAD, "1756400000", "nonce1", echostr)

    def test_callback_plaintext_mode_without_encrypt(self):
        """明文模式（无 Encrypt 字段）签名保持兼容"""
        adapter = _make_wecom_adapter()
        xml = (
            "<xml><ToUserName><![CDATA[toUser]]></ToUserName>"
            "<FromUserName><![CDATA[fromUser]]></FromUserName>"
            "<CreateTime>1756400000</CreateTime>"
            "<MsgType><![CDATA[text]]></MsgType>"
            "<Content><![CDATA[hi]]></Content>"
            "</xml>"
        )

        assert adapter.handle_callback(_WECOM_SIG_PLAINTEXT, "1756400000", "nonce1", xml) is not None


# ============================================================
# 微信公众号 stable_token 规范
# ============================================================


class TestWeChatOfficialStableToken:
    """官方推荐 POST /cgi-bin/stable_token（凭证与普通 token 接口隔离）"""

    def test_refresh_uses_stable_token_endpoint(self, monkeypatch):
        import neurova.channels.wechat_auth as auth_mod
        from neurova.channels.wechat import WeChatAdapter

        captured = {}

        def fake_post(url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeQQResponse({"access_token": _FAKE_OA_TOKEN, "expires_in": 7200})

        monkeypatch.setattr(auth_mod.requests, "post", fake_post)
        adapter = WeChatAdapter()
        adapter.official_appid = "wxappid"
        adapter.official_secret = "wxsecret"

        assert auth_mod.WeChatAuthMixin._refresh_official_token(adapter) is True

        assert captured["url"] == "https://api.weixin.qq.com/cgi-bin/stable_token"
        assert captured["json"]["grant_type"] == "client_credential"
        assert captured["json"]["appid"] == "wxappid"
        assert captured["json"]["secret"] == "wxsecret"
        assert captured["json"]["force_refresh"] is False
        assert adapter.official_access_token == _FAKE_OA_TOKEN


# ============================================================
# Telegram parse_mode 规范（Bot API 10.x）
# ============================================================


class TestTelegramParseMode:
    """legacy Markdown 仍受支持；parse_mode 可配置；解析失败回退纯文本重发"""

    def _adapter(self):
        from neurova.channels.telegram_adapter import TelegramAdapter

        adapter = TelegramAdapter()
        adapter.bot_token = "1:TOKEN"
        adapter._initialized = True
        return adapter

    def test_parse_error_falls_back_to_plain_text(self):
        calls = []

        def fake_api_request(method, path, **kwargs):
            # 快照拷贝: 实现的回退路径会原地修改 payload（pop parse_mode）
            calls.append(dict(kwargs.get("json") or {}))
            if len(calls) == 1 and "parse_mode" in calls[0]:
                return {"ok": False, "description": "Bad Request: can't parse entities"}
            return {"ok": True, "result": {"message_id": 1}}

        adapter = self._adapter()
        adapter._api_request = fake_api_request

        assert adapter._send_text_message("chat1", "hello *world_ [x") is True
        assert len(calls) == 2
        assert "parse_mode" in calls[0], "首次发送应携带配置的 parse_mode"
        assert "parse_mode" not in calls[1], "解析失败后必须以纯文本重发"

    def test_no_fallback_when_plain_send_also_fails(self):
        def fake_api_request(method, path, **kwargs):
            return {"ok": False, "description": "Bad Request: chat not found"}

        adapter = self._adapter()
        adapter._api_request = fake_api_request

        assert adapter._send_text_message("chat1", "hello") is False

    def test_parse_mode_configurable(self):
        adapter = self._adapter()

        captured = {}

        def fake_api_request(method, path, **kwargs):
            captured["json"] = kwargs.get("json", {})
            return {"ok": True}

        adapter._api_request = fake_api_request
        adapter.parse_mode = "HTML"
        adapter._send_text_message("chat1", "<b>hi</b>")

        assert captured["json"]["parse_mode"] == "HTML"

    def test_authenticate_reads_parse_mode(self):
        adapter = self._adapter()
        adapter._api_request = lambda *a, **k: {"ok": True}

        adapter.authenticate({"bot_token": "1:T", "parse_mode": "MarkdownV2"})

        assert adapter.parse_mode == "MarkdownV2"
