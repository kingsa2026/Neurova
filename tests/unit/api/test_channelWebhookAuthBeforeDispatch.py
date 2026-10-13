# -*- coding: utf-8 -*-
"""渠道 webhook 分派链：验签必须先于投递（§6-181 批 24 · 安全）。

漏洞实状（活体取证到手，非推测）：`api/endpoints/channels.py` 的入站分派链
（`handle_webhook:174`，路由挂在 `/api/v1/channel-adapters/{channel_type}/webhook`，
见 `endpoints/__init__.py:241` + `:345`）里，飞书那支 `_handle_feishu_webhook` 与钉钉那支
`_handle_dingtalk_webhook` **不做任何验签/令牌校验**，把请求体直接拼成 `ChannelMessage`
后 `await adapter._emit_event(MESSAGE_RECEIVED, ...)` 投进 manager，而 `sender_id` 取自请求体
（飞书 `:232`、钉钉 `:259`）。`tests/manual/channelVoiceFactorySeam_live.py` 的 `[OBSERVE]` 段实测：
无签名、无 token 的伪造事件 ⇒ **HTTP 200、事件 1 条、`sender_id='ou_FORGED_by_attacker'`、
`content='冒充'`**。默认绑定还是 `0.0.0.0`（`start_server.py:69`、`app.py:1337`），不是回环。

危害：任何人能对**已配置**的飞书/钉钉渠道冒充任意平台用户驱动 agent 回合——正好绕过
§6-123/§6-163 立起来的那套"发送者即身份"（身份解析读的就是这个 `sender_id`）：可以他人身份
读写其绑定 agent 的技能私库与记忆、把消息投进别人的会话、按伪造用户计 LLM 额度。
wecom 那支是例外，它委托 `adapter.handle_callback`，而 `wecom.py:181-186` 已 fail-closed——
说明这洞不是设计取舍，是"逐平台加分支时各写各的"漏出来的。

修法（一处口径：验签在适配器里，分派链只委托；投递前必须过）：
- **钉钉**：按平台"接收消息"协议校验 header 的 `timestamp` + `sign`
  （HMAC-SHA256、key=appSecret、串=`timestamp + "\\n" + appSecret`、Base64；偏差 >1h 视为非法）。
- **飞书**：challenge 必须走适配器已有的 `verify_url_challenge`（端点此前**自己 echo**，绕过了仓里
  已有的 C-23 那道门）；事件回调比对 payload 里的 verification token（v2 在 `header.token`、
  v1 在顶层 `token`），未配置 token 一律拒（与 wecom/telegram 口径一致，恒定时间比较）。
  密文回调（body 只有 `encrypt` 字段）本批**不解密、直接拒并点名原因**——不静默放行。

一处如实边界（别把判据当平台互操作证明）：本档的"签名正确"样本是用**同一套文档公式**在测试里
算出来的，它证的是"机制生效且算错的代价是拒绝"，**不证与本仓拿不到的真平台逐字节一致**。
选这个失败方向是有意的：公式若与平台实际不符，后果是合法回调被拒（渠道不响应，看得见、可诊断），
而不是伪造被放行。真凭据下的双向自证待有账号的那一批做。
"""

import base64
import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.channels.base import ChannelConfig
from neurova.channels.dingtalk import DingTalkAdapter
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.manager import ChannelManager, get_channel_manager

WEBHOOK = "/api/v1/channel-adapters/{}/webhook"
APP_SECRET = "dt-client-secret-live"
VERIFY_TOKEN = "fs-verification-token"


