"""
BaseChannel 统一接口测试

TDD: 先写测试，再实现
"""

import pytest
from abc import ABC
from neurova.channels.base import ChannelAdapter, ChannelConfig, ChannelMessage, MessageChannel


class TestBaseChannelInterface:
    """测试BaseChannel统一接口"""

    def test_channel_adapter_is_abstract(self):
        """ChannelAdapter应该是抽象类"""
        assert issubclass(ChannelAdapter, ABC)

    def test_channel_adapter_requires_config(self):
        """ChannelAdapter应该接受ChannelConfig参数"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        assert adapter.config.channel_type == "test"

    def test_channel_adapter_has_channel_type_property(self):
        """ChannelAdapter应该有channel_type属性"""
        config = ChannelConfig(channel_type="wechat")
        adapter = ConcreteTestChannel(config)
        assert adapter.channel_type == "wechat"

    def test_channel_adapter_has_is_connected_property(self):
        """ChannelAdapter应该有is_connected属性"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        assert adapter.is_connected is False

    def test_channel_adapter_has_set_event_callback(self):
        """ChannelAdapter应该有set_event_callback方法"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)

        callback = lambda event_type, message: None
        adapter.set_event_callback(callback)
        assert adapter._event_callback is callback

    def test_channel_adapter_has_health_check(self):
        """ChannelAdapter应该有health_check方法"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        import asyncio
        result = asyncio.run(adapter.health_check())
        assert "channel_type" in result
        assert "connected" in result
        assert result["channel_type"] == "test"

    def test_cannot_instantiate_abstract(self):
        """不能直接实例化ChannelAdapter"""
        config = ChannelConfig(channel_type="test")
        with pytest.raises(TypeError):
            ChannelAdapter(config)

    def test_config_stores_channel_type(self):
        """ChannelConfig应该存储channel_type"""
        config = ChannelConfig(channel_type="telegram")
        assert config.channel_type == "telegram"

    def test_message_channel_enum(self):
        """MessageChannel应该有标准值"""
        assert hasattr(MessageChannel, "WECHAT")
        assert hasattr(MessageChannel, "TELEGRAM")
        assert hasattr(MessageChannel, "DISCORD")

    def test_channel_message_creation(self):
        """ChannelMessage应该可以创建"""
        msg = ChannelMessage(
            channel_type="test",
            message_id="123",
            chat_id="chat1",
            content="hello",
            sender_id="user1",
            sender_name="TestUser",
        )
        assert msg.message_id == "123"
        assert msg.content == "hello"


class TestConcreteChannelConformance:
    """测试具体Channel实现是否符合接口契约"""

    def test_concrete_channel_connect(self):
        """具体Channel应该能connect"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        import asyncio
        result = asyncio.run(adapter.connect())
        assert result is True
        assert adapter.is_connected is True

    def test_concrete_channel_disconnect(self):
        """具体Channel应该能disconnect"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        import asyncio
        asyncio.run(adapter.connect())
        asyncio.run(adapter.disconnect())
        assert adapter.is_connected is False

    def test_concrete_channel_send_message(self):
        """具体Channel应该能send_message"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        import asyncio
        asyncio.run(adapter.connect())
        msg_id = asyncio.run(adapter.send_message("chat1", "hello", "text"))
        assert msg_id is not None

    def test_channel_unified_config_interface(self):
        """所有Channel应该有get_channel_config方法"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        cfg = adapter.get_channel_config()
        assert isinstance(cfg, dict)
        assert "channel_type" in cfg

    def test_channel_update_config(self):
        """Channel应该支持update_config"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        adapter.update_config({"enabled": False})
        assert adapter.get_channel_config().get("enabled") is False

    def test_channel_update_config_extra(self):
        """update_config应该支持extra字段"""
        config = ChannelConfig(channel_type="test")
        adapter = ConcreteTestChannel(config)
        adapter.update_config({"show_tool_messages": True})
        assert adapter.get_channel_config().get("extra", {}).get("show_tool_messages") is True


# Helper: Concrete implementation for testing
import asyncio


class ConcreteTestChannel(ChannelAdapter):
    """用于测试的具体Channel实现"""

    def __init__(self, config: ChannelConfig):
        super().__init__(config)
        self._show_tool_messages = False
        self._show_thinking = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    async def send_message(
        self, chat_id: str, content: str, message_type: str = "text", **kwargs
    ) -> str:
        return f"msg_{chat_id}_{asyncio.get_event_loop().time()}"
