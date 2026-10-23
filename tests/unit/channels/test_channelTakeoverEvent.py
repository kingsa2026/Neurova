"""渠道原生接管事件 → 会话质量事件账。"""
import asyncio
from datetime import datetime, timezone

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.manager import ChannelManager
from neurova.quality.outcome_store import ConversationQualityStore


class _ProbeAdapter(ChannelAdapter):
    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send_message(self, chat_id, content, message_type="text", **kwargs):
        return "msg-probe"


def test_capability_defaults_to_unsupported():
    """默认能力位 False：没有原生事件的渠道标 unsupported，不伪造事件。"""
    adapter = _ProbeAdapter(ChannelConfig(channel_type="probe"))
    assert adapter.humanTakeoverEvents is False
    assert asyncio.run(adapter.health_check())["human_takeover_events"] is False

    manager = ChannelManager.get_instance()
    manager.register_adapter(adapter)
    try:
        assert manager.list_adapters()["probe"]["human_takeover_events"] is False
    finally:
        manager.unregister_adapter("probe")


def test_mqtt_declares_and_parses_explicit_takeover_event():
    """MQTT 是已接线的通用渠道：协议显式事件 → 渠道事件，不从文本推断。"""
    from types import SimpleNamespace

    from neurova.channels.mqtt import MQTTAdapter

    adapter = MQTTAdapter()
    assert adapter.humanTakeoverEvents is True
    raw = SimpleNamespace(topic="ops/up", qos=0, retain=False)

    paused = adapter._parse_takeover_event(
        raw,
        '{"event_type": "human_takeover_started", "chat_id": "c-1",'
        ' "operator_id": "op-1", "reason": "customer_request"}',
    )
    assert paused is not None
    event_type, message = paused
    assert event_type == ChannelEventType.HUMAN_TAKEOVER_STARTED
    assert message.chat_id == "c-1"
    assert message.sender_id == "op-1"
    assert message.metadata["takeover_reason"] == "customer_request"

    assert adapter._parse_takeover_event(raw, '{"content": "普通消息"}') is None

    manager = ChannelManager.get_instance()
    manager.register_adapter(adapter)
    try:
        assert manager.list_adapters()["mqtt"]["human_takeover_events"] is True
    finally:
        manager.unregister_adapter("mqtt")


def test_channel_takeover_event_reaches_quality_store(tmp_path, monkeypatch):
    store = ConversationQualityStore(str(tmp_path / "quality.db"))
    monkeypatch.setattr("neurova.quality.get_quality_store", lambda: store)
    manager = ChannelManager.get_instance()
    message = ChannelMessage(
        channel_type="feishu", message_id="msg-1", sender_id="human-op",
        sender_name="operator", content="", chat_id="chat-1",
        timestamp=datetime.now(timezone.utc),
        metadata={"agent_id": "default", "takeover_reason": "customer_request"},
    )

    asyncio.run(manager._on_channel_event(
        ChannelEventType.HUMAN_TAKEOVER_STARTED, message
    ))
    metrics = store.metrics()
    store.close()

    assert metrics["takeover_events"] == 1
    assert metrics["takeover_sources"] == {"channel_event": 1}
    assert metrics["coverage"]["channel_event"] == 1
