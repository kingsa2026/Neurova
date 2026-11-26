# -*- coding: utf-8 -*-
"""CHAN-07：ChannelManager 启停必须使用同一份实例清单。

审计证据（docs/05-reports/全仓逐文件审计报告_2026-11-25.md §8 CHAN-07）：
`start()` 遍历 `_agent_adapters` 全量实例表（agent 隔离多实例），`stop()`
只遍历 default 兼容视图 `_adapters`——挂在非 default agent 名下的适配器
停机时不断开，长连接/接收线程残留；进程退出前也停不掉。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from neurova.channels.manager import ChannelManager, get_channel_manager


class _StubAdapter:
    def __init__(self, channel_type: str):
        self.channel_type = channel_type
        self.config = SimpleNamespace(enabled=True)
        self.connected = False
        self._event_callback = None
        self.agent_id = "default"

    def set_event_callback(self, callback):
        self._event_callback = callback

    async def connect(self):
        self.connected = True
        return True

    async def disconnect(self):
        self.connected = False


@pytest.fixture()
def manager(tmp_path):
    from tests.manual._liveVerifyIsolation import isolatedDataRoot

    isolatedDataRoot()
    ChannelManager._instance = None
    mgr = get_channel_manager()
    mgr.ingress_queue = None  # 队列排水不是本判据主张
    yield mgr
    ChannelManager._instance = None


def testStopDisconnectsNonDefaultAgentInstances(manager):
    defaultAdapter = _StubAdapter("feishu")
    kaiAdapter = _StubAdapter("telegram")
    manager.register_adapter(defaultAdapter, agent_id="default")
    manager.register_adapter(kaiAdapter, agent_id="kai")
    asyncio.run(manager.start())
    assert kaiAdapter.connected is True, "前置：start 应连接非 default 实例"

    asyncio.run(manager.stop())

    assert kaiAdapter.connected is False, (
        "停机遗漏了挂在 agent=kai 名下的适配器（连接/线程会残留到进程退出）"
    )
    assert defaultAdapter.connected is False


def testStartAndStopCoverTheSameInstanceSet(manager):
    adapters = [
        _StubAdapter("feishu"),
        _StubAdapter("telegram"),
    ]
    manager.register_adapter(adapters[0], agent_id="default")
    manager.register_adapter(adapters[1], agent_id="kai")
    asyncio.run(manager.start())
    connected = {a.channel_type for a in adapters if a.connected}
    asyncio.run(manager.stop())
    disconnected = {a.channel_type for a in adapters if not a.connected}

    assert connected == disconnected, (
        f"start/stop 的实例定义域不一致：连接过 {connected}，停机只断开 {disconnected}"
    )