# -*- coding: utf-8 -*-
"""N2（2026-11-17）——Telegram webhook 接收端点 + 管理三端点。

背景：`TelegramWebhookMixin`（set/delete/get_webhook_info + verify_webhook_signature）
全仓零调用，`/api/v1/channel-adapters/{channel_type}/webhook` 的分派链此前只认
飞书/钉钉/企微/微信客服——Telegram 的推送进不了本仓，管理面三方法也是死码。

本档钉住两类行为：

接收面（`POST .../telegram/webhook`，鉴权＝X-Telegram-Bot-Api-Secret-Token 验签，fail-closed）：
- 无签名头 / 坏签名 / 实例未配密钥 → 一律 403，且**一条 update 都不许进处理入口**；
- 合法签名 → 2xx 快回（重活由端点后台派发，不阻塞响应），update 进入
  `_process_update`（经公开入口 `processWebhookUpdate`，monkeypatch 捕获验证）；
- 渠道未注册 → 404（与既有分派链同口径）。

管理面（set/delete/info 三端点，鉴权＝requireAgentOwner，default 无主即仅 admin）：
- 普通用户（非属主）403；admin 可用；
- 三端点分别调 mixin 三方法并透传真实结果（成功/失败都不谎报）；
- 不具备 webhook 管理能力的渠道 → 400 点名，不 AttributeError 500。
"""

import json
import time

import pytest
from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.api.deps import get_current_user
from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import FeishuAdapter
from neurova.channels.manager import ChannelManager, get_channel_manager
from neurova.channels.telegram_adapter import TelegramAdapter

WEBHOOK = "/api/v1/channel-adapters/telegram/webhook"
WEBHOOK_SET = "/api/v1/channel-adapters/telegram/webhook/set"
WEBHOOK_INFO = "/api/v1/channel-adapters/telegram/webhook/info"
SECRET = "tg-webhook-secret-live"

ADMIN = {"user_id": "root", "username": "root", "role": "admin", "neuser_id": "root"}
USER = {"user_id": "u1", "username": "alice", "role": "user", "neuser_id": "u1"}

SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _makeTelegram(secret: str = SECRET) -> TelegramAdapter:
    """已认证、已配 webhook 密钥的 Telegram 实例（不起外网、不连 Telegram）。"""
    adapter = TelegramAdapter()
    adapter.bot_token = "123:test-token"
    adapter._initialized = True
    adapter._webhook_secret = secret
    return adapter


def _update(text: str = "hello") -> dict:
    """最小合法 Telegram update（文本消息）。"""
    return {
        "update_id": 1,
        "message": {
            "message_id": 11,
            "from": {"id": 42, "username": "tester"},
            "chat": {"id": -1001, "type": "private"},
            "text": text,
        },
    }


def _waitUntil(predicate, timeout: float = 2.0) -> bool:
    """后台派发是 fire-and-forget：轮询等它落地（超时即判负）。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


@pytest.fixture()
def tgFace():
    """真 app + 真分派链；telegram 实例由测试侧注册（不依赖外网凭据）。

    `set_app_state({"agents": {}})` 置空运行实例表 → default 视为无主 →
    管理面属主门退化为"仅 admin"，普通用户 403 可断言。
    """
    from neurova.api.endpoints import set_app_state

    ChannelManager._instance = None
    app = create_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        set_app_state({"agents": {}})
        adapter = _makeTelegram()
        get_channel_manager().register_adapter(adapter)
        yield client, adapter
        client.app.dependency_overrides.pop(get_current_user, None)
    set_app_state(None)
    ChannelManager._instance = None


def _as(client, identity: dict) -> None:
    client.app.dependency_overrides[get_current_user] = lambda: identity


# ============================================================
# 接收面：验签 fail-closed，合法才进处理入口
# ============================================================


class TestTelegramWebhookReceive:
    def testUnsignedPushRejectedAndNeverDispatched(self, tgFace):
        client, adapter = tgFace
        captured = []
        adapter._process_update = lambda upd: captured.append(upd)

        r = client.post(WEBHOOK, json=_update())  # 不带签名头

        assert r.status_code == 403, f"无签名推送被放行：{r.status_code} {r.text[:160]}"
        assert not captured, "被拒的同时还进了处理入口——验签形同虚设"

    def testBadSecretPushRejected(self, tgFace):
        client, adapter = tgFace
        captured = []
        adapter._process_update = lambda upd: captured.append(upd)

        r = client.post(WEBHOOK, json=_update(),
                        headers={SECRET_HEADER: "not-the-secret"})

        assert r.status_code == 403, f"坏签名推送被放行：{r.status_code} {r.text[:160]}"
        assert not captured

    def testFailClosedWhenSecretNotConfigured(self, tgFace):
        """未配置 _webhook_secret 时必须拒绝（C-10 口径），不能'没密钥就放行'。"""
        client, adapter = tgFace
        adapter._webhook_secret = ""
        captured = []
        adapter._process_update = lambda upd: captured.append(upd)

        r = client.post(WEBHOOK, json=_update(),
                        headers={SECRET_HEADER: "anything"})

        assert r.status_code == 403, f"未配密钥时推送被放行：{r.status_code} {r.text[:160]}"
        assert not captured

    def testValidSignatureReachesProcessUpdateAndAnswersFast(self, tgFace):
        """合法签名 → 2xx 快回 + update 进入 _process_update（后台派发落地）。"""
        client, adapter = tgFace
        captured = []
        adapter._process_update = lambda upd: captured.append(upd)

        r = client.post(WEBHOOK, json=_update("正常消息"),
                        headers={SECRET_HEADER: SECRET})

        assert r.status_code == 200, f"合法签名被拒：{r.status_code} {r.text[:160]}"
        assert r.json() == {"ok": True}
        assert _waitUntil(lambda: len(captured) == 1), (
            f"合法 update 未进入 _process_update（捕获 {len(captured)} 条）")
        assert captured[0]["message"]["text"] == "正常消息"

    def testGarbageBodyWithValidSignatureRejected(self, tgFace):
        """签名对但体不是 JSON：拒收（不是合法平台回调），不投递、不 500。"""
        client, adapter = tgFace
        captured = []
        adapter._process_update = lambda upd: captured.append(upd)

        r = client.post(WEBHOOK, content=b"this-is-not-json",
                        headers={SECRET_HEADER: SECRET})

        assert r.status_code in (400, 403), f"垃圾体被放行：{r.status_code} {r.text[:160]}"
        assert not captured

    def testUnregisteredTelegramReturns404(self, tgFace):
        """渠道没注册时 404（与既有分派链同口径），不是 500。"""
        client, _adapter = tgFace
        mgr = get_channel_manager()
        mgr.unregister_adapter("telegram", agent_id="default")

        r = client.post(WEBHOOK, json=_update(), headers={SECRET_HEADER: SECRET})

        assert r.status_code == 404, f"未注册渠道返回 {r.status_code}：{r.text[:160]}"


# ============================================================
# 管理面：requireAgentOwner 门 + mixin 三方法透传
# ============================================================


class TestTelegramWebhookManagement:
    def testNormalUserForbiddenOnAllThree(self, tgFace):
        """default 无主 agent：非 admin 一律 403，三端点都不例外。"""
        client, adapter = tgFace
        _as(client, USER)
        calls = []
        adapter.set_webhook = lambda *a, **k: calls.append(("set", a)) or True
        adapter.delete_webhook = lambda *a, **k: calls.append(("del", a)) or True
        adapter.get_webhook_info = lambda *a, **k: calls.append(("info", a)) or {}

        assert client.post(WEBHOOK_SET, json={"webhook_url": "https://x/tg"}).status_code == 403
        assert client.delete(WEBHOOK).status_code == 403
        assert client.get(WEBHOOK_INFO).status_code == 403
        assert not calls, "403 的同时 mixin 还被调用了——门没关住"

    def testAnonymousForbiddenOnManagementFace(self, tgFace):
        """未登录（无身份覆盖）→ 401/403，不得落到管理员分支。"""
        client, _adapter = tgFace
        assert client.post(WEBHOOK_SET, json={"webhook_url": "https://x/tg"}).status_code in (401, 403)
        assert client.delete(WEBHOOK).status_code in (401, 403)
        assert client.get(WEBHOOK_INFO).status_code in (401, 403)

    def testSetWebhookPassesArgsAndSuccessThrough(self, tgFace):
        client, adapter = tgFace
        _as(client, ADMIN)
        seen = {}

        def _fakeSet(url, secret_token=""):
            seen["args"] = (url, secret_token)
            return True

        adapter.set_webhook = _fakeSet

        r = client.post(WEBHOOK_SET, json={
            "webhook_url": "https://example.com/tg", "secret_token": "s2"})

        assert r.status_code == 200, r.text[:160]
        assert r.json()["success"] is True, "mixin 返回 True 却被报成失败"
        assert seen["args"] == ("https://example.com/tg", "s2"), f"参数未透传：{seen}"

    def testSetWebhookFailurePassesThrough(self, tgFace):
        """Telegram 侧拒绝（mixin 返回 False）→ success=false 透传，不谎报成功。"""
        client, adapter = tgFace
        _as(client, ADMIN)
        adapter.set_webhook = lambda url, secret_token="": False

        r = client.post(WEBHOOK_SET, json={"webhook_url": "https://example.com/tg"})

        assert r.status_code == 200 and r.json()["success"] is False, r.text[:160]

    def testDeleteWebhookPassesFlagAndResultThrough(self, tgFace):
        client, adapter = tgFace
        _as(client, ADMIN)
        seen = {}

        def _fakeDelete(drop_pending_updates=False):
            seen["drop"] = drop_pending_updates
            return True

        adapter.delete_webhook = _fakeDelete

        r = client.delete(f"{WEBHOOK}?drop_pending_updates=true")

        assert r.status_code == 200 and r.json()["success"] is True, r.text[:160]
        assert seen["drop"] is True, "drop_pending_updates 未透传到 mixin"

    def testWebhookInfoPassesResultThrough(self, tgFace):
        client, adapter = tgFace
        _as(client, ADMIN)
        info = {"url": "https://example.com/tg", "pending_update_count": 3}
        adapter.get_webhook_info = lambda: info

        r = client.get(WEBHOOK_INFO)

        assert r.status_code == 200, r.text[:160]
        body = r.json()
        assert body["success"] is True and body["data"] == info, body

    def testWebhookInfoNoneMeansFailure(self, tgFace):
        """getWebhookInfo 失败（mixin 返回 None）→ success=false，不编造数据。"""
        client, adapter = tgFace
        _as(client, ADMIN)
        adapter.get_webhook_info = lambda: None

        r = client.get(WEBHOOK_INFO)

        assert r.status_code == 200 and r.json()["success"] is False and r.json()["data"] is None

    def testUnsupportedChannelGets400Not500(self, tgFace):
        """没有 webhook 管理能力的渠道（如飞书）→ 400 点名，不 AttributeError 500。"""
        client, _adapter = tgFace
        _as(client, ADMIN)
        fs = FeishuAdapter(ChannelConfig(channel_type="feishu", app_id="cli",
                                         app_secret="sec", verification_token="tok"))
        get_channel_manager().register_adapter(fs)

        r = client.post("/api/v1/channel-adapters/feishu/webhook/set",
                        json={"webhook_url": "https://x/fs"})

        assert r.status_code == 400, f"不支持渠道返回 {r.status_code}：{r.text[:160]}"
        assert "webhook" in r.text.lower()

    def testMissingChannelReturns404(self, tgFace):
        client, _adapter = tgFace
        _as(client, ADMIN)
        get_channel_manager().unregister_adapter("telegram", agent_id="default")

        assert client.get(WEBHOOK_INFO).status_code == 404
