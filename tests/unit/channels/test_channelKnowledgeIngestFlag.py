"""渠道 ingest_to_kb 开关：只注入 metadata，不改聊天主链。"""
import asyncio

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.manager import ChannelManager


class _ProbeAdapter(ChannelAdapter):
    async def connect(self):
        return True

    async def disconnect(self):
        return None

    async def send_message(self, chat_id, content, message_type="text", **kwargs):
        return "m1"


def test_ingest_flag_injected_only_when_configured(monkeypatch):
    manager = ChannelManager.get_instance()
    seen = []

    async def _capture(event_type, message):
        seen.append(dict(message.metadata))

    monkeypatch.setattr(manager, "_on_channel_event", _capture)
    on = _ProbeAdapter(ChannelConfig(
        channel_type="probe-on", extra={"ingest_to_kb": "true"}
    ))
    off = _ProbeAdapter(ChannelConfig(channel_type="probe-off"))
    manager.register_adapter(on, agent_id="default")
    manager.register_adapter(off, agent_id="default")
    try:
        message = ChannelMessage(
            channel_type="probe-on", message_id="m1", sender_id="u1",
            sender_name="u1", content="正文", chat_id="c1",
        )
        asyncio.run(on._event_callback(ChannelEventType.MESSAGE_RECEIVED, message))
        assert seen[-1]["ingest_to_kb"] is True

        off_message = ChannelMessage(
            channel_type="probe-off", message_id="m2", sender_id="u1",
            sender_name="u1", content="正文", chat_id="c1",
        )
        asyncio.run(off._event_callback(ChannelEventType.MESSAGE_RECEIVED, off_message))
        assert "ingest_to_kb" not in seen[-1]
    finally:
        manager.unregister_adapter("probe-on")
        manager.unregister_adapter("probe-off")
