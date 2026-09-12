# -*- coding: utf-8 -*-
"""渠道二维码授权 handler 契约测试（对齐 QwenPaw qrcode_auth_handler，2026-09-13）。

覆盖 5 个 handler 的真实官方协议语义（QwenPaw 照搬）：
- feishu   : RFC 8628 device flow @ accounts.feishu.cn / accounts.larksuite.com
- dingtalk : /app/registration init→begin→poll @ oapi.dingtalk.com
- qq       : /lite/create_bind_task + poll_bind_result @ q.qq.com（AES-256-GCM 解出 bot secret）
- wecom    : /ai/qc/gen 抓 window.settings + /ai/qc/query_result @ work.weixin.qq.com
- wechat   : ilinkai.weixin.qq.com get_bot_qrcode/get_qrcode_status（真实 iLink 端点，
             取代 NV 旧的虚构 ilink.wechat.bot）
以及 generate_qrcode_image（segno PNG base64）。

全程用 Fake AsyncClient 替身 httpx，不发真实网络请求。
"""

from __future__ import annotations

import base64
import io
import json
from types import SimpleNamespace

import pytest


class _FakeResponse:
    def __init__(self, payload, text=""):
        self._payload = payload
        self.text = text or json.dumps(payload)
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeAsyncClient:
    """按 (method, url 前缀) 路由的 httpx.AsyncClient 替身。

    responses: list of dicts {method, url_startswith, json?|text?}，
    每次匹配消费一条（保序）。记录调用供断言。
    """

    _next_routes: list = []
    _usage: dict = {}  # 类级共享：每次 async with 新建实例也要延续消费游标

    def __init__(self, *args, **kwargs):
        self._routes = type(self)._next_routes

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def _match(self, method, url):
        for route in self._routes:
            if route["method"] != method:
                continue
            if not url.startswith(route["url_startswith"]):
                continue
            used = type(self)._usage.get(id(route), 0)
            if route.get("times", 1) <= used:
                continue
            type(self)._usage[id(route)] = used + 1
            return route
        raise AssertionError(f"unrouted request: {method} {url}")

    async def get(self, url, params=None, headers=None, timeout=None):
        type(self).calls.append(("GET", url, params))
        route = self._match("GET", url)
        return _FakeResponse(route.get("json", {}), route.get("text", ""))

    async def post(self, url, json=None, data=None, headers=None, timeout=None, content=None):
        type(self).calls.append(("POST", url, json or data or content))
        route = self._match("POST", url)
        return _FakeResponse(route.get("json", {}), route.get("text", ""))


@pytest.fixture
def httpx_routes(monkeypatch):
    import httpx

    def _setup(routes):
        FakeAsyncClient._next_routes = routes
        FakeAsyncClient.calls = []
        FakeAsyncClient._usage = {}  # 每用例重置：route dict 新对象但 id() 可能复用
        monkeypatch.setattr(httpx, "AsyncClient", FakeAsyncClient)

    return _setup


def _req(**query):
    return SimpleNamespace(query_params=query)


# ------------------------------------------------------------------
# 注册表与图片生成
# ------------------------------------------------------------------


def test_registry_has_five_channels():
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    assert set(QRCODE_AUTH_HANDLERS) == {"feishu", "dingtalk", "qq", "wecom", "wechat"}


def test_generate_qrcode_image_returns_base64_png():
    from neurova.channels.qrcode_auth import generate_qrcode_image

    b64 = generate_qrcode_image("https://example.com/scan?a=1")
    raw = base64.b64decode(b64)
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"


# ------------------------------------------------------------------
# 飞书：RFC 8628 device flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_feishu_fetch_and_poll(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "POST", "url_startswith": "https://accounts.feishu.cn/oauth/v1/app/registration",
         "json": {"supported_auth_methods": ["client_secret"]}},
        {"method": "POST", "url_startswith": "https://accounts.feishu.cn/oauth/v1/app/registration",
         "json": {"device_code": "dc-123",
                  "verification_uri_complete": "https://open.feishu.cn/page/cli?foo=1"}},
        {"method": "POST", "url_startswith": "https://accounts.feishu.cn/oauth/v1/app/registration",
         "json": {"client_id": "cli_a", "client_secret": "sec_b",
                  "user_info": {"open_id": "ou_x", "tenant_brand": "feishu"}}},
    ])
    h = QRCODE_AUTH_HANDLERS["feishu"]
    qr = await h.fetch_qrcode(_req())
    assert qr.poll_token == "dc-123"
    assert qr.scan_url.startswith("https://open.feishu.cn/page/cli?foo=1&")
    assert "source=NEUROVA" in qr.scan_url

    poll = await h.poll_status(qr.poll_token, _req())
    assert poll.status == "success"
    assert poll.credentials["app_id"] == "cli_a"
    assert poll.credentials["app_secret"] == "sec_b"


