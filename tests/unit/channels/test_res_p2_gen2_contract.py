"""
RES-P2-12 + Gen2 契约补齐 防回归测试（资源型Bug扫描报告 2026-09-11 渠道域）

- P2-12: telegram_api_client.py / qqbot.py 的 async _download_url 在 httpx 不可用时的
  requests 回退分支必须经 asyncio.to_thread 下沉（原实现阻塞事件循环至 60s）。
- Gen2 契约: qq/qqbot 适配器 __init__ 未走基类 ChannelAdapter.__init__，缺
  self.config / self._connected / self._event_callback，导致基类 channel_type 属性、
  health_check、is_connected、_emit_event 全部 AttributeError。
  （telegram_adapter/discord/websocket 已由 C-03/C-04 修复，本文件不重复覆盖。）

隔离纪律：无真实网络。httpx 已安装的环境下用 monkeypatch 强制走 requests 回退分支；
requests.get 打桩并记录执行线程。
"""

import asyncio
import sys
import threading
from types import SimpleNamespace

import pytest

import neurova.channels.qqbot as qqbot_module
import neurova.channels.telegram_api_client as tac_module
from neurova.channels.base import ChannelConfig, ChannelEventType
from neurova.channels.qq import QQAdapter
from neurova.channels.qqbot import QQBotAdapter


# ============================================================
# P2-12 telegram_api_client._download_url
# ============================================================


class _Resp:
    status_code = 200

    def __init__(self, body: bytes):
        self.content = body


@pytest.mark.asyncio
async def test_p2_12_telegram_download_url_fallback_offloads_requests(monkeypatch):
    # sys.modules 值为 None 时 import httpx 抛 ImportError → 强制进入 requests 回退分支
    monkeypatch.setitem(sys.modules, "httpx", None)

    loop_thread = threading.current_thread()
    seen = {}

    def fake_get(url, timeout=None):
        seen["thread"] = threading.current_thread()
        seen["timeout"] = timeout
        return _Resp(b"payload-bytes")

    monkeypatch.setattr(tac_module.requests, "get", fake_get)

    mixin = tac_module.TelegramAPIMixin()
    data = await mixin._download_url("http://unit.test/fake", timeout=7)

    assert data == b"payload-bytes"
    assert seen["timeout"] == 7
    assert seen["thread"] is not loop_thread, (
        "P2-12 未修复：requests 回退分支直接跑在事件循环线程上，最长阻塞 60s"
    )


@pytest.mark.asyncio
async def test_p2_12_qqbot_download_url_fallback_offloads_requests(monkeypatch):
    monkeypatch.setattr(qqbot_module, "HTTPX_AVAILABLE", False)

    loop_thread = threading.current_thread()
    seen = {}

    def fake_get(url, timeout=None):
        seen["thread"] = threading.current_thread()
        return _Resp(b"qqbot-bytes")

    monkeypatch.setattr(qqbot_module.requests, "get", fake_get)

    data = await qqbot_module._download_url(object(), "http://unit.test/fake")

    assert data == b"qqbot-bytes"
    assert seen["thread"] is not loop_thread, (
        "P2-12 未修复：requests 回退分支直接跑在事件循环线程上，最长阻塞 60s"
    )


# ============================================================
# Gen2 契约：QQAdapter 三件套 + health_check + _emit_event 可用
# ============================================================


def test_gen2_qq_adapter_contract_trio():
    adapter = QQAdapter()
    assert isinstance(adapter.config, ChannelConfig), "Gen2 未修复：QQAdapter 缺 self.config"
    assert adapter.config.channel_type == "qq"
    assert adapter.config.enabled is False
    assert adapter._connected is False, "Gen2 未修复：QQAdapter 缺 self._connected"
    assert adapter._event_callback is None, "Gen2 未修复：QQAdapter 缺 self._event_callback"
    assert adapter.channel_type == "qq"
    assert adapter.is_connected is False


@pytest.mark.asyncio
async def test_gen2_qq_adapter_health_check_and_emit():
    adapter = QQAdapter()
    health = await adapter.health_check()
    assert health["channel_type"] == "qq"
    assert health["connected"] is False
    assert health["enabled"] is False

    received = []

    async def cb(event_type, message):
        received.append(message)

    adapter.set_event_callback(cb)
    await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, SimpleNamespace(content="x"))
    assert len(received) == 1


# ============================================================
# Gen2 契约：QQBotAdapter 三件套（生产类缺 connect/disconnect 抽象实现，
# 测试子类补齐——该缺口另行登记）
# ============================================================


class _QQBotTestAdapter(QQBotAdapter):
    async def connect(self) -> bool:
        return True

    async def disconnect(self):
        return None


def test_gen2_qqbot_adapter_contract_trio():
    adapter = _QQBotTestAdapter()
    assert isinstance(adapter.config, ChannelConfig), "Gen2 未修复：QQBotAdapter 缺 self.config"
    assert adapter.config.channel_type == "qqbot"
    assert adapter.config.enabled is False
    assert adapter._connected is False, "Gen2 未修复：QQBotAdapter 缺 self._connected"
    assert adapter._event_callback is None, "Gen2 未修复：QQBotAdapter 缺 self._event_callback"
    assert adapter.channel_type == "qqbot"


@pytest.mark.asyncio
async def test_gen2_qqbot_adapter_health_check():
    adapter = _QQBotTestAdapter()
    health = await adapter.health_check()
    assert health["channel_type"] == "qqbot"
    assert health["connected"] is False
    assert health["enabled"] is False
