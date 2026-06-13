"""
ChannelRegistry — 通道注册表

管理所有检索通道的生命周期：注册/注销/查询/枚举，线程安全。
"""

import logging
import threading
from typing import Dict, List, Optional

from .base import BaseChannel, ChannelMetadata, ChannelState

logger = logging.getLogger(__name__)


class ChannelRegistry:
    """通道注册表（单例）"""

    _instance: Optional["ChannelRegistry"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "ChannelRegistry":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._channels: Dict[str, BaseChannel] = {}
                    cls._instance._metadata: Dict[str, ChannelMetadata] = {}
        return cls._instance

    def register(self, channel: BaseChannel) -> bool:
        name = channel.metadata.name
        if name in self._channels:
            logger.warning("通道 %s 已存在，将被覆盖", name)
        self._channels[name] = channel
        self._metadata[name] = channel.metadata
        logger.info("注册通道: %s", name)
        return True

    def unregister(self, name: str) -> bool:
        if name not in self._channels:
            logger.warning("通道 %s 不存在", name)
            return False
        channel = self._channels[name]
        if channel.get_state() == ChannelState.ACTIVE:
            logger.warning("通道 %s 仍处于活跃状态，建议先关闭", name)
        del self._channels[name]
        del self._metadata[name]
        logger.info("注销通道: %s", name)
        return True

    def get(self, name: str) -> Optional[BaseChannel]:
        return self._channels.get(name)

    def get_all(self) -> List[BaseChannel]:
        return list(self._channels.values())

    def get_active(self) -> List[BaseChannel]:
        return [ch for ch in self._channels.values() if ch.get_state() == ChannelState.ACTIVE]

    def get_by_capability(self, capability: str) -> List[BaseChannel]:
        return [ch for ch in self._channels.values() if capability in ch.metadata.capabilities]

    def get_metadata(self, name: str) -> Optional[ChannelMetadata]:
        return self._metadata.get(name)

    def get_all_metadata(self) -> Dict[str, ChannelMetadata]:
        return self._metadata.copy()

    async def initialize_all(self) -> Dict[str, bool]:
        results = {}
        for name, channel in self._channels.items():
            try:
                success = await channel.initialize()
                results[name] = success
            except Exception as e:
                logger.error("初始化通道 %s 失败: %s", name, e)
                results[name] = False
        return results

    async def shutdown_all(self) -> None:
        for name, channel in self._channels.items():
            try:
                await channel.shutdown()
            except Exception as e:
                logger.error("关闭通道 %s 失败: %s", name, e)


def get_channel_registry() -> ChannelRegistry:
    """获取通道注册表单例"""
    return ChannelRegistry()
