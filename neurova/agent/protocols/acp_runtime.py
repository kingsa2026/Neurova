"""
ACP 运行时 (Agent Communication Protocol Runtime)。

对齐升级方案 P1-2.1：基于已有 AgentMessage 信封（message_protocol.py），
落地 agent 间消息路由中枢：

- register/unregister: agent 注册与注销（handler 可同步可异步）
- send: 同步派发；未知接收者 → 死信队列（复用 dead_letter_queue.py）
- request/response: correlation_id 关联的请求-响应；handler 返回的
  AgentMessage 视为响应自动回路由
- trace_id 贯穿：同一条业务链路的所有消息共享 trace_id

设计约束（AGENTS.md）:
- 深模块：不 import Agent，通过 handler 回调解耦
- 单例生命周期: get_acp_runtime() / reset_acp_runtime()
- 线程安全: threading.RLock 保护注册表与统计
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Optional, Union

from neurova.agent.protocols.message_protocol import (
    AgentMessage,
    DeadLetterReason,
    MessageType,
)

logger = logging.getLogger(__name__)

# handler 签名：接收 AgentMessage，可返回 AgentMessage（视为响应）或任意值
MessageHandler = Callable[[AgentMessage], Any]
AwaitableOrValue = Union[Any]


class DeliveryStatus(str, Enum):
    """派发结果状态"""

    DELIVERED = "delivered"
    FAILED = "failed"
    EXPIRED = "expired"
    DEAD_LETTER = "dead_letter"


@dataclass
class DeliveryResult:
    """一次 send 的派发结果"""

    status: DeliveryStatus
    message_id: str = ""
    reason: Optional[DeadLetterReason] = None
    error: Optional[str] = None


@dataclass
class _PendingRequest:
    """request() 的挂起等待"""

    correlation_id: str
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())
    created_at: float = field(default_factory=time.time)


class ACPRuntime:
    """ACP 消息中枢：agent 注册表 + 路由 + 请求-响应关联 + DLQ 兜底。"""

    def __init__(self):
        self._handlers: Dict[str, MessageHandler] = {}
        self._lock = threading.RLock()
        self._pending: Dict[str, _PendingRequest] = {}
        # 统计
        self._stats = {"sent": 0, "delivered": 0, "failed": 0, "expired": 0, "dead_letter": 0}
        # 延迟加载 DLQ（可选依赖，缺失时降级为仅记录日志）
        try:
            from neurova.agent.protocols.dead_letter_queue import get_dead_letter_queue

            self._dlq = get_dead_letter_queue()
        except Exception:
            self._dlq = None

    # ── 注册 ────────────────────────────────────────────────────

    def register_agent(
        self,
        agent_id: str,
        handler: MessageHandler,
        capabilities: Optional[list] = None,
    ) -> bool:
        if not agent_id:
            raise ValueError("agent_id 不能为空")
        with self._lock:
            if capabilities and hasattr(self._dlq, "noop"):
                pass  # 能力注册由 CapabilityDiscovery 负责，此处仅保留扩展点
            replaced = agent_id in self._handlers
            self._handlers[agent_id] = handler
            if replaced:
                logger.debug("ACP agent 处理器已替换: %s", agent_id)
            else:
                logger.info("ACP agent 已注册: %s", agent_id)
        return True

    def unregister_agent(self, agent_id: str) -> bool:
        with self._lock:
            return self._handlers.pop(agent_id, None) is not None

    def list_agents(self) -> list:
        with self._lock:
            return list(self._handlers.keys())

    # ── 派发 ────────────────────────────────────────────────────

    def send(self, message: AgentMessage) -> DeliveryResult:
        """同步派发消息。handler 若为协程函数则调度到事件循环。"""
        with self._lock:
            self._stats["sent"] += 1

        if message.is_expired():
            with self._lock:
                self._stats["expired"] += 1
            self._to_dead_letter(message, DeadLetterReason.TIMEOUT)
            return DeliveryResult(
                status=DeliveryStatus.EXPIRED,
                message_id=message.message_id,
                reason=DeadLetterReason.TIMEOUT,
            )

        with self._lock:
            handler = self._handlers.get(message.receiver_id)

        if handler is None:
            with self._lock:
                self._stats["dead_letter"] += 1
            self._to_dead_letter(message, DeadLetterReason.RECIPIENT_NOT_FOUND)
            return DeliveryResult(
                status=DeliveryStatus.DEAD_LETTER,
                message_id=message.message_id,
                reason=DeadLetterReason.RECIPIENT_NOT_FOUND,
            )

        try:
            outcome = handler(message)
            if asyncio.iscoroutine(outcome):
                # 异步 handler：调度执行，完成后处理其响应
                _schedule_async_handler(outcome, message, self._on_handler_done)
            else:
                self._on_handler_done(message, outcome)
        except Exception as e:  # noqa: BLE001 - 单个 handler 故障不能拖垮中枢
            logger.warning("ACP handler 执行失败 (%s): %s", message.receiver_id, e)
            with self._lock:
                self._stats["failed"] += 1
            self._to_dead_letter(message, DeadLetterReason.SYSTEM_ERROR)
            return DeliveryResult(
                status=DeliveryStatus.FAILED,
                message_id=message.message_id,
                reason=DeadLetterReason.SYSTEM_ERROR,
                error=str(e),
            )

        with self._lock:
            self._stats["delivered"] += 1
        return DeliveryResult(status=DeliveryStatus.DELIVERED, message_id=message.message_id)

    def _on_handler_done(self, original: AgentMessage, outcome: Any) -> None:
        """handler 完成：若返回 AgentMessage 则视为响应，按 correlation_id 回路由。"""
        if not isinstance(outcome, AgentMessage):
            return
        response = outcome
        response.type = MessageType.RESPONSE
        if response.correlation_id is None:
            response.correlation_id = original.message_id
        self._resolve_pending(response.correlation_id, response)

    async def send_async(self, message: AgentMessage) -> DeliveryResult:
        """异步环境下的派发（语义同 send，协程 handler 直接 await）。"""
        with self._lock:
            handler = self._handlers.get(message.receiver_id)
        if handler is None or message.is_expired():
            return self.send(message)
        try:
            outcome = handler(message)
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            self._on_handler_done(message, outcome)
            with self._lock:
                self._stats["delivered"] += 1
            return DeliveryResult(status=DeliveryStatus.DELIVERED, message_id=message.message_id)
        except Exception as e:  # noqa: BLE001
            with self._lock:
                self._stats["failed"] += 1
            return DeliveryResult(
                status=DeliveryStatus.FAILED, message_id=message.message_id, error=str(e)
            )

    # ── 请求-响应 ───────────────────────────────────────────────

    async def request(self, message: AgentMessage, timeout: float = 10.0) -> Optional[AgentMessage]:
        """发送请求并等待关联响应；超时或未知接收者返回 None。"""
        loop = asyncio.get_running_loop()
        correlation_id = message.correlation_id or message.message_id
        message.correlation_id = correlation_id

        future = loop.create_future()
        pending = _PendingRequest(correlation_id=correlation_id, future=future)
        with self._lock:
            self._pending[correlation_id] = pending

        try:
            result = await asyncio.get_running_loop().run_in_executor(None, self.send, message)
            if result.status != DeliveryStatus.DELIVERED:
                return None
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            with self._lock:
                self._pending.pop(correlation_id, None)

    def _resolve_pending(self, correlation_id: str, response: AgentMessage) -> None:
        with self._lock:
            pending = self._pending.pop(correlation_id, None)
        if pending and not pending.future.done():
            # future 绑定在创建它的循环上；从当前（可能是工作）线程线程安全地置值
            try:
                loop = pending.future.get_loop()
                loop.call_soon_threadsafe(pending.future.set_result, response)
            except RuntimeError:
                pending.future.set_result(response)

    # ── DLQ 与统计 ──────────────────────────────────────────────

    def _to_dead_letter(self, message: AgentMessage, reason: DeadLetterReason) -> None:
        try:
            if self._dlq is not None:
                self._dlq.add(message, reason)
        except Exception:
            logger.debug("DLQ 写入失败（降级忽略）", exc_info=True)

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            stats = dict(self._stats)
            stats["registered_agents"] = len(self._handlers)
            stats["pending_requests"] = len(self._pending)
            return stats


def _schedule_async_handler(coro, original: AgentMessage, on_done: Callable) -> None:
    """把异步 handler 的完成回调接到事件循环。"""

    async def _runner():
        try:
            outcome = await coro
            on_done(original, outcome)
        except Exception as e:  # noqa: BLE001
            logger.warning("异步 handler 执行失败 (%s): %s", original.receiver_id, e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_runner())
    except RuntimeError:
        # 无运行中的事件循环（同步上下文）：新起后台循环执行
        asyncio.run(_runner())


# ── 单例生命周期 ────────────────────────────────────────────────

_acp_runtime_instance: Optional[ACPRuntime] = None


def get_acp_runtime() -> ACPRuntime:
    global _acp_runtime_instance
    if _acp_runtime_instance is None:
        _acp_runtime_instance = ACPRuntime()
    return _acp_runtime_instance


def reset_acp_runtime() -> None:
    global _acp_runtime_instance
    _acp_runtime_instance = None


__all__ = [
    "ACPRuntime",
    "DeliveryStatus",
    "DeliveryResult",
    "get_acp_runtime",
    "reset_acp_runtime",
]
