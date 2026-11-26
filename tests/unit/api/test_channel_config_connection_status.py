# -*- coding: utf-8 -*-
"""CHAN-08：渠道配置读面必须透传端到端连接状态，不能只看传输 is_connected。"""

from __future__ import annotations

import os

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_channel_status_0123")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import channel_config as channelConfigModule
from neurova.channels.discord import DiscordAdapter
from neurova.channels.manager import ChannelManager


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(channelConfigModule.router, prefix="/api/v1")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin", "username": "admin", "role": "admin"
    }
    ChannelManager._instance = None
    channelConfigModule._save_store({
        "version": 2,
        "agents": {"default": {"discord": {
            "channel_type": "discord", "enabled": True,
            "app_id": "", "app_secret": "", "use_stream": True,
            "extra": {"bot_token": "token"},
        }}},
    })
    manager = ChannelManager.get_instance()
    adapter = DiscordAdapter()
    adapter.bot_token = "token"
    monkeypatch.setattr(adapter, "_verify_token", lambda: True)
    manager.register_adapter(adapter)
    import asyncio

    assert asyncio.run(adapter.connect()) is True
    with TestClient(app, raise_server_exceptions=False) as testClient:
        yield testClient
    ChannelManager._instance = None
    app.dependency_overrides.clear()


def testListConfigDoesNotReportOutboundOnlyAdapterAsConnected(client):
    response = client.get("/api/v1/channel-configs")
    assert response.status_code == 200
    row = response.json()[0]
    assert row["connected"] is False
    assert row["transport_connected"] is True
    assert row["status"] == "not_supported"
    assert "discord" in row["inbound_reason"]


def testSingleConfigUsesSameConnectionStatusContract(client):
    response = client.get("/api/v1/channel-configs/discord")
    assert response.status_code == 200
    row = response.json()
    assert row["connected"] is False
    assert row["transport_connected"] is True
    assert row["status"] == "not_supported"
