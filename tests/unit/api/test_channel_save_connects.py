# -*- coding: utf-8 -*-
"""保存渠道必须按 enabled 即时 connect/断开（启用后不重启即生效）。

根因回归：create_or_update_config 此前只 register_adapter 不 connect，连接仅在
启动 bootstrap 做——用户后端启动后启用飞书/钉钉/微信长连接渠道 → 适配器登记但
从不建连 → "启用后仍无响应"。且重存同渠道时旧连接不拆 → 飞书单机器人双连接被拒。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import channel_config as cc


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(cc, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(cc, "CONFIG_FILE", tmp_path / "channel_configs.json")

    made = {}

    class FakeAdapter:
        channel_type = "feishu"
        def __init__(self):
            self.connected = False
            self.disconnected = False
        def set_event_callback(self, cb):
            self._cb = cb
        async def connect(self):
            self.connected = True
            made["connects"] = made.get("connects", 0) + 1
            return True
        async def disconnect(self):
            self.disconnected = True
            made["disconnects"] = made.get("disconnects", 0) + 1

    def new_adapter():
        a = FakeAdapter()
        made["adapter"] = a
        return a

    monkeypatch.setattr(cc, "_create_adapter", lambda *a, **k: new_adapter())

    # 真 ChannelManager 单例（隔离），记录 get/unregister
    from neurova.channels.manager import ChannelManager
    ChannelManager._instance = None
    mgr = ChannelManager()
    monkeypatch.setattr(cc, "get_channel_manager", lambda: mgr)
    yield mgr, made, FakeAdapter
    ChannelManager._instance = None


def _req(enabled=True, extra=None):
    return cc.ChannelConfigRequest(
        channel_type="feishu", enabled=enabled,
        app_id="cli_x", app_secret="s", use_stream=True, extra=extra or {"domain": "feishu"},
    )


@pytest.mark.asyncio
async def test_save_enabled_connects(env):
    mgr, made, _ = env
    res = await cc.create_or_update_config(_req(enabled=True))
    assert res["success"] is True
    assert made["connects"] == 1, "启用保存必须即时 connect（不重启即生效）"
    assert made["adapter"].connected is True
    assert mgr.get_adapter("feishu", agent_id="default") is made["adapter"]


@pytest.mark.asyncio
async def test_save_disabled_does_not_connect(env):
    mgr, made, _ = env
    res = await cc.create_or_update_config(_req(enabled=False))
    assert res["success"] is True
    assert made.get("connects", 0) == 0, "停用保存不得连接"
    assert mgr.get_adapter("feishu", agent_id="default") is None, "停用后不应留有连接实例"


@pytest.mark.asyncio
async def test_resave_tears_down_previous_connection(env):
    """重存同渠道：旧适配器必须先 disconnect（飞书单机器人仅 1 条长连接）。"""
    mgr, made, _ = env
    await cc.create_or_update_config(_req(enabled=True))
    first = made["adapter"]
    await cc.create_or_update_config(_req(enabled=True))
    assert first.disconnected is True, "重存必须先断开旧实例连接，否则双连接被平台拒"
    assert made["connects"] == 2