def _dingtalkSign(timestamp: str, appSecret: str) -> str:
    """平台文档公式：Base64(HmacSHA256(key=appSecret, msg=timestamp + "\\n" + appSecret))。"""
    digest = hmac.new(appSecret.encode("utf-8"),
                      f"{timestamp}\n{appSecret}".encode("utf-8"),
                      hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")


def _tsNowMs(offsetMs: int = 0) -> str:
    return str(int(time.time() * 1000) + offsetMs)


def _eventBody(senderId: str = "ou_victim", content: str = "帮我删掉所有笔记") -> dict:
    return {
        "senderId": senderId,
        "conversationId": "cid-1",
        "conversationType": "1",
        "msgId": "m-forged",
        "msgtype": "text",
        "text": {"content": content},
    }


@pytest.fixture()
def clientWith(tmp_path, monkeypatch):
    """真 app + 真分派链；事件回调换成 recorder（不起 agent、不调模型、不开外网）。"""
    ChannelManager._instance = None
    events: list = []

    async def _record(_eventType, message):
        events.append(message)

    dt = DingTalkAdapter(ChannelConfig(channel_type="dingtalk", app_id="dtkey",
                                       app_secret=APP_SECRET, use_stream=False))
    fs = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli_live",
                                     app_secret="sec_live", verification_token=VERIFY_TOKEN))
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as c:
        mgr = get_channel_manager()
        for adapter in (dt, fs):
            mgr.register_adapter(adapter)
            adapter._event_callback = _record
        yield c, events
    ChannelManager._instance = None


class TestDingTalkMustVerifyBeforeDispatch:
    def testUnsignedRequestIsRejectedAndNeverEmits(self, clientWith):
        client, events = clientWith
        r = client.post(WEBHOOK.format("dingtalk"), json=_eventBody())

        assert r.status_code in (401, 403), f"未验签的伪造请求被放行：{r.status_code} {r.text[:120]}"
        assert not events, f"被拒的同时还投了事件（{len(events)} 条）——那才是真危害"

    def testCorrectlySignedRequestStillReachesTheAdapter(self, clientWith):
        """反向对照：不能把门一关了之——合法回调必须仍然进得来。"""
        client, events = clientWith
        ts = _tsNowMs()
        r = client.post(WEBHOOK.format("dingtalk"), json=_eventBody(),
                        headers={"timestamp": ts, "sign": _dingtalkSign(ts, APP_SECRET)})

        assert r.status_code == 200, f"合法签名被拒：{r.status_code} {r.text[:160]}"
        assert len(events) == 1 and events[0].sender_id == "ou_victim"

    def testSignatureFromWrongSecretIsRejected(self, clientWith):
        client, events = clientWith
        ts = _tsNowMs()
        r = client.post(WEBHOOK.format("dingtalk"), json=_eventBody(),
                        headers={"timestamp": ts, "sign": _dingtalkSign(ts, "not-the-secret")})

        assert r.status_code in (401, 403) and not events, f"错密钥的签名被接受：{r.status_code}"

    def testStaleTimestampIsRejected(self, clientWith):
        """平台口径：与系统时间差 1 小时以上即非法——否则抓到的请求可无限重放。"""
        client, events = clientWith
        ts = _tsNowMs(offsetMs=-2 * 60 * 60 * 1000)
        r = client.post(WEBHOOK.format("dingtalk"), json=_eventBody(),
                        headers={"timestamp": ts, "sign": _dingtalkSign(ts, APP_SECRET)})

        assert r.status_code in (401, 403) and not events, f"过期时间戳被接受：{r.status_code}"

    def testMissingSecretFailsClosed(self, tmp_path, monkeypatch):
        """没配 appSecret 时不得"没有密钥就跳过校验"。"""
        ChannelManager._instance = None
        seen: list = []

        async def _record(_t, m):
            seen.append(m)

        dt = DingTalkAdapter(ChannelConfig(channel_type="dingtalk", app_id="k", app_secret=""))
        with TestClient(create_app(), raise_server_exceptions=False) as c:
            get_channel_manager().register_adapter(dt)
            dt._event_callback = _record
            ts = _tsNowMs()
            r = c.post(WEBHOOK.format("dingtalk"), json=_eventBody(),
                       headers={"timestamp": ts, "sign": _dingtalkSign(ts, "")})
        ChannelManager._instance = None

        assert r.status_code in (401, 403) and not seen, (
            "未配置密钥时放行了（空密钥还会让任何自算签名都匹配——比不验签更糟）")
        assert seen == []

    def testMalformedTimestampIsRejected(self, clientWith):
        """timestamp 不是数字时不能"解析失败就算通过"，也不能抛 500 当成拒绝。"""
        client, events = clientWith
        r = client.post(WEBHOOK.format("dingtalk"), json=_eventBody(),
                        headers={"timestamp": "tomorrow", "sign": _dingtalkSign("tomorrow", APP_SECRET)})

        assert r.status_code in (400, 401, 403) and not events, f"坏时间戳被接受：{r.status_code}"


