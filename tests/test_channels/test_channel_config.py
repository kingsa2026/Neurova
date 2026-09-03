"""
渠道配置测试

测试目标：neurova/channels 中导出的真实实现（来自 neurova/channels/base.py）。

说明：
- 包导出的 ChannelConfig / UserIdentity / MessageChannel 均来自 base.py，
  而非 channels/models.py（models.py 为另一份独立定义，未被包导出）。
- 原测试针对更丰富的旧版 ChannelConfig（priority / health_status / bot_name /
  max_message_length / rate_limit 等字段），与 base.py 精简版不符。
  此处对齐到真实实现（与 router / api_router / mem_core 的修复原则一致）。
"""

import pytest

from neurova.channels import ChannelConfig, MessageChannel, UserIdentity


class TestChannelConfig:
    """渠道配置（base.py 实现：channel_type: str + 各平台凭证）"""

    def test_default_config(self):
        config = ChannelConfig(channel_type="feishu")
        assert config.channel_type == "feishu"
        assert config.enabled is True
        assert config.app_id == ""
        assert config.app_secret == ""
        assert config.webhook_url == ""
        assert config.use_stream is True
        assert config.extra == {}

    def test_disabled_channel(self):
        config = ChannelConfig(channel_type="dingtalk", enabled=False)
        assert config.enabled is False

    def test_credentials(self):
        config = ChannelConfig(
            channel_type="wecom",
            app_id="app_123",
            app_secret="sec_456",
            webhook_url="https://example.com/hook",
        )
        assert config.app_id == "app_123"
        assert config.app_secret == "sec_456"
        assert config.webhook_url == "https://example.com/hook"

    def test_extra(self):
        config = ChannelConfig(channel_type="feishu", extra={"foo": "bar"})
        assert config.extra == {"foo": "bar"}

    def test_to_dict(self):
        config = ChannelConfig(channel_type="feishu")
        d = config.to_dict()
        assert isinstance(d, dict)
        assert d["channel_type"] == "feishu"


class TestUserIdentity:
    """用户身份（base.py 实现）"""

    def test_minimal_identity(self):
        identity = UserIdentity(
            user_id="u1",
            channel=MessageChannel.WEBHOOK,
            channel_user_id="wx_001",
        )
        assert identity.user_id == "u1"
        assert identity.channel_user_id == "wx_001"
        assert identity.display_name is None
        assert identity.created_at is not None

    def test_with_display_name(self):
        identity = UserIdentity(
            user_id="u1",
            channel=MessageChannel.FEISHU,
            channel_user_id="fs_001",
            display_name="张三",
        )
        assert identity.display_name == "张三"
        assert identity.channel_user_id == "fs_001"