@pytest.mark.asyncio
async def test_feishu_lark_domain_query_param(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "POST", "url_startswith": "https://accounts.larksuite.com/oauth/v1/app/registration",
         "json": {"supported_auth_methods": ["client_secret"]}},
        {"method": "POST", "url_startswith": "https://accounts.larksuite.com/oauth/v1/app/registration",
         "json": {"device_code": "dc-l", "verification_uri_complete": "https://larksuite.com/x"}},
    ])
    h = QRCODE_AUTH_HANDLERS["feishu"]
    qr = await h.fetch_qrcode(_req(domain="lark"))
    assert qr.poll_token == "dc-l"
    assert FakeAsyncClient.calls[0][1].startswith("https://accounts.larksuite.com")


@pytest.mark.asyncio
async def test_feishu_poll_expired(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "POST", "url_startswith": "https://accounts.feishu.cn/oauth/v1/app/registration",
         "json": {"error": "expired_token"}},
    ])
    h = QRCODE_AUTH_HANDLERS["feishu"]
    poll = await h.poll_status("dc", _req())
    assert poll.status == "expired"


@pytest.mark.asyncio
async def test_feishu_poll_pending_is_waiting(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "POST", "url_startswith": "https://accounts.feishu.cn/oauth/v1/app/registration",
         "json": {"error": "authorization_pending"}},
    ])
    h = QRCODE_AUTH_HANDLERS["feishu"]
    poll = await h.poll_status("dc", _req())
    assert poll.status == "waiting"


# ------------------------------------------------------------------
# 钉钉：device flow
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dingtalk_fetch_and_poll(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "POST", "url_startswith": "https://oapi.dingtalk.com/app/registration/init",
         "json": {"errcode": 0, "nonce": "n-1"}},
        {"method": "POST", "url_startswith": "https://oapi.dingtalk.com/app/registration/begin",
         "json": {"errcode": 0, "device_code": "dev-9",
                  "verification_uri_complete": "https://open-dev.dingtalk.com/qr/abc"}},
        {"method": "POST", "url_startswith": "https://oapi.dingtalk.com/app/registration/poll",
         "json": {"status": "SUCCESS", "client_id": "cid", "client_secret": "csec"}},
        {"method": "POST", "url_startswith": "https://oapi.dingtalk.com/app/registration/poll",
         "json": {"status": "WAITING"}},
    ])
    h = QRCODE_AUTH_HANDLERS["dingtalk"]
    qr = await h.fetch_qrcode(_req())
    assert qr.scan_url == "https://open-dev.dingtalk.com/qr/abc"
    assert qr.poll_token == "dev-9"
    # init 带 source=NEUROVA
    assert FakeAsyncClient.calls[0][2]["source"] == "NEUROVA"

    poll = await h.poll_status(qr.poll_token, _req())
    assert poll.status == "success"
    assert poll.credentials == {"client_id": "cid", "client_secret": "csec"}

    waiting = await h.poll_status(qr.poll_token, _req())
    assert waiting.status == "waiting"


@pytest.mark.asyncio
async def test_dingtalk_null_client_id_not_success(httpx_routes):
    """官方 poll 可能返回 client_id:null——不得把 None 变 'None' 字符串判成功。"""
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "POST", "url_startswith": "https://oapi.dingtalk.com/app/registration/poll",
         "json": {"status": "CREATING", "client_id": None, "client_secret": None}},
    ])
    h = QRCODE_AUTH_HANDLERS["dingtalk"]
    poll = await h.poll_status("dev", _req())
    assert poll.status == "waiting"


# ------------------------------------------------------------------
# QQ：绑定任务 + AES-256-GCM
# ------------------------------------------------------------------


def _encrypt_bot_secret(plaintext: str, key_b64: str) -> str:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = base64.b64decode(key_b64)
    iv = b"\x00" * 12
    raw = iv + AESGCM(key).encrypt(iv, plaintext.encode(), None)
    return base64.b64encode(raw).decode()