class TestFeishuMustUseTheExistingGate:
    def testChallengeIsNotEchoedWithoutToken(self, clientWith):
        """端点此前自己 `return {"challenge": ...}`，绕过了 `verify_url_challenge` 里那道 C-23 门。"""
        client, _events = clientWith
        r = client.post(WEBHOOK.format("feishu"),
                        json={"type": "url_verification", "challenge": "c-1", "token": "wrong"})

        assert r.status_code in (401, 403), f"错 token 的挑战仍被 echo：{r.status_code} {r.text[:120]}"

    def testChallengeWithRightTokenStillWorks(self, clientWith):
        client, _events = clientWith
        r = client.post(WEBHOOK.format("feishu"),
                        json={"type": "url_verification", "challenge": "c-1", "token": VERIFY_TOKEN})

        assert r.status_code == 200 and r.json().get("challenge") == "c-1", r.text[:160]

    @pytest.mark.parametrize("envelope", ("v1", "v2"))
    def testEventWithoutValidTokenIsRejected(self, clientWith, envelope):
        """两代事件信封都要核 token：v2 在 `header.token`，v1 在顶层 `token`。"""
        client, events = clientWith
        payload = {"event": {"sender": {"sender_id": {"user_id": "ou_victim"}},
                             "message": {"message_id": "om_1", "chat_id": "oc_1",
                                         "message_type": "text", "content": "{\"text\":\"冒充\"}"}}}
        if envelope == "v2":
            payload.update({"schema": "2.0", "header": {"token": "wrong", "event_type": "im.message.receive_v1"}})
        else:
            payload.update({"type": "event_callback", "token": "wrong"})

        r = client.post(WEBHOOK.format("feishu"), json=payload)
        assert r.status_code in (401, 403), f"{envelope} 信封错 token 被放行：{r.status_code}"
        assert not events

    def testEventWithValidTokenIsDispatched(self, clientWith):
        client, events = clientWith
        r = client.post(WEBHOOK.format("feishu"), json={
            "schema": "2.0", "header": {"token": VERIFY_TOKEN, "event_type": "im.message.receive_v1"},
            "event": {"sender": {"sender_id": {"user_id": "ou_real"}},
                      "message": {"message_id": "om_2", "chat_id": "oc_2",
                                  "message_type": "text", "content": "{\"text\":\"正常\"}"}}})

        assert r.status_code == 200, r.text[:160]
        assert len(events) == 1 and events[0].sender_id == "ou_real", "合法回调没投出去"

    def testEncryptedEventIsRefusedNotSilentlyPassed(self, clientWith):
        """密文回调本批不解密：必须点名拒绝，不能"读不到 token 就当中性的过"。"""
        client, events = clientWith
        r = client.post(WEBHOOK.format("feishu"), json={"encrypt": "base64-gibberish"})

        assert r.status_code in (400, 401, 403), f"密文回调被当成明文放行：{r.status_code}"
        assert not events
        assert "encrypt" in r.text.lower(), f"拒绝原因没点名密文未实装：{r.text[:160]}"

    def testMissingVerificationTokenFailsClosed(self, clientWith):
        ChannelManager._instance = None
        seen: list = []

        async def _record(_t, m):
            seen.append(m)

        from neurova.channels.manager import get_channel_manager as getMgr

        bare = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli", app_secret="s"))
        with TestClient(create_app(), raise_server_exceptions=False) as c:
            getMgr().register_adapter(bare)
            bare._event_callback = _record
            r = c.post(WEBHOOK.format("feishu"), json={
                "schema": "2.0", "header": {"token": "", "event_type": "im.message.receive_v1"},
                "event": {"sender": {"sender_id": {"user_id": "x"}}, "message": {}}})
        ChannelManager._instance = None

        assert r.status_code in (401, 403) and not seen, "未配置 verification_token 时放行了"
