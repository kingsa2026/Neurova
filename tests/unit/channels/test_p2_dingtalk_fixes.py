"""
P2 修复测试（2026-08 代码审计）— 钉钉 Webhook

覆盖 bug:
1. DingTalkWebhookBot.send_text 使用 hmac.new() 但模块从未 import hmac
   → 配置了 secret 的机器人每次发送都抛 NameError
2. send_markdown 完全不加签 → 配置了 secret 的机器人 markdown 消息必然被钉钉拒绝
修复: 抽取 _build_signed_url()，send_text/send_markdown 统一走加签 URL。
"""

import base64
import hashlib
import hmac as hmac_module
import urllib.parse

import pytest

from neurova.channels.dingtalk import DingTalkWebhookBot


class _FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {"errcode": 0}

    async def json(self):
        return self._payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


def _patch_aiohttp(monkeypatch, captured):
    import sys
    import types

    fake = types.ModuleType("aiohttp")

    class ClientTimeout:
        def __init__(self, total=None):
            self.total = total

    class ClientSession:
        def post(self, url, json=None, timeout=None):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

    fake.ClientTimeout = ClientTimeout
    fake.ClientSession = ClientSession
    monkeypatch.setitem(sys.modules, "aiohttp", fake)


class TestSignedUrl:
    def test_build_signed_url_contains_timestamp_and_sign(self):
        bot = DingTalkWebhookBot("https://oapi.dingtalk.com/robot/send?access_token=t", secret="SEC123")
        url = bot._build_signed_url()
        assert "timestamp=" in url
        assert "sign=" in url

    def test_build_signed_url_matches_reference_hmac(self):
        secret = "SEC123"
        bot = DingTalkWebhookBot("https://oapi.dingtalk.com/robot/send?access_token=t", secret=secret)
        url = bot._build_signed_url()

        parsed = urllib.parse.urlparse(url)
        query = urllib.parse.parse_qs(parsed.query)
        timestamp = query["timestamp"][0]
        sign = query["sign"][0]

        sign_str = f"{timestamp}\n{secret}"
        expected_code = hmac_module.new(
            secret.encode("utf-8"), sign_str.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        # parse_qs 已对查询值做 URL 解码，故与未加引号的 base64 原文比较
        expected_sign = base64.b64encode(expected_code).decode("utf-8")
        assert sign == expected_sign

    def test_no_secret_returns_plain_url(self):
        bot = DingTalkWebhookBot("https://oapi.dingtalk.com/robot/send?access_token=t")
        assert bot._build_signed_url() == bot.webhook_url


class TestSendTextSigning:
    @pytest.mark.asyncio
    async def test_send_text_with_secret_uses_signed_url(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured)
        bot = DingTalkWebhookBot("https://oapi.dingtalk.com/robot/send?access_token=t", secret="SEC123")

        result = await bot.send_text("hello")

        assert result is True
        assert "sign=" in captured["url"], "配置 secret 时 send_text 必须使用加签 URL"
        assert "timestamp=" in captured["url"]

    @pytest.mark.asyncio
    async def test_send_text_without_secret_no_sign(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured)
        bot = DingTalkWebhookBot("https://oapi.dingtalk.com/robot/send?access_token=t")

        result = await bot.send_text("hello")

        assert result is True
        assert "sign=" not in captured["url"]


class TestSendMarkdownSigning:
    @pytest.mark.asyncio
    async def test_send_markdown_with_secret_uses_signed_url(self, monkeypatch):
        captured = {}
        _patch_aiohttp(monkeypatch, captured)
        bot = DingTalkWebhookBot("https://oapi.dingtalk.com/robot/send?access_token=t", secret="SEC123")

        result = await bot.send_markdown("标题", "正文")

        assert result is True
        assert "sign=" in captured["url"], (
            "配置 secret 时 send_markdown 也必须加签，否则钉钉拒绝消息"
        )
        assert captured["json"]["msgtype"] == "markdown"
