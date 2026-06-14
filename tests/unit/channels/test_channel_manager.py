"""
ChannelManager 单元测试
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

try:
    from neurova.channels.manager import ChannelManager
    from neurova.channels.base import ChannelAdapter, ChannelConfig, MessageChannel
    HAS_CHANNEL_MANAGER = True
except ImportError:
    HAS_CHANNEL_MANAGER = False


class MockAdapter(ChannelAdapter):
    """测试用 Mock 适配器"""

    def __init__(self, channel_type: str = "test_channel", enabled: bool = True):
        config = ChannelConfig(channel_type=channel_type, enabled=enabled)
        super().__init__(config)
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self):
        self._connected = False

    async def send_message(self, chat_id: str, content: str, message_type: str = "text", **kwargs) -> str:
        return f"msg_{channel_type}"


@unittest.skipIf(not HAS_CHANNEL_MANAGER, "ChannelManager not available")
class TestChannelManager(unittest.TestCase):
    """ChannelManager 测试类"""

    def setUp(self) -> None:
        """测试前初始化"""
        ChannelManager._instance = None
        self.manager = ChannelManager()

    def tearDown(self) -> None:
        """测试后清理"""
        ChannelManager._instance = None

    def test_add_channel(self) -> None:
        """测试添加渠道适配器"""
        adapter = MockAdapter(channel_type="wechat", enabled=True)
        self.manager.register_adapter(adapter)

        retrieved = self.manager.get_adapter("wechat")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.channel_type, "wechat")

    def test_remove_channel(self) -> None:
        """测试移除渠道适配器"""
        adapter = MockAdapter(channel_type="wechat", enabled=True)
        self.manager.register_adapter(adapter)

        self.assertTrue(self.manager.unregister_adapter("wechat"))
        self.assertIsNone(self.manager.get_adapter("wechat"))

    def test_list_channels(self) -> None:
        """测试列出渠道适配器"""
        self.manager.register_adapter(MockAdapter(channel_type="wechat"))
        self.manager.register_adapter(MockAdapter(channel_type="feishu"))
        self.manager.register_adapter(MockAdapter(channel_type="telegram"))

        channels = self.manager.list_adapters()
        self.assertEqual(len(channels), 3)
        self.assertIn("wechat", channels)
        self.assertIn("feishu", channels)
        self.assertIn("telegram", channels)

    def test_update_channel_config(self) -> None:
        """测试更新渠道配置"""
        adapter = MockAdapter(channel_type="wechat", enabled=True)
        self.manager.register_adapter(adapter)

        self.manager.get_adapter("wechat").update_config({"app_id": "new_app_id"})

        updated = self.manager.get_adapter("wechat")
        self.assertEqual(updated.config.app_id, "new_app_id")

    def test_enable_disable_channel(self) -> None:
        """测试启用/禁用渠道"""
        adapter = MockAdapter(channel_type="wechat", enabled=True)
        self.manager.register_adapter(adapter)

        cfg = self.manager.get_adapter("wechat")
        self.assertTrue(cfg.config.enabled)

        cfg.config.enabled = False
        disabled = self.manager.get_adapter("wechat")
        self.assertFalse(disabled.config.enabled)

        cfg.config.enabled = True
        enabled = self.manager.get_adapter("wechat")
        self.assertTrue(enabled.config.enabled)

    def test_get_channel_status(self) -> None:
        """测试获取渠道状态"""
        adapter = MockAdapter(channel_type="wechat", enabled=True)
        self.manager.register_adapter(adapter)

        status = self.manager.list_adapters()
        self.assertIn("wechat", status)
        self.assertIn("connected", status["wechat"])
        self.assertIn("enabled", status["wechat"])

    def test_get_nonexistent_channel(self) -> None:
        """测试获取不存在的渠道"""
        cfg = self.manager.get_adapter("nonexistent")
        self.assertIsNone(cfg)

    def test_remove_nonexistent_channel(self) -> None:
        """测试移除不存在的渠道"""
        self.assertFalse(self.manager.unregister_adapter("nonexistent"))

    def test_get_nonexistent_channel_status(self) -> None:
        """测试获取不存在渠道的状态"""
        status = self.manager.list_adapters()
        self.assertNotIn("nonexistent", status)

    def test_channel_priority(self) -> None:
        """测试渠道优先级排序 - 通过 extra 字段"""
        adapter1 = MockAdapter(channel_type="wechat")
        adapter1.config.extra["priority"] = 10
        adapter2 = MockAdapter(channel_type="feishu")
        adapter2.config.extra["priority"] = 5

        self.manager.register_adapter(adapter1)
        self.manager.register_adapter(adapter2)

        channels = self.manager.list_adapters()
        self.assertIn("wechat", channels)
        self.assertIn("feishu", channels)

    def test_get_preferred_channel(self) -> None:
        """测试获取首选渠道 - 通过 adapter 获取"""
        adapter_high = MockAdapter(channel_type="feishu")
        adapter_high.config.extra["priority"] = 10
        adapter_low = MockAdapter(channel_type="wechat")
        adapter_low.config.extra["priority"] = 1

        self.manager.register_adapter(adapter_high)
        self.manager.register_adapter(adapter_low)

        preferred = self.manager.get_adapter("feishu")
        self.assertIsNotNone(preferred)
        self.assertEqual(preferred.channel_type, "feishu")


if __name__ == "__main__":
    unittest.main()
