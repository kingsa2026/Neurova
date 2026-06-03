"""
渠道管理器

管理所有渠道适配器的生命周期、消息路由和健康监控。

深度模块:
- 小接口: start / stop / get_adapter / list_adapters
- 深实现: 适配器注册、连接管理、消息分发、健康检查
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelConfig,
    ChannelEventCallback,
    ChannelEventType,
    ChannelMessage,
)

logger = logging.getLogger(__name__)


# ============================================================
# 消息处理器类型
# ============================================================

MessageHandler = Callable[[ChannelMessage], Coroutine[Any, Any, str]]


class ChannelManager:
    """
    渠道管理器

    职责:
    1. 注册/注销渠道适配器
    2. 管理适配器连接生命周期
    3. 将收到的消息分发给消息处理器
    4. 提供健康检查和状态查询

    用法:
        manager = ChannelManager()
        manager.register_adapter(feishu_adapter)
        manager.set_message_handler(my_handler)
        await manager.start()
    """

    _instance: Optional["ChannelManager"] = None

    def __init__(self):
        if ChannelManager._instance is not None:
            raise RuntimeError("Use get_channel_manager() instead of direct construction")
        self._adapters: Dict[str, ChannelAdapter] = {}
        self._message_handler: Optional[MessageHandler] = None
        self._running = False

    @classmethod
    def get_instance(cls) -> "ChannelManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ============================================================
    # 适配器管理
    # ============================================================

    def register_adapter(self, adapter: ChannelAdapter):
        """注册渠道适配器"""
        channel_type = adapter.channel_type
        if channel_type in self._adapters:
            logger.warning(f"Replacing existing adapter for {channel_type}")
        adapter.set_event_callback(self._on_channel_event)
        self._adapters[channel_type] = adapter
        logger.info(f"Registered adapter: {channel_type}")

    def unregister_adapter(self, channel_type: str) -> bool:
        """注销渠道适配器"""
        if channel_type in self._adapters:
            del self._adapters[channel_type]
            logger.info(f"Unregistered adapter: {channel_type}")
            return True
        return False

    def get_adapter(self, channel_type: str) -> Optional[ChannelAdapter]:
        """获取指定渠道的适配器"""
        return self._adapters.get(channel_type)

    def list_adapters(self) -> Dict[str, Dict[str, Any]]:
        """列出所有已注册的适配器状态"""
        result = {}
        for channel_type, adapter in self._adapters.items():
            result[channel_type] = {
                "channel_type": channel_type,
                "connected": adapter.is_connected,
                "enabled": adapter.config.enabled,
            }
        return result

    # ============================================================
    # 消息处理
    # ============================================================

    def set_message_handler(self, handler: MessageHandler):
        """设置消息处理函数 - 收到消息后调用此函数"""
        self._message_handler = handler

    async def send_message(
        self,
        channel_type: str,
        chat_id: str,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Optional[str]:
        """通过指定渠道发送消息"""
        adapter = self._adapters.get(channel_type)
        if not adapter:
            logger.error(f"No adapter for channel: {channel_type}")
            return None
        if not adapter.is_connected:
            logger.warning(f"Adapter {channel_type} not connected, attempting connect")
            if not await adapter.connect():
                logger.error(f"Failed to connect adapter: {channel_type}")
                return None
        return await adapter.send_message(chat_id, content, message_type, **kwargs)

    async def broadcast_message(
        self,
        content: str,
        message_type: str = "text",
        **kwargs,
    ) -> Dict[str, Optional[str]]:
        """向所有已连接的渠道广播消息"""
        results = {}
        for channel_type, adapter in self._adapters.items():
            if adapter.is_connected:
                try:
                    msg_id = await adapter.send_message("", content, message_type, **kwargs)
                    results[channel_type] = msg_id
                except Exception as e:
                    logger.exception(f"Broadcast to {channel_type} failed: {e}")
                    results[channel_type] = None
        return results

    async def _on_channel_event(
        self, event_type: ChannelEventType, message: ChannelMessage
    ):
        """处理渠道事件"""
        logger.info(
            f"Channel event: {event_type.value} from {message.channel_type} "
            f"sender={message.sender_name}"
        )

        if event_type == ChannelEventType.MESSAGE_RECEIVED and self._message_handler:
            try:
                reply = await self._message_handler(message)
                if reply:
                    await self.send_message(
                        message.channel_type,
                        message.chat_id,
                        reply,
                    )
            except Exception as e:
                logger.exception(f"Message handler error: {e}")
                # 尝试发送错误提示
                try:
                    await self.send_message(
                        message.channel_type,
                        message.chat_id,
                        "抱歉，处理消息时出现错误，请稍后重试。",
                    )
                except Exception:
                    pass

    # ============================================================
    # 生命周期
    # ============================================================

    async def start(self):
        """启动所有已启用的适配器"""
        if self._running:
            logger.warning("ChannelManager already running")
            return

        self._running = True
        tasks = []
        for channel_type, adapter in self._adapters.items():
            if adapter.config.enabled:
                tasks.append(self._connect_adapter(adapter))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Connect error: {result}")

        logger.info(f"ChannelManager started with {len(self._adapters)} adapters")

    async def stop(self):
        """停止所有适配器"""
        self._running = False
        tasks = []
        for adapter in self._adapters.values():
            tasks.append(adapter.disconnect())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("ChannelManager stopped")

    async def _connect_adapter(self, adapter: ChannelAdapter):
        """连接单个适配器"""
        try:
            success = await adapter.connect()
            if success:
                logger.info(f"Adapter {adapter.channel_type} connected")
            else:
                logger.warning(f"Adapter {adapter.channel_type} failed to connect")
        except Exception as e:
            logger.exception(f"Adapter {adapter.channel_type} connect error: {e}")

    # ============================================================
    # 健康检查
    # ============================================================

    async def health_check(self) -> Dict[str, Any]:
        """检查所有渠道健康状态"""
        statuses = {}
        for channel_type, adapter in self._adapters.items():
            try:
                status = await adapter.health_check()
                statuses[channel_type] = status
            except Exception as e:
                statuses[channel_type] = {
                    "channel_type": channel_type,
                    "connected": False,
                    "error": str(e),
                }
        return {
            "running": self._running,
            "adapters": statuses,
        }


# ============================================================
# 全局单例
# ============================================================


def get_channel_manager() -> ChannelManager:
    """获取渠道管理器单例"""
    return ChannelManager.get_instance()
