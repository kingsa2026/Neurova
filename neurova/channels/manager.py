from __future__ import annotations

"""
渠道管理器

管理所有渠道适配器的生命周期、消息路由和健康监控。

深度模块:
- 小接口: start / stop / get_adapter / list_adapters
- 深实现: 适配器注册、连接管理、消息分发、健康检查
"""

import asyncio
from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelEventType,
    ChannelMessage,
)

logger = get_logger(__name__)

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
            logger.debug("SessionSyncManager not available: %s", e)
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
        # C-24: 构造期直接建表——原惰性 hasattr 建表存在竞态（并发 add 时
        # 两个线程都可能通过 hasattr 检查并各自重建列表）
        self._message_handlers: List[tuple] = []
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
            logger.warning("Replacing existing adapter for %s", channel_type)
        adapter.set_event_callback(self._on_channel_event)
        self._adapters[channel_type] = adapter
        logger.info("Registered adapter: %s", channel_type)

    def unregister_adapter(self, channel_type: str) -> bool:
        """注销渠道适配器"""
        if channel_type in self._adapters:
            del self._adapters[channel_type]
            logger.info("Unregistered adapter: %s", channel_type)
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
        """设置消息处理函数 - 收到消息后调用此函数

        注意: 此方法会覆盖之前的处理器。如果需要多个处理器，请使用 add_message_handler。
        """
        self._message_handler = handler

    def add_message_handler(self, handler: MessageHandler, priority: int = 0) -> int:
        """添加消息处理函数（支持多个处理器）

        Args:
            handler: 消息处理函数
            priority: 优先级（数字越小优先级越高）

        Returns:
            处理器ID（用于后续移除）
        """
        handler_id = len(self._message_handlers)
        self._message_handlers.append((priority, handler_id, handler))
        # 按优先级排序
        self._message_handlers.sort(key=lambda x: x[0])
        logger.info("Added message handler with priority %s, id=%s", priority, handler_id)
        return handler_id

    def remove_message_handler(self, handler_id: int) -> bool:
        """移除消息处理函数"""
        for i, (priority, hid, handler) in enumerate(self._message_handlers):
            if hid == handler_id:
                del self._message_handlers[i]
                logger.info("Removed message handler id=%s", handler_id)
                return True
        return False

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
            logger.error("No adapter for channel: %s", channel_type)
            return None
        if not adapter.is_connected:
            logger.warning("Adapter %s not connected, attempting connect", channel_type)
            if not await adapter.connect():
                logger.error("Failed to connect adapter: %s", channel_type)
                return None

        result = await adapter.send_message(chat_id, content, message_type, **kwargs)

        # 广播回复到 SessionSyncManager
        await self._sync_reply_to_session(chat_id, content, channel_type)

        return result

    async def _sync_reply_to_session(self, chat_id: str, content: str, channel_type: str):
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
                },
            )

            # 广播到其他渠道
            await sync_manager.broadcast_event(session.session_id, event, exclude_channel=channel_type)

        except Exception as e:
            logger.debug("SessionSyncManager reply sync failed: %s", e)

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
                    logger.exception("Broadcast to %s failed: %s", channel_type, e)
                    results[channel_type] = None
        return results

    async def _on_channel_event(self, event_type: ChannelEventType, message: ChannelMessage):
        """处理渠道事件"""
        logger.info("Channel event: %s from %s " f"sender=%s", event_type.value, message.channel_type, message.sender_name)

        # 广播到 SessionSyncManager
        await self._sync_to_session_sync(event_type, message)

        if event_type == ChannelEventType.MESSAGE_RECEIVED:
            # P1-12 语音预检: 语音消息先转写再进 handler 链（@提及/关键词
            # 判定拿真实文本；失败降级占位，绝不阻断）
            try:
                from neurova.channels.voice_precheck import transcribe_voice_message

                message = await transcribe_voice_message(message)
            except Exception as e:  # noqa: BLE001 - 预检故障不影响消息分发
                logger.debug("语音预检跳过: %s", e)

            # P0-5 入站持久化队列（OpenClaw 启发）：先持久化再分发，重启不
            # 丢消息。enqueue 成功 → 立即同步排水该消息（await，时序与旧
            # 直发路径一致，分发结果经 ack/nack 落账）；队列不可用（DB 故障）
            # → fail-open 旧直发路径。重启遗留消息由 start_drain 后台兜底。
            # C-07: enqueue 返回 False 仅表示"重复消息去重"，直接丢弃；
            # DB 故障抛 IngressQueueUnavailable 才 fail-open 直发——
            # 否则平台重发的消息会被去重后再次直发（双投递）。
            queue = self._get_ingress_queue()
            if queue is not None:
                from neurova.channels.channel_ingress_queue import IngressQueueUnavailable

                try:
                    enqueued = queue.enqueue(message)
                except IngressQueueUnavailable as e:
                    logger.warning("Ingress queue unavailable, fail-open to direct dispatch: %s", e)
                else:
                    if not enqueued:
                        return  # 重复消息（tombstone 去重），不再直发
                    ev = queue.claim(worker="inline")
                    if ev is not None:
                        try:
                            await self._dispatch_message(ev.message)
                        except Exception as e:  # noqa: BLE001 - 分发失败 nack 重试
                            queue.nack(ev.event_id, str(e))
                        else:
                            queue.ack(ev.event_id)
                    return

            await self._dispatch_message(message)

    def _get_ingress_queue(self):
        """惰性创建入站持久化队列（DB 打开失败返回 None，fail-open 直发）。

        测试可通过 manager.ingress_queue = ChannelIngressQueue(tmp) 注入，
        或置 False 强制直发路径。
        """
        injected = getattr(self, "ingress_queue", None)
        if injected is False:
            return None
        if injected is not None:
            return injected
        if getattr(self, "_ingress_queue_failed", False):
            return None
        try:
            from neurova.channels.channel_ingress_queue import ChannelIngressQueue

            import os

            db_path = os.environ.get("NEUROVA_CHANNEL_INGRESS_DB") or Path("data/channel_ingress.db")
            queue = ChannelIngressQueue(db_path=db_path)
            self.ingress_queue = queue
            return queue
        except Exception as e:
            logger.warning("Ingress queue unavailable, fail-open to direct dispatch: %s", e)
            self._ingress_queue_failed = True
            return None

    async def _dispatch_message(self, message: ChannelMessage):
        """把一条渠道消息送进处理器链（原 _on_channel_event 分发体）。"""
        # 优先使用多处理器链
        # C-24: 快照遍历——处理器在回调中增删列表时不再被并发修改影响
        if self._message_handlers:
            for priority, handler_id, handler in list(self._message_handlers):
                try:
                    reply = await handler(message)
                    if reply:
                        await self.send_message(
                            message.channel_type,
                            message.chat_id,
                            reply,
                        )
                        break  # 第一个返回回复的处理器获胜
                except Exception as e:
                    logger.exception("Message handler %s error: %s", handler_id, e)
        # 回退到单处理器模式
        elif self._message_handler:
            try:
                reply = await self._message_handler(message)
                if reply:
                    await self.send_message(
                        message.channel_type,
                        message.chat_id,
                        reply,
                    )
            except Exception as e:
                logger.exception("Message handler error: %s", e)
                # 尝试发送错误提示
                try:
                    await self.send_message(
                        message.channel_type,
                        message.chat_id,
                        "抱歉，处理消息时出现错误，请稍后重试。",
                    )
                except Exception:
                    pass

    async def _sync_to_session_sync(self, event_type: ChannelEventType, message: ChannelMessage):
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

            # 获取或创建会话（B4-b：群聊隔离键——share_session_in_group=False
            # 时按 sender 隔离，否则群共享）
            scope_id = self.resolve_session_scope_id(message)
            session = sync_manager.get_session_by_external_id(scope_id)
            if not session:
                # 尝试从元数据获取 user_id
                user_id = getattr(message, "sender_id", None) or "anonymous"
                agent_id = "default"
                session = sync_manager.create_session(
                    user_id=user_id,
                    agent_id=agent_id,
                    external_id=scope_id,
                    metadata={"channel_type": message.channel_type},
                )

            # 创建事件
            event = SessionEvent(
                event_type=mapped_type,
                session_id=session.session_id,
                source_channel=message.channel_type,
                payload={
                    "content": message.content,
                    "sender_name": message.sender_name,
                    "sender_id": getattr(message, "sender_id", None),
                    "metadata": message.metadata,
                },
            )

            # 广播到其他渠道
            await sync_manager.broadcast_event(session.session_id, event, exclude_channel=message.channel_type)

        except Exception as e:
            logger.debug("SessionSyncManager sync failed: %s", e)

    # ============================================================
    # 生命周期
    # ============================================================

    async def start(self):
        """启动所有已启用的适配器"""
        if self._running:
            logger.warning("ChannelManager already running")
            return

        self._running = True
        # P0-5：启动入站持久化队列排水（含重启恢复：遗留 pending/processing
        # 重新入列消费）。handler 为既有分发链；队列不可用时 start_drain 为空操作。
        queue = self._get_ingress_queue()
        if queue is not None:
            queue.start_drain(self._dispatch_message, poll_interval=0.5)

        tasks = []
        for channel_type, adapter in self._adapters.items():
            if adapter.config.enabled:
                tasks.append(self._connect_adapter(adapter))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for i, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error("Connect error: %s", result)

        logger.info("ChannelManager started with %s adapters", len(self._adapters))

    async def stop(self):
        """停止所有适配器"""
        self._running = False
        # P0-5：先停排水循环再断适配器（在途消息 nack 回列，重启续投）
        # C-06: _get_ingress_queue() 把实例存到 self.ingress_queue（无下划线），
        # 此处此前读 _ingress_queue 恒 None → 排水任务永不停止、持续持有 DB 连接
        queue = getattr(self, "ingress_queue", None)
        if queue is not None:
            try:
                await queue.stop_drain()
            except Exception as e:  # noqa: BLE001 - 停机不因队列失败中断
                logger.debug("Ingress drain stop skipped: %s", e)
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
                logger.info("Adapter %s connected", adapter.channel_type)
            else:
                logger.warning("Adapter %s failed to connect", adapter.channel_type)
        except Exception as e:
            logger.exception("Adapter %s connect error: %s", adapter.channel_type, e)

    # ============================================================
    # B4-a 渠道管理能力面（QP config.py/manager.py 对齐）
    # ============================================================

    async def restart_channel(self, channel_type: str) -> Dict[str, Any]:
        """渠道重启：disconnect → connect（配置变更生效/断线重连语义）。"""
        adapter = self.get_adapter(channel_type)
        if adapter is None:
            return {"success": False, "channel_type": channel_type, "error": "渠道未注册"}
        try:
            await adapter.disconnect()
        except Exception as e:  # noqa: BLE001 — 断开失败继续尝试重连
            logger.warning("restart %s disconnect 异常（继续重连）: %s", channel_type, e)
        try:
            ok = await adapter.connect()
            return {"success": bool(ok), "channel_type": channel_type}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "channel_type": channel_type, "error": str(e)}

    async def replace_channel(
        self, channel_type: str, adapter_factory: "Callable[[], ChannelAdapter]",
    ) -> Dict[str, Any]:
        """替换渠道适配器实例（配置热更新：旧实例断开注销，新实例注册并连接）。"""
        old = self.get_adapter(channel_type)
        if old is not None:
            try:
                await old.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.unregister_adapter(channel_type)
        adapter = adapter_factory()
        self.register_adapter(adapter)
        try:
            ok = await adapter.connect()
            return {"success": bool(ok), "channel_type": channel_type}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "channel_type": channel_type, "error": str(e)}

    def clear_channel_queue(self, channel_type: str) -> int:
        """清空渠道待处理入站队列，返回清除条数（队列不可用抛 IngressQueueUnavailable）。"""
        queue = self._get_ingress_queue()
        return queue.clear(channel_type)

    def conflict_check(self) -> Dict[str, Any]:
        """机器人身份冲突检测（QP config.py:379 对齐）。

        两个渠道复用同一身份凭据（app_id/api_key 相同）时，平台的回调/事件
        会串渠道。按身份指纹分组，返回出现 ≥2 次的冲突项。
        """
        groups: Dict[str, List[str]] = {}
        for channel_type, adapter in self._adapters.items():
            cfg = getattr(adapter, "config", None)
            app_id = str(getattr(cfg, "app_id", "") or "")
            api_key = str(getattr(cfg, "api_key", "") or "")
            identity = app_id or api_key
            if not identity:
                continue
            groups.setdefault(identity, []).append(channel_type)
        conflicts = [
            {"identity": identity, "channels": chans}
            for identity, chans in groups.items()
            if len(chans) >= 2
        ]
        return {"conflicts": conflicts, "checked": len(groups)}

    # ============================================================
    # B4-b 群聊会话隔离（#7208/#7001 对齐）
    # ============================================================

    @staticmethod
    def _coerce_share_flag(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in ("false", "0", "no", "off")
        return bool(value)

    def resolve_session_scope_id(self, message: ChannelMessage) -> str:
        """群聊会话隔离键（单点裁决，供会话同步/处理器共用）。

        share_session_in_group=True（默认）→ chat_id（群内共享一个会话）；
        False → ``chat_id:sender_id``（按发送者隔离，QwenPaw 隔离模式语义）。
        配置取适配器的 share_session_in_group 属性（bool/"true"/"false"），
        未声明的适配器默认共享——与既有行为等价，只提升不下降。
        """
        scope = message.chat_id
        adapter = self.get_adapter(message.channel_type)
        if adapter is not None:
            share = getattr(adapter, "share_session_in_group", True)
            if not self._coerce_share_flag(share) and message.sender_id:
                scope = f"{message.chat_id}:{message.sender_id}"
        return scope

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
