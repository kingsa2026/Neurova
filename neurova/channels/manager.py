from __future__ import annotations

"""
渠道管理器

管理所有渠道适配器的生命周期、消息路由和健康监控。

深度模块:
- 小接口: start / stop / get_adapter / list_adapters
- 深实现: 适配器注册、连接管理、消息分发、健康检查
"""

import asyncio
import threading
from neurova.core.logger import get_logger
from typing import Any, Callable, Coroutine, Dict, List, Optional

from neurova.channels.base import (
    ChannelAdapter,
    ChannelEventType,
    ChannelMessage,
)
from neurova.channels.voice_egress import (
    VOICE_MESSAGE_TYPE,
    VOICE_OUT_NONE,
    VoiceReply,
    resolveVoiceReply,
)
from neurova.core.data_root import callerPath
from neurova.core.lazy_singleton import lazySingleton

logger = get_logger(__name__)


def _adapterViewKey(agentId: str, channelType: str) -> str:
    """渠道实例在对外视图里的键——`list_adapters` 与 `health_check` 共用这一份约定（§6-190）。

    default 保留裸 channel 名（既有前端与脚本按 `"feishu"` 读），其余带 `agent:` 前缀。
    两份视图各写一遍这个约定，就是"同一个口径两个事实源"——加 agent 维度时必然漏掉一处。
    """
    return channelType if agentId == "default" else f"{agentId}:{channelType}"


# 延迟导入 SessionSyncManager 避免循环导入
_session_sync_manager = None


