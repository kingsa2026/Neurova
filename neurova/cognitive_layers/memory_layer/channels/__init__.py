"""记忆检索通道插件化基础设施"""

from .base import BaseChannel, ChannelMetadata, ChannelResult, ChannelState
from .registry import ChannelRegistry, get_channel_registry

__all__ = [
    "BaseChannel",
    "ChannelMetadata",
    "ChannelResult",
    "ChannelState",
    "ChannelRegistry",
    "get_channel_registry",
]