@pytest.mark.asyncio
async def test_qq_fetch_and_poll_decrypt(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS, decode_poll_token

    httpx_routes([
        {"method": "POST", "url_startswith": "https://q.qq.com/lite/create_bind_task",
         "json": {"retcode": 0, "data": {"task_id": "t-1"}}},
        {"method": "POST", "url_startswith": "https://q.qq.com/lite/poll_bind_result",
         "json": {"retcode": 0, "data": {"status": 2, "bot_appid": "12345",
                                         "bot_encrypt_secret": "placeholder",
                                         "user_openid": "open-1"}}},
    ])
    h = QRCODE_AUTH_HANDLERS["qq"]
    qr = await h.fetch_qrcode(_req())
    assert "q.qq.com/qqbot/openclaw/connect.html" in qr.scan_url
    assert "source=NEUROVA" in qr.scan_url
    task_id, aes_key = decode_poll_token(qr.poll_token)
    assert task_id == "t-1"

    # 用真实 key 重加密后再走 poll
    routes = FakeAsyncClient._next_routes
    routes[1]["json"]["data"]["bot_encrypt_secret"] = _encrypt_bot_secret("s3cr3t", aes_key)

    poll = await h.poll_status(qr.poll_token, _req())
    assert poll.status == "success"
    assert poll.credentials["app_id"] == "12345"
    assert poll.credentials["client_secret"] == "s3cr3t"
    assert poll.credentials["user_openid"] == "open-1"


@pytest.mark.asyncio
async def test_qq_poll_expired_status3(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS, _encode_poll_token

    httpx_routes([
        {"method": "POST", "url_startswith": "https://q.qq.com/lite/poll_bind_result",
         "json": {"retcode": 0, "data": {"status": 3}}},
    ])
    h = QRCODE_AUTH_HANDLERS["qq"]
    poll = await h.poll_status(_encode_poll_token("t", base64.b64encode(b"k" * 32).decode()), _req())
    assert poll.status == "expired"


@pytest.mark.asyncio
async def test_qq_invalid_poll_token_400(httpx_routes):
    from fastapi import HTTPException

    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([])
    h = QRCODE_AUTH_HANDLERS["qq"]
    with pytest.raises(HTTPException) as ei:
        await h.poll_status("not-a-token", _req())
    assert ei.value.status_code == 400


# ------------------------------------------------------------------
# 企业微信：auth page settings 抓取
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wecom_fetch_and_poll(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    html = 'x window.settings = {"scode": "sc-1", "auth_url": "https://work.weixin.qq.com/auth/a"}; y'
    httpx_routes([
        {"method": "GET", "url_startswith": "https://work.weixin.qq.com/ai/qc/gen", "text": html},
        {"method": "GET", "url_startswith": "https://work.weixin.qq.com/ai/qc/query_result",
         "json": {"data": {"status": "success", "bot_info": {"botid": "bot-9", "secret": "sec-9"}}}},
    ])
    h = QRCODE_AUTH_HANDLERS["wecom"]
    qr = await h.fetch_qrcode(_req())
    assert qr.scan_url == "https://work.weixin.qq.com/auth/a"
    assert qr.poll_token == "sc-1"
    assert "source=neurova" in FakeAsyncClient.calls[0][1]

    poll = await h.poll_status(qr.poll_token, _req())
    assert poll.status == "success"
    assert poll.credentials == {"bot_id": "bot-9", "secret": "sec-9"}


# ------------------------------------------------------------------
# 微信 iLink：真实端点（取代虚构 ilink.wechat.bot）
# ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wechat_fetch_uses_real_ilink_host(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "GET", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/get_bot_qrcode",
         "json": {"qrcode": "qr-abc", "qrcode_img_content": ""}},
    ])
    h = QRCODE_AUTH_HANDLERS["wechat"]
    qr = await h.fetch_qrcode(_req())
    assert qr.poll_token == "qr-abc"
    assert qr.scan_url == "https://liteapp.weixin.qq.com/q/7GiQu1?qrcode=qr-abc&bot_type=3"


@pytest.mark.asyncio
async def test_wechat_poll_confirmed(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "GET", "url_startswith": "https://ilinkai.weixin.qq.com/ilink/bot/get_qrcode_status",
         "json": {"status": "confirmed", "bot_token": "tok-1", "baseurl": "https://gw.example.com"}},
    ])
    h = QRCODE_AUTH_HANDLERS["wechat"]
    poll = await h.poll_status("qr-abc", _req())
    assert poll.status == "confirmed"
    assert poll.credentials["bot_token"] == "tok-1"
    assert poll.credentials["base_url"] == "https://gw.example.com"


@pytest.mark.asyncio
async def test_wechat_poll_custom_base_url(httpx_routes):
    from neurova.channels.qrcode_auth import QRCODE_AUTH_HANDLERS

    httpx_routes([
        {"method": "GET", "url_startswith": "https://my.gateway.local/ilink/bot/get_bot_qrcode",
         "json": {"qrcode": "q2", "qrcode_img_content": ""}},
    ])
    h = QRCODE_AUTH_HANDLERS["wechat"]
    qr = await h.fetch_qrcode(_req(base_url="https://my.gateway.local"))
    assert qr.poll_token == "q2"
