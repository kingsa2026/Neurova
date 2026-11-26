# -*- coding: utf-8 -*-
"""CHAN-08：传输鉴权成功不等于渠道入站可用。

QQBot/Discord/QClaw/小艺没有生产接收链，旧企业微信 Stream 也没有接收循环；
它们可以保留真实出站能力，但状态面必须返回 connected=False + not_supported。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from neurova.channels.base import ChannelConfig
from neurova.channels.discord import DiscordAdapter
from neurova.channels.manager import ChannelManager
from neurova.channels.qclaw import QClawAdapter
from neurova.channels.qqbot import QQBotAdapter
from neurova.channels.wecom import WeComAdapter
from neurova.channels.xiaoyi import XiaoYiAdapter


@pytest.mark.asyncio
async def testDiscordTransportAuthDoesNotClaimInboundConnected(monkeypatch):
    adapter = DiscordAdapter()
    adapter.bot_token = "token"
    monkeypatch.setattr(adapter, "_verify_token", lambda: True)

    assert await adapter.connect() is True
    status = adapter.connectionStatus()
    assert status["transport_connected"] is True
    assert status["connected"] is False
    assert status["status"] == "not_supported"
    assert "discord" in status["inbound_reason"]


@pytest.mark.asyncio
async def testQQBotTransportAuthDoesNotClaimInboundConnected(monkeypatch):
    adapter = QQBotAdapter()
    adapter.access_token = "token"
    monkeypatch.setattr(adapter, "_verify_connection", lambda: True)

    assert await adapter.connect() is True
    status = adapter.connectionStatus()
    assert status["transport_connected"] is True
    assert status["connected"] is False
    assert status["status"] == "not_supported"
    assert "qqbot" in status["inbound_reason"]


@pytest.mark.asyncio
async def testQClawAuthenticationDoesNotClaimInboundConnected(monkeypatch):
    adapter = QClawAdapter(ChannelConfig(
        channel_type="qclaw", app_id="app", app_secret="secret"
    ))

    class Service:
        def verify_credentials(self, _appId, _secret):
            return {"valid": True}

        def get_access_token(self, _appId, _secret):
            return "token"

    monkeypatch.setattr("neurova.channels.qclaw.get_qclaw_service", lambda: Service())

    assert await adapter.connect() is True
    status = adapter.connectionStatus()
    assert status["transport_connected"] is True
    assert status["connected"] is False
    assert status["status"] == "not_supported"
    assert "qclaw" in status["inbound_reason"]


@pytest.mark.asyncio
async def testXiaoYiWebSocketDoesNotClaimInboundConnected(monkeypatch):
    adapter = XiaoYiAdapter()
    assert await adapter.authenticate({
        "access_key": "ak", "secret_key": "sk", "agent_id": "agent"
    }) is True

    async def fake_connect():
        adapter._connected = True

    monkeypatch.setattr(adapter, "_async_init_connection", fake_connect)

    assert await adapter.connect() is True
    status = adapter.connectionStatus()
    assert status["transport_connected"] is True
    assert status["connected"] is False
    assert status["status"] == "not_supported"
    assert "xiaoyi" in status["inbound_reason"]


@pytest.mark.asyncio
async def testWeComStreamIsNotSupportedButWebhookRemainsConnected(monkeypatch):
    async def fake_refresh():
        adapter._access_token = "token"
        adapter._token_expires_at = time.time() + 60

    adapter = WeComAdapter(ChannelConfig(
        channel_type="wecom", use_stream=True,
        extra={"corpid": "corp", "agentid": "1"},
    ))
    monkeypatch.setattr(adapter, "_refresh_access_token", fake_refresh)

    assert await adapter.connect() is True
    status = adapter.connectionStatus()
    assert status["transport_connected"] is True
    assert status["connected"] is False
    assert status["status"] == "not_supported"
    assert "wecom" in status["inbound_reason"]
    await adapter.disconnect()

    webhook = WeComAdapter(ChannelConfig(
        channel_type="wecom", use_stream=False, webhook_url="https://example.test/cb"
    ))
    assert await webhook.connect() is True
    webhookStatus = webhook.connectionStatus()
    assert webhookStatus["connected"] is True
    assert webhookStatus["status"] == "connected"
    await webhook.disconnect()


@pytest.mark.asyncio
async def testManagerStatusUsesEndToEndConnectivity(monkeypatch):
    manager = ChannelManager()
    adapter = DiscordAdapter()
    adapter.bot_token = "token"
    monkeypatch.setattr(adapter, "_verify_token", lambda: True)
    manager.register_adapter(adapter)
    assert await adapter.connect() is True

    listed = manager.list_adapters()["discord"]
    health = (await manager.health_check())["adapters"]["discord"]
    assert listed["connected"] is False
    assert listed["status"] == "not_supported"
    assert health["connected"] is False
    assert health["transport_connected"] is True
    assert health["status"] == "not_supported"
