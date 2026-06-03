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
    MessageChannel,
)
from neurova.channels.manager import ChannelManager, get_channel_manager
from neurova.channels.xiaoyi import XiaoYiAdapter, create_xiaoyi_adapter
from neurova.session_manager import SessionManager, SessionMessage, SessionRecord, get_session_manager

__all__ = [
    "ChannelAdapter",
    "ChannelConfig",
    "ChannelMessage",
    "ChannelEventType",
    "MessageChannel",
    "ChannelManager",
    "get_channel_manager",
    "XiaoYiAdapter",
    "create_xiaoyi_adapter",
    "SessionManager",
    "SessionMessage",
    "SessionRecord",
    "get_session_manager",
]
