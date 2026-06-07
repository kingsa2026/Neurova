from __future__ import annotations

"""
渠道管理器

管理所有渠道适配器的生命周期、消息路由和健康监控。

深度模块:
- 小接口: start / stop / get_adapter / list_adapters
- 深实现: 适配器注册、连接管理、消息分发、健康检查
"""

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

# 延迟导入 SessionSyncManager 避免循环导入
_session_sync_manager = None


def _get_session_sync_manager():
    """获取 SessionSyncManager 单例（延迟导入）"""
    global _session_sync_manager
    if _session_sync_manager is None:
        try:
            from neurova.sync.session_sync_manager import get_session_sync_manager
            _session_sync_manager = get_session_sync_manager()
        except Exception as e:
            logger.debug(f"SessionSyncManager not available: {e}")
    return _session_sync_manager

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
        
        result = await adapter.send_message(chat_id, content, message_type, **kwargs)
        
        # 广播回复到 SessionSyncManager
        await self._sync_reply_to_session(chat_id, content, channel_type)
        
        return result

    async def _sync_reply_to_session(
        self, chat_id: str, content: str, channel_type: str
    ):
        """同步回复消息到 SessionSyncManager"""
        sync_manager = _get_session_sync_manager()
        if not sync_manager:
            return

        try:
            from neurova.sync.session_sync_manager import EventType, SessionEvent

            # 查找会话
            session = sync_manager.get_session_by_external_id(chat_id)
            if not session:
                return

            # 创建回复事件
            event = SessionEvent(
                event_type=EventType.AGENT_REPLY,
                session_id=session.session_id,
                source_channel=channel_type,
                payload={
                    "content": content,
                    "reply_to": chat_id,
                }
            )

            # 广播到其他渠道
            await sync_manager.broadcast_event(
                session.session_id,
                event,
                exclude_channel=channel_type
            )

        except Exception as e:
            logger.debug(f"SessionSyncManager reply sync failed: {e}")

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

        # 广播到 SessionSyncManager
        await self._sync_to_session_sync(event_type, message)

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

    async def _sync_to_session_sync(
        self, event_type: ChannelEventType, message: ChannelMessage
    ):
        """同步事件到 SessionSyncManager"""
        sync_manager = _get_session_sync_manager()
        if not sync_manager:
            return

        try:
            from neurova.sync.session_sync_manager import EventType, SessionEvent

            # 映射事件类型
            event_type_map = {
                ChannelEventType.MESSAGE_RECEIVED: EventType.USER_MESSAGE,
                ChannelEventType.BOT_CONNECTED: EventType.CHANNEL_CONNECTED,
                ChannelEventType.BOT_DISCONNECTED: EventType.CHANNEL_DISCONNECTED,
            }

            mapped_type = event_type_map.get(event_type)
            if not mapped_type:
                return

            # 获取或创建会话
            session = sync_manager.get_session_by_external_id(message.chat_id)
            if not session:
                # 尝试从元数据获取 user_id
                user_id = getattr(message, 'sender_id', None) or "anonymous"
                agent_id = "default"
                session = sync_manager.create_session(
                    user_id=user_id,
                    agent_id=agent_id,
                    external_id=message.chat_id,
                    metadata={"channel_type": message.channel_type}
                )

            # 创建事件
            event = SessionEvent(
                event_type=mapped_type,
                session_id=session.session_id,
                source_channel=message.channel_type,
                payload={
                    "content": message.content,
                    "sender_name": message.sender_name,
                    "sender_id": getattr(message, 'sender_id', None),
                    "metadata": message.metadata,
                }
            )

            # 广播到其他渠道
            await sync_manager.broadcast_event(
                session.session_id,
                event,
                exclude_channel=message.channel_type
            )

        except Exception as e:
            logger.debug(f"SessionSyncManager sync failed: {e}")

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
