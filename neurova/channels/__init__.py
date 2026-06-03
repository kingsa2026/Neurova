"""
Neurova 渠道集成模块

提供飞书、钉钉、企业微信等第三方平台的机器人接入能力。
支持 Stream 模式（WebSocket 长连接）和 Webhook 模式。

使用方式:
    from neurova.channels import ChannelManager, get_channel_manager

    manager = get_channel_manager()
    manager.start()
"""

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelMessage,
    ChannelEventType,
)
from neurova.channels.manager import ChannelManager, get_channel_manager

__all__ = [
    "ChannelAdapter",
    "ChannelConfig",
    "ChannelMessage",
    "ChannelEventType",
    "ChannelManager",
    "get_channel_manager",
]
