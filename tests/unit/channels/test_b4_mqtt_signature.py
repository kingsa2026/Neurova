"""B-4 同根因收口（mqtt）：send_message 必须满足基类签名，manager 可直连。

含诚实化收口（2026-09-11，与 websocket/sip 同族）：paho 缺失或客户端未就绪
时发布诚实失败（None），不再模拟成功。
"""

from unittest.mock import MagicMock

import pytest

from neurova.channels import mqtt as mqtt_module
from neurova.channels.mqtt import MQTTAdapter


@pytest.fixture
def adapter():
    a = MQTTAdapter()
    a._initialized = True
    a._connected = True
    a._client = MagicMock()
    return a


@pytest.mark.asyncio
async def test_honest_failure_when_paho_missing(adapter, monkeypatch):
    """paho 缺失（本环境现状）：发布诚实失败返回 None，不再模拟成功。"""
    monkeypatch.setattr(mqtt_module, "MQTT_AVAILABLE", False)
    assert await adapter.send_message("device-1", "hello") is None


@pytest.mark.asyncio
async def test_base_signature_contract_success(adapter, monkeypatch):
    """paho 在位 + 客户端就绪：基类签名直调成功返回消息标识。"""
    from types import SimpleNamespace

    # paho 缺席环境：fake 模块命名空间提供 MQTT_ERR_SUCCESS（成功判定依据）
    monkeypatch.setattr(mqtt_module, "MQTT_AVAILABLE", True)
    monkeypatch.setattr(mqtt_module, "mqtt", SimpleNamespace(MQTT_ERR_SUCCESS=0), raising=False)
    adapter._client.publish.return_value = (0, 1)

    msg_id = await adapter.send_message("device-1", "hello", "text")
    assert isinstance(msg_id, str) and msg_id

    adapter._connected = False
    assert await adapter.send_message("device-1", "hello") is None


@pytest.mark.asyncio
async def test_delegates_to_unified_path(adapter, monkeypatch):
    """基类签名入参正确装配 UnifiedMessage 并委托内部路径。"""
    seen = {}

    def fake_send(message):
        seen["msg"] = message
        return True

    monkeypatch.setattr(adapter, "_send_unified", fake_send)
    msg_id = await adapter.send_message("device-1", "payload-body", "text", user_id="u1", priority=5)
    assert isinstance(msg_id, str) and msg_id
    assert seen["msg"].content == "payload-body"
    assert seen["msg"].chat_id == "device-1"
    assert seen["msg"].user_id == "u1"
    assert seen["msg"].metadata.get("priority") == 5