@lazySingleton("_session_sync_manager")
def _get_session_sync_manager():
    """获取 SessionSyncManager 单例（延迟导入；拿不到时返回 None，下次照旧重试）"""
    try:
        from neurova.sync.session_sync_manager import get_session_sync_manager

        return get_session_sync_manager()
    except Exception as e:
        logger.debug("SessionSyncManager not available: %s", e)
        return None


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
    _instanceLock = threading.RLock()
    # 懒建单例的双检锁（AGENTS.md §3）：RLock 允许构造链回落到同一入口
    _instanceLock = threading.RLock()

    def __init__(self):
        if ChannelManager._instance is not None:
            raise RuntimeError("Use get_channel_manager() instead of direct construction")
        self._adapters: Dict[str, ChannelAdapter] = {}
        # agent 多实例全量表
        self._agent_adapters: Dict[tuple, ChannelAdapter] = {}
        self._message_handler: Optional[MessageHandler] = None
        # C-24: 构造期直接建表——原惰性 hasattr 建表存在竞态（并发 add 时
        # 两个线程都可能通过 hasattr 检查并各自重建列表）
        self._message_handlers: List[tuple] = []
        self._running = False

    @classmethod
    def get_instance(cls) -> "ChannelManager":
        if cls._instance is None:
            with cls._instanceLock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ============================================================
    # 适配器管理
    # ============================================================

    def register_adapter(self, adapter: ChannelAdapter, agent_id: str = "default"):
        """注册渠道适配器

        实例即路由：注册时绑定 agent_id 与事件回调，入站消息 metadata 携带来源
 agent。
        `_adapters[type]` 保持 default agent 兼容视图（既有 get_adapter 调用零破坏）；
        `_agent_adapters[(agent_id, type)]` 为全量实例表（跨 agent 多实例）。
        """
        channel_type = adapter.channel_type
        if not hasattr(self, "_agent_adapters"):
            self._agent_adapters: Dict[tuple, ChannelAdapter] = {}
        adapter.agent_id = agent_id
        adapter.set_event_callback(self._make_event_callback(agent_id))
        self._agent_adapters[(agent_id, channel_type)] = adapter
        if agent_id == "default":
            if channel_type in self._adapters:
                logger.warning("Replacing existing adapter for %s", channel_type)
            self._adapters[channel_type] = adapter
        logger.info("Registered adapter: %s (agent=%s)", channel_type, agent_id)

    def _make_event_callback(self, agent_id: str):
        """装配期闭包：事件进入统一处理链前注入来源 agent。"""
        async def _callback(event_type: ChannelEventType, message: ChannelMessage):
            # metadata 随 ingress 队列 JSON 内嵌持久化（channel_ingress_queue:56），
            # agent 上下文可跨重启排水存活；已有值不覆盖（同一消息不串台）
            if "agent_id" not in message.metadata:
                message.metadata["agent_id"] = agent_id
            return await self._on_channel_event(event_type, message)
        return _callback

    def unregister_adapter(self, channel_type: str, agent_id: str = "default") -> bool:
        """注销渠道适配器"""
        found = False
        if hasattr(self, "_agent_adapters") and (agent_id, channel_type) in self._agent_adapters:
            del self._agent_adapters[(agent_id, channel_type)]
            found = True
        if agent_id == "default" and channel_type in self._adapters:
            del self._adapters[channel_type]
            found = True
        if found:
            logger.info("Unregistered adapter: %s (agent=%s)", channel_type, agent_id)
        return found

    def get_adapter(self, channel_type: str, agent_id: str = "default") -> Optional[ChannelAdapter]:
        """获取指定渠道的适配器（默认 agent 视图向后兼容）"""
        if hasattr(self, "_agent_adapters"):
            adapter = self._agent_adapters.get((agent_id, channel_type))
            if adapter is not None:
                return adapter
        if agent_id == "default":
            return self._adapters.get(channel_type)
        return None

    def resolveInboundAdapter(self, channel_type: str, authenticator=None):
        """入站回调的适配器解析——全仓唯一入口（§6-188）。

        实例表主键是 `(agent_id, channel_type)`，而平台回调 URL 只带 `channel_type`。
        **本意是每个 agent 各有专属渠道配置**，所以"这条回调是谁的"不该由 default 说了算——
        三平台的验签面用的都是实例自己的凭据（飞书 verification_token、钉钉 appSecret、
        企微 callback token），回调体自带答案。于是分两态：

        - 给了 `authenticator` 且候选 ≥2 ⇒ **逐只问凭据，恰好一只验过就用它**（default 不插队）；
          0 只 ⇒ 拒并点名"没有一只验下"；≥2 只 ⇒ 拒并点名是哪几只——那不是路由问题，是
          **同一份凭据被两个 agent 共用**（`/conflicts/check` 在报的就是它），静默投给 default
          等于把配置错误掩盖成正常投递。
        - 没给谓词（该类型没有验签面、或回调体读不懂）或候选只有 1 只 ⇒ §6-189 的语义一字不变：
          default 有则用它；否则该类型全表唯一则用那一格；多格歧义则拒并点名涉及哪几个 agent。

        `authenticator(adapter)` 抛异常按**不匹配**处理并记一条告警：入站回调是外部边界，
        一只实例的读法炸了不许把整条分派带进 500（也不许因此放行）。
        返回 `(adapter, failureReason)`：取不到时成对给出原因，别让调用方用 None 猜两种失败。
        """
        table = getattr(self, "_agent_adapters", {}) or {}
        owners = sorted(aid for (aid, ctype) in table if ctype == channel_type)
        candidates = [table[(aid, channel_type)] for aid in owners]
        legacy = self._adapters.get(channel_type)
        if legacy is not None and "default" not in owners:
            owners = sorted(owners + ["default"])
            candidates.append(legacy)
        if not candidates:
            return None, f"Channel '{channel_type}' not found"

        if authenticator is not None and len(candidates) > 1:
            matched = []
            for agentId, candidate in zip(owners, candidates):
                try:
                    verified = bool(authenticator(candidate))
                except Exception as e:  # noqa: BLE001 - 外部回调是边界：一只读法抛错不算它匹配
                    logger.warning("渠道 %s（agent=%s）验签自己的回调时抛错，按不匹配处理：%s",
                                   channel_type, agentId, e)
                    verified = False
                if verified:
                    matched.append(agentId)
            if len(matched) == 1:
                return candidates[owners.index(matched[0])], ""
            if not matched:
                return None, (
                    f"Channel '{channel_type}': none of the registered instances "
                    f"({'、'.join(owners)}) authenticated this callback（凭据都不匹配，歧义不投递）")
            return None, (
                f"Channel '{channel_type}' callback authenticated against multiple agents "
                f"({'、'.join(matched)})——这几只共用了同一份凭据（见 /conflicts/check），歧义不投递")

        if "default" in owners:
            return table.get(("default", channel_type)) or legacy, ""
        if len(owners) == 1:
            return candidates[0], ""
        return None, (
            f"Channel '{channel_type}' is registered under multiple agents ({'、'.join(owners)}); "
            "回调 URL 无法唯一确定适配器（歧义不投递）——请把 agent 维度带进回调地址")

    def list_adapters(self) -> Dict[str, Dict[str, Any]]:
        """列出所有已注册的适配器状态（跨 agent 全量；键约定与 `health_check` 同一份）"""
        result = {}
        table = getattr(self, "_agent_adapters", {}) or {}
        for (agent_id, channel_type), adapter in table.items():
            result[_adapterViewKey(agent_id, channel_type)] = {
                "channel_type": channel_type,
                "agent_id": agent_id,
                "connected": adapter.is_connected,
                "enabled": adapter.config.enabled,
                "human_takeover_events": bool(
                    getattr(adapter, "humanTakeoverEvents", False)
                ),
                "human_takeover_reason": str(
                    getattr(adapter, "humanTakeoverReason", "") or ""
                ),
            }
        # 兼容：仅存在于 _adapters 而无复合键的实例（理论不发生，兜底）
        for channel_type, adapter in self._adapters.items():
            if ("default", channel_type) not in table:
                result[_adapterViewKey("default", channel_type)] = {
                    "channel_type": channel_type,
                    "agent_id": "default",
                    "connected": adapter.is_connected,
                    "enabled": adapter.config.enabled,
                    "human_takeover_events": bool(
                        getattr(adapter, "humanTakeoverEvents", False)
                    ),
                    "human_takeover_reason": str(
                        getattr(adapter, "humanTakeoverReason", "") or ""
                    ),
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
        """通过指定渠道发送消息（长文本按渠道上限分片，失败不静默）

        `agent_id` 两态（§6-195）：**未点名或点名 default**＝沿用 default 兼容视图（`neurflow`
        审批通知那条路不带 agent_id，它要的就是"default 有什么发什么"，语义一字不变）；
        **点名非 default**＝只认那一格，取不到就诚实失败——此前它无条件
        `or self._adapters.get(t)`，于是 §6-190 给 `/send` 加上 `agent_id` 之后，
        `?agent_id=kai` 在 kai 名下没配这条渠道时会**由 default 的 bot 把这条消息发出去**、
        回执还写 success。回落不是兼容，是拿别人的身份说话（§6-189 同一条纪律的出站半边）。
        """
        agent_id = str(kwargs.pop("agent_id", "default") or "default")
        session_scope = kwargs.pop("session_scope", "") or chat_id  # 回复广播按 scope 反查
        adapter = getattr(self, "_agent_adapters", {}).get((agent_id, channel_type))
        if adapter is None and agent_id == "default":
            # 兼容视图：只给 default 那一态用（点名别的 agent 却回落到它，就是错投）
            adapter = self._adapters.get(channel_type)
        if adapter is None:
            logger.error("渠道 %s 没有登记在 agent=%s 名下的实例（不做跨 agent 回落）",
                         channel_type, agent_id)
            return None
        if not adapter.is_connected:
            logger.warning("Adapter %s not connected, attempting connect", channel_type)
            if not await adapter.connect():
                logger.error("Failed to connect adapter: %s", channel_type)
                return None

        # 统一出站分片：长回复按渠道单条上限切分逐条发，避免超限被截断/整条失败
        # （各平台 text 上限不同；此前全渠道单条整发且吞错）。非文本类型原样发。
        from neurova.channels.message_chunker import split_message, text_limit_for

        parts = [content]
        if message_type == "text":
            parts = split_message(content, text_limit_for(channel_type))

        first_id: Optional[str] = None
        failed = 0
        for part in parts:
            result = await adapter.send_message(chat_id, part, message_type, **kwargs)
            if result is None:
                failed += 1
                logger.warning("渠道 %s 分片发送失败（chat=%s，第 %d/%d 片）",
                               channel_type, str(chat_id)[:20], parts.index(part) + 1, len(parts))
            elif first_id is None:
                first_id = result
            await self._sync_reply_to_session(session_scope, part, channel_type)
        if failed:
            logger.error("渠道 %s 回复有 %d/%d 片发送失败（chat=%s）", channel_type, failed, len(parts), str(chat_id)[:20])
        return first_id

    async def _sync_reply_to_session(self, chat_id: str, content: str, channel_type: str):
        """同步回复消息到 SessionSyncManager（chat_id 处传入统一 scope 键）"""
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
        """向**所有实例**广播消息——定义域是全量实例表，不是 default 兼容视图（§6-195）。

        此前遍历 `self._adapters`，于是工作流审批通知（唯一生产调用者
        `collaboration/neurflow/builtin.py:2135`）只发给 default 名下那几只渠道，挂在别的 agent
        名下的渠道收不到审批、流程卡在 pending 等人。键沿用 `_adapterViewKey` 单源：
        default 仍是裸渠道名 ⇒ 现有 caller 的 `list(results.values())[0]` 与 mock 形状都不破。
        """
        results = {}
        table = getattr(self, "_agent_adapters", {}) or {}
        targets = list(table.items())
        for channelType, adapter in self._adapters.items():
            if ("default", channelType) not in table:
                targets.append((("default", channelType), adapter))
        for (agent_id, channel_type), adapter in targets:
            if adapter.is_connected:
                try:
                    msg_id = await adapter.send_message("", content, message_type, **kwargs)
                    results[_adapterViewKey(agent_id, channel_type)] = msg_id
                except Exception as e:
                    logger.exception("Broadcast to %s failed: %s", channel_type, e)
                    results[_adapterViewKey(agent_id, channel_type)] = None
        return results

    async def _on_channel_event(self, event_type: ChannelEventType, message: ChannelMessage):
        """处理渠道事件"""
        logger.info("Channel event: %s from %s " f"sender=%s", event_type.value, message.channel_type, message.sender_name)

        if event_type in (
            ChannelEventType.HUMAN_TAKEOVER_STARTED,
            ChannelEventType.HUMAN_TAKEOVER_ENDED,
        ):
            try:
                from neurova.quality import get_quality_store

                session_id = self.resolve_session_scope_id(message)
                occurred = getattr(message, "timestamp", None)
                get_quality_store().recordEvent(
                    event_type.value, session_id,
                    agentId=str(message.metadata.get("agent_id") or ""),
                    channel=str(message.channel_type or ""),
                    source="channel_event",
                    sourceEventId="%s:%s:%s" % (
                        message.channel_type, message.message_id, event_type.value,
                    ),
                    actorId=str(message.sender_id or ""),
                    reasonCode=str(message.metadata.get("takeover_reason") or ""),
                    occurredAt=occurred.isoformat() if hasattr(occurred, "isoformat") else None,
                    metadata={"chat_id": message.chat_id},
                )
            except Exception as exc:  # noqa: BLE001 - 质量账失败不影响渠道主链
                logger.warning("渠道人工接管事件记录失败: %s", exc)
            return

        # 广播到 SessionSyncManager
        await self._sync_to_session_sync(event_type, message)

        # 机器人被移出群 → 归档该会话（不再处理该群消息、控制台隐藏）
        if event_type == ChannelEventType.CHAT_BOT_REMOVED:
            await self.archive_channel_session(message)
            return

        if event_type == ChannelEventType.MESSAGE_RECEIVED:
            # P1-12 语音预检: 语音消息先转写再进 handler 链（@提及/关键词
            # 判定拿真实文本；失败降级占位，绝不阻断）
            try:
                from neurova.channels.voice_precheck import transcribe_voice_message

                message = await transcribe_voice_message(message)
            except Exception as e:  # noqa: BLE001 - 预检故障不影响消息分发
                logger.debug("语音预检跳过: %s", e)

            # P0-5 入站持久化队列：先持久化再分发，重启不
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

            db_path = callerPath(os.environ.get("NEUROVA_CHANNEL_INGRESS_DB"), "channel_ingress.db")
            queue = ChannelIngressQueue(db_path=db_path)
            self.ingress_queue = queue
            return queue
        except Exception as e:
            logger.warning("Ingress queue unavailable, fail-open to direct dispatch: %s", e)
            self._ingress_queue_failed = True
            return None

    def _reply_kwargs(self, message: ChannelMessage) -> dict:
        """回发时携带的上下文：agent 归属（按实例查适配器）+ 群@提问者所需 sender/群标记。
        此前 _dispatch_message 回发只传 (channel_type, chat_id, reply)，丢失 sender/
        chat_type/agent_id → 群回复无法@提问者、非 default agent 回发拿错实例。"""
        return {
            "agent_id": str(message.metadata.get("agent_id") or "default"),
            "at_user_id": message.sender_id,
            "chat_type": message.chat_type,
            # 渠道专属回发上下文（钉钉 session_webhook 等）随 metadata 透传给适配器
            "reply_metadata": dict(message.metadata or {}),
            # 统一会话作用域键：回复广播到内存层须用与入站一致的 scope（此前用裸
            # chat_id 反查 → 按发送者隔离/非 default agent 时查不到、实时同步断链）
            "session_scope": self.resolve_session_scope_id(message),
        }

    async def _sendReplyItems(self, message: ChannelMessage, items) -> None:
        """把 handler 返回的回发项逐条送出。

        项有两种：`str`＝文本条（既有契约）；`VoiceReply`＝本轮 TTS 产物（§6-168 缺口②）。
        处理器链与单处理器回退**共用这一条**——此前两处各写一份循环，改一处漏一处正是
        §6-161 那笔（删双写只补 chat.py 漏了 console.py）的同族。
        """
        for part in (items if isinstance(items, (list, tuple)) else [items]):
            if part is None or part == "":
                continue
            if isinstance(part, VoiceReply):
                await self._sendVoiceReply(message, part)
                continue
            await self.send_message(
                message.channel_type,
                message.chat_id,
                str(part),
                **self._reply_kwargs(message),
            )

    async def _sendVoiceReply(self, message: ChannelMessage, reply: VoiceReply) -> None:
        """按渠道能力落地一条语音回发；发不出去必须点名，不得静默丢。

        能力位在适配器上（`ChannelAdapter.voiceOutMode`，取值只在
        `neurova/channels/voice_egress.py` 定义）。不支持时**不降级成"发个链接"**——
        本仓没有公网基址配置，相对 URL 在手机上不可点，那样做等于把假送达写进日志。
        """
        agent_id = str(message.metadata.get("agent_id") or "default")
        adapter = self.get_adapter(message.channel_type, agent_id)
        mode = getattr(adapter, "voiceOutMode", VOICE_OUT_NONE) if adapter is not None else VOICE_OUT_NONE
        resolved = resolveVoiceReply(reply.file_path, mode, reply.paired_text)
        if resolved is None:
            logger.warning(
                "渠道 %s（agent=%s）不支持语音出站，本轮 TTS 产物未送达：%s",
                message.channel_type, agent_id, reply.file_path,
            )
            return
        await self.send_message(
            message.channel_type,
            message.chat_id,
            "",
            message_type=VOICE_MESSAGE_TYPE,
            file_path=resolved.file_path,
            **self._reply_kwargs(message),
        )

    async def _dispatch_message(self, message: ChannelMessage):
        """把一条渠道消息送进处理器链（原 _on_channel_event 分发体）。"""
        # 优先使用多处理器链
        # C-24: 快照遍历——处理器在回调中增删列表时不再被并发修改影响
        if self._message_handlers:
            for priority, handler_id, handler in list(self._message_handlers):
                try:
                    reply = await handler(message)
                    if reply:
                        # 2026-09-14 契约扩展：handler 可返回多条消息（思考/工具/
                        # 正文拆分）；2026-10-12 起项可为文本或 VoiceReply（语音）。
                        await self._sendReplyItems(message, reply)
                        break  # 第一个返回回复的处理器获胜
                except Exception as e:
                    logger.exception("Message handler %s error: %s", handler_id, e)
        # 回退到单处理器模式
        elif self._message_handler:
            try:
                reply = await self._message_handler(message)
                if reply:
                    await self._sendReplyItems(message, reply)
            except Exception as e:
                logger.exception("Message handler error: %s", e)
                # 尝试发送错误提示
                try:
                    await self.send_message(
                        message.channel_type,
                        message.chat_id,
                        "抱歉，处理消息时出现错误，请稍后重试。",
                        **self._reply_kwargs(message),
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
                # 2026-09-13 agent 隔离：归属取来源 adapter（装配期注入），
                # 替换原硬编码 "default"——渠道多 agent 路由的数据通路根点。
                agent_id = str(message.metadata.get("agent_id") or "default")
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
        # agent 多实例：遍历全量表（default 视图兜底保留，防只写 _adapters 的旧路径）
        table = dict(getattr(self, "_agent_adapters", {}) or {})
        for channel_type, adapter in self._adapters.items():
            table.setdefault(("default", channel_type), adapter)
        for (_aid, _ctype), adapter in table.items():
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
    # B4-a 渠道管理能力面
    # ============================================================

    async def restart_channel(self, channel_type: str, agent_id: str = "default") -> Dict[str, Any]:
        """渠道重启：disconnect → connect（配置变更生效/断线重连语义）。

        必须带 agent 维度：实例表的主键是 `(agent_id, channel_type)`，同一平台
        在不同 agent 下可以是两个独立 bot。缺了 agent 就会去动 default 的实例 ——
        用户在「凯蒂」的视图里点重启，动的是别人的长连接，而屏幕上看不出差别。
        """
        adapter = self.get_adapter(channel_type, agent_id=agent_id)
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

    def clear_channel_queue(self, channel_type: str, agent_id: str = "default") -> int:
        """清空该 (agent, 渠道) 的待处理入站队列，返回清除条数。

        队列按 agent 归属：同平台两个 agent 各自的积压必须分开清 ——
        按渠道裸名清会把别人的待办一起删掉（用户只看得见自己视图里的积压数）。
        队列不可用抛 IngressQueueUnavailable。
        """
        queue = self._get_ingress_queue()
        return queue.clear(channel_type, agent_id=agent_id)

    def conflict_check(self) -> Dict[str, Any]:
        """机器人身份冲突检测（**跨 agent 全量扫描面**）。

        两个渠道复用同一身份凭据（app_id/api_key 相同）时，平台的回调/事件
        会串渠道。按身份指纹分组，返回出现 ≥2 次的冲突项。

        扫描面必须是全量实例表 `_agent_adapters`：曾经只扫 `_adapters`（default
        兼容视图），于是「agent A 的飞书」与「agent B 的钉钉」用同一个 app_id
        配出来时，检测**完全看不见** —— 而这两个 bot 会互相抢同一条平台事件流，
        正是本检测存在的理由。归属对带上 agent，否则同名平台分不清是哪两个实例。
        """
        groups: Dict[str, List[str]] = {}
        table = getattr(self, "_agent_adapters", {}) or {}
        owners = table if table else {
            ("default", channel_type): adapter for channel_type, adapter in self._adapters.items()
        }
        for (agent_id, channel_type), adapter in owners.items():
            cfg = getattr(adapter, "config", None)
            app_id = str(getattr(cfg, "app_id", "") or "")
            api_key = str(getattr(cfg, "api_key", "") or "")
            identity = app_id or api_key
            if not identity:
                continue
            groups.setdefault(identity, []).append(
                _adapterViewKey(agent_id, channel_type)
            )
        conflicts = [
            {"identity": identity, "channels": channels}
            for identity, channels in groups.items()
            if len(channels) >= 2
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

    async def archive_channel_session(self, message: ChannelMessage) -> bool:
        """机器人被移出群 → 归档该会话文件（移入 archived/，控制台与实时同步消失）。

        会话键与 channel_router 落盘时一致：resolve_session_scope_id(message)。
        归档失败仅告警，不抛（事件旁路）。"""
        agent_id = str(message.metadata.get("agent_id") or "default")
        session_id = self.resolve_session_scope_id(message)
        try:
            from neurova.session_manager import SessionManager
            repo = SessionManager()
            ok = repo.archive_session(agent_id, session_id)
            if ok:
                logger.info("已归档渠道会话（机器人被移出群）: agent=%s session=%s", agent_id, session_id)
            return bool(ok)
        except Exception as e:  # noqa: BLE001 - 归档失败不影响事件处理
            logger.warning("归档渠道会话失败 agent=%s session=%s: %s", agent_id, session_id, e)
            return False


    def resolve_session_scope_id(self, message: ChannelMessage) -> str:
        """群聊会话隔离键（单点裁决，供会话同步/处理器共用）。

        share_session_in_group=True（默认）→ chat_id（群内共享一个会话）；
 False → ``chat_id:sender_id``。
        配置取适配器的 share_session_in_group 属性（bool/"true"/"false"），
        未声明的适配器默认共享——与既有行为等价，只提升不下降。
        agent 隔离（2026-09-13）：非 default agent 的实例前缀 ``agent:``
        default 保持旧键格式——既有会话历史零迁移。
        """
        agent = str(message.metadata.get("agent_id") or "default")
        scope = message.chat_id if agent == "default" else f"{agent}:{message.chat_id}"
        adapter = self.get_adapter(message.channel_type, agent_id=agent)
        if adapter is not None:
            share = getattr(adapter, "share_session_in_group", True)
            if not self._coerce_share_flag(share) and message.sender_id:
                scope = f"{message.chat_id}:{message.sender_id}"
        return scope

    # ============================================================
    # 健康检查
    # ============================================================

    async def health_check(self) -> Dict[str, Any]:
        """检查**所有实例**的健康状态——定义域是全量实例表，不是 default 视图（§6-190）。

        此前遍历 `self._adapters`（default 兼容视图），于是 `GET /channel-adapters` 与
        `/health/all` 看不见挂在别的 agent 名下的渠道——实例明明连着、也在收消息，健康视图里却没有它。
        键约定与 `list_adapters` 共用同一个 `_adapterViewKey`（default 保留裸键向后兼容）。
        """
        table = getattr(self, "_agent_adapters", {}) or {}
        targets = list(table.items())
        for channelType, adapter in self._adapters.items():
            if ("default", channelType) not in table:
                targets.append((("default", channelType), adapter))

        statuses: Dict[str, Any] = {}
        for (agentId, channelType), adapter in targets:
            try:
                status = await adapter.health_check()
            except Exception as e:  # noqa: BLE001 - 单渠道探活失败不影响整张视图
                status = {
                    "channel_type": channelType,
                    "connected": False,
                    "error": str(e),
                }
            entry = dict(status or {})
            entry.setdefault("channel_type", channelType)
            entry.setdefault("agent_id", agentId)
            statuses[_adapterViewKey(agentId, channelType)] = entry

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
