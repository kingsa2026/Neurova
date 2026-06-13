from __future__ import annotations

"""
Neurova API 开放平台事件系统

提供事件发布和Webhook投递功能：
1. EventSystem - 事件系统核心
2. Webhook投递 - 异步投递事件到订阅端点
3. 重试机制 - 失败自动重试
4. 签名验证 - HMAC-SHA256签名
"""

import asyncio
import json
import logging
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, List, Optional

# api imports
from neurova.api.openplatform.models import (
    DeliveryStatus,
    WebhookDelivery,
    WebhookEndpoint,
    WebhookEvent,
    WebhookEventType,
    generate_delivery_id,
    generate_event_id,
)

logger = logging.getLogger(__name__)


class EventTypes(Enum):
    """事件类型（兼容性别名）"""

    # 用户事件
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"

    # Agent事件
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    AGENT_MESSAGE = "agent.message"
    AGENT_ERROR = "agent.error"

    # 记忆事件
    MEMORY_CREATED = "memory.created"
    MEMORY_UPDATED = "memory.updated"
    MEMORY_DELETED = "memory.deleted"

    # 任务事件
    TASK_CREATED = "task.created"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # 系统事件
    SYSTEM_ALERT = "system.alert"
    SYSTEM_UPDATE = "system.update"

    # 聊天事件
    CHAT_MESSAGE = "chat.message"
    CHAT_RESPONSE = "chat.response"

    # 技能事件
    SKILL_USED = "skill.used"
    SKILL_ERROR = "skill.error"

    # 配额事件
    QUOTA_WARNING = "quota.warning"
    QUOTA_EXCEEDED = "quota.exceeded"


@dataclass
class Event:
    """事件数据模型"""

    event_id: str
    event_type: EventTypes
    payload: Dict[str, Any]
    source: str = "system"
    timestamp: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.event_id is None:
            self.event_id = generate_event_id()
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["event_type"] = self.event_type.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """从字典创建"""
        data = data.copy()
        data["event_type"] = EventTypes(data["event_type"])
        return cls(**data)

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "Event":
        """从JSON字符串创建"""
        return cls.from_dict(json.loads(json_str))

    def to_webhook_event(self, app_id: str, webhook_id: str) -> WebhookEvent:
        """转换为Webhook事件"""
        return WebhookEvent(
            event_id=self.event_id,
            event_type=WebhookEventType(self.event_type.value),
            app_id=app_id,
            webhook_id=webhook_id,
            payload=self.payload,
            timestamp=self.timestamp,
            metadata=self.metadata,
        )


class WebhookDeliveryJob:
    """
    Webhook投递作业
    负责异步投递事件到Webhook端点
    """

    def __init__(self, event: Event, endpoint: WebhookEndpoint, delivery_id: Optional[str] = None):
        """
        初始化投递作业

        Args:
            event: 事件
            endpoint: Webhook端点
            delivery_id: 投递ID
        """
        self.event = event
        self.endpoint = endpoint
        self.delivery_id = delivery_id or generate_delivery_id()

        # 创建投递记录
        self.delivery = WebhookDelivery(
            delivery_id=self.delivery_id,
            event_id=event.event_id,
            webhook_id=endpoint.webhook_id,
            status=DeliveryStatus.PENDING,
            url=endpoint.url,
            payload=event.to_dict(),
        )

        self._session: Optional[aiohttp.ClientSession] = None

    async def execute(self) -> WebhookDelivery:
        """
        执行投递

        Returns:
            投递记录
        """
        try:
            import aiohttp

            # 准备请求数据
            payload_json = json.dumps(self.event.to_dict(), ensure_ascii=False)
            signature = self.endpoint.generate_signature(payload_json)

            headers = {
                "Content-Type": "application/json",
                "X-Webhook-ID": self.endpoint.webhook_id,
                "X-Event-ID": self.event.event_id,
                "X-Delivery-ID": self.delivery_id,
                "X-Signature": signature,
                "User-Agent": "Neurova-Webhook/1.0",
            }

            # 发送请求
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    self.endpoint.url, data=payload_json, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    response_body = await response.text()

                    if response.status >= 200 and response.status < 300:
                        self.delivery.mark_delivered(response.status, response_body)
                        logger.info("Webhook delivered successfully: %s", self.delivery_id)
                    else:
                        self.delivery.mark_failed(f"HTTP {response.status}: {response_body}", response.status)
                        logger.warning("Webhook delivery failed: %s (HTTP %d)", self.delivery_id, response.status)

            return self.delivery

        except asyncio.TimeoutError:
            self.delivery.mark_failed("Timeout")
            logger.warning("Webhook delivery timeout: %s", self.delivery_id)
            return self.delivery

        except Exception as e:
            self.delivery.mark_failed(str(e))
            logger.error("Webhook delivery error: %s - %s", self.delivery_id, e)
            return self.delivery

    async def _schedule_retry(self):
        """安排重试"""
        if self.delivery.should_retry():
            logger.info("Scheduling retry for delivery %s (attempt %d)", self.delivery_id, self.delivery.attempts + 1)
            # 延迟后重试
            await asyncio.sleep(self.delivery.next_retry_at - time.time())
            await self.execute()

    async def close(self):
        """关闭资源"""
        if self._session:
            await self._session.close()


class EventSystem:
    """
    事件系统
    负责事件发布和Webhook管理
    """

    _instance: Optional["EventSystem"] = None

    def __init__(self):
        """初始化事件系统"""
        self._endpoints: Dict[str, WebhookEndpoint] = {}
        self._event_queue: asyncio.Queue[Event] = asyncio.Queue()
        self._delivery_queue: asyncio.Queue[WebhookDeliveryJob] = asyncio.Queue()
        self._deliveries: Dict[str, WebhookDelivery] = {}
        self._handlers: Dict[EventTypes, List[Callable[[Event], Awaitable[None]]]] = {}
        self._worker_task: Optional[asyncio.Task] = None
        self._delivery_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._stats = {
            "events_published": 0,
            "deliveries_attempted": 0,
            "deliveries_successful": 0,
            "deliveries_failed": 0,
        }

        logger.info("EventSystem initialized")

    @classmethod
    def get_instance(cls) -> "EventSystem":
        """获取事件系统实例（单例模式）"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self):
        """启动事件系统"""
        if self._is_running:
            logger.warning("EventSystem is already running")
            return

        self._is_running = True

        # 启动工作线程
        self._worker_task = asyncio.create_task(self._worker_loop())
        self._delivery_task = asyncio.create_task(self._delivery_loop())

        logger.info("EventSystem started")

    async def stop(self):
        """停止事件系统"""
        if not self._is_running:
            return

        self._is_running = False

        # 取消任务
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

        if self._delivery_task:
            self._delivery_task.cancel()
            try:
                await self._delivery_task
            except asyncio.CancelledError:
                pass

        logger.info("EventSystem stopped")

    async def _worker_loop(self):
        """事件处理工作循环"""
        while self._is_running:
            try:
                # 等待事件
                event = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)

                # 处理事件
                await self._process_event(event)

                # 标记任务完成
                self._event_queue.task_done()

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Event processing error: %s", e)
                await asyncio.sleep(1)

    async def _delivery_loop(self):
        """投递处理工作循环"""
        while self._is_running:
            try:
                # 等待投递作业
                job = await asyncio.wait_for(self._delivery_queue.get(), timeout=1.0)

                # 执行投递
                await job.execute()

                # 存储投递记录
                self._deliveries[job.delivery_id] = job.delivery

                # 更新统计
                self._stats["deliveries_attempted"] += 1
                if job.delivery.status == DeliveryStatus.DELIVERED:
                    self._stats["deliveries_successful"] += 1
                else:
                    self._stats["deliveries_failed"] += 1

                # 标记任务完成
                self._delivery_queue.task_done()

                # 如果需要重试，安排重试
                if job.delivery.should_retry():
                    asyncio.create_task(job._schedule_retry())

            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Delivery processing error: %s", e)
                await asyncio.sleep(1)

    async def _process_event(self, event: Event):
        """
        处理事件

        Args:
            event: 事件
        """
        # 调用事件处理器
        handlers = self._handlers.get(event.event_type, [])
        for handler in handlers:
            try:
                await handler(event)
            except Exception as e:
                logger.error("Event handler error: %s", e)

        # 发送到Webhook端点
        for endpoint in self._endpoints.values():
            if endpoint.is_active and self._should_deliver(endpoint, event):
                job = WebhookDeliveryJob(event, endpoint)
                await self._delivery_queue.put(job)

    def _should_deliver(self, endpoint: WebhookEndpoint, event: Event) -> bool:
        """
        检查是否应该投递到端点

        Args:
            endpoint: Webhook端点
            event: 事件

        Returns:
            是否应该投递
        """
        # 如果没有订阅事件，投递所有事件
        if not endpoint.events:
            return True

        # 检查是否订阅了该事件类型
        webhook_event_type = WebhookEventType(event.event_type.value)
        return webhook_event_type in endpoint.events

    def register_endpoint(self, endpoint: WebhookEndpoint):
        """
        注册Webhook端点

        Args:
            endpoint: Webhook端点
        """
        self._endpoints[endpoint.webhook_id] = endpoint
        logger.info("Registered webhook endpoint: %s", endpoint.webhook_id)

    def unregister_endpoint(self, webhook_id: str):
        """
        注销Webhook端点

        Args:
            webhook_id: Webhook ID
        """
        if webhook_id in self._endpoints:
            del self._endpoints[webhook_id]
            logger.info("Unregistered webhook endpoint: %s", webhook_id)

    def get_endpoint(self, webhook_id: str) -> Optional[WebhookEndpoint]:
        """
        获取Webhook端点

        Args:
            webhook_id: Webhook ID

        Returns:
            Webhook端点，如果不存在则返回None
        """
        return self._endpoints.get(webhook_id)

    def list_endpoints(self, app_id: Optional[str] = None) -> List[WebhookEndpoint]:
        """
        列出Webhook端点

        Args:
            app_id: 应用ID过滤

        Returns:
            Webhook端点列表
        """
        endpoints = list(self._endpoints.values())
        if app_id:
            endpoints = [e for e in endpoints if e.app_id == app_id]
        return endpoints

    def update_endpoint(self, webhook_id: str, **kwargs) -> Optional[WebhookEndpoint]:
        """
        更新Webhook端点

        Args:
            webhook_id: Webhook ID
            **kwargs: 要更新的字段

        Returns:
            更新后的端点，如果不存在则返回None
        """
        endpoint = self.get_endpoint(webhook_id)
        if endpoint is None:
            return None

        for key, value in kwargs.items():
            if hasattr(endpoint, key):
                setattr(endpoint, key, value)

        endpoint.updated_at = time.time()
        return endpoint

    async def publish_event(self, event: Event):
        """
        发布事件

        Args:
            event: 事件
        """
        await self._event_queue.put(event)
        self._stats["events_published"] += 1
        logger.debug("Published event: %s (%s)", event.event_id, event.event_type.value)

    async def emit_chat_message(self, message: Dict[str, Any], user_id: str, agent_id: str):
        """
        发出聊天消息事件

        Args:
            message: 消息内容
            user_id: 用户ID
            agent_id: Agent ID
        """
        event = Event(
            event_id=generate_event_id(),
            event_type=EventTypes.CHAT_MESSAGE,
            payload={"message": message, "user_id": user_id, "agent_id": agent_id},
            source="chat",
        )
        await self.publish_event(event)

    async def emit_agent_response(self, response: Dict[str, Any], user_id: str, agent_id: str):
        """
        发出Agent响应事件

        Args:
            response: 响应内容
            user_id: 用户ID
            agent_id: Agent ID
        """
        event = Event(
            event_id=generate_event_id(),
            event_type=EventTypes.CHAT_RESPONSE,
            payload={"response": response, "user_id": user_id, "agent_id": agent_id},
            source="agent",
        )
        await self.publish_event(event)

    async def emit_memory_event(self, event_type: EventTypes, memory_id: str, agent_id: str, data: Dict[str, Any]):
        """
        发出记忆事件

        Args:
            event_type: 事件类型
            memory_id: 记忆ID
            agent_id: Agent ID
            data: 事件数据
        """
        event = Event(
            event_id=generate_event_id(),
            event_type=event_type,
            payload={"memory_id": memory_id, "agent_id": agent_id, **data},
            source="memory",
        )
        await self.publish_event(event)

    async def emit_skill_event(self, event_type: EventTypes, skill_name: str, agent_id: str, data: Dict[str, Any]):
        """
        发出技能事件

        Args:
            event_type: 事件类型
            skill_name: 技能名称
            agent_id: Agent ID
            data: 事件数据
        """
        event = Event(
            event_id=generate_event_id(),
            event_type=event_type,
            payload={"skill_name": skill_name, "agent_id": agent_id, **data},
            source="skill",
        )
        await self.publish_event(event)

    async def emit_quota_event(self, event_type: EventTypes, user_id: str, quota_type: str, data: Dict[str, Any]):
        """
        发出配额事件

        Args:
            event_type: 事件类型
            user_id: 用户ID
            quota_type: 配额类型
            data: 事件数据
        """
        event = Event(
            event_id=generate_event_id(),
            event_type=event_type,
            payload={"user_id": user_id, "quota_type": quota_type, **data},
            source="quota",
        )
        await self.publish_event(event)

    def get_delivery(self, delivery_id: str) -> Optional[WebhookDelivery]:
        """
        获取投递记录

        Args:
            delivery_id: 投递ID

        Returns:
            投递记录，如果不存在则返回None
        """
        return self._deliveries.get(delivery_id)

    def list_deliveries(
        self, webhook_id: Optional[str] = None, status: Optional[DeliveryStatus] = None, limit: int = 100
    ) -> List[WebhookDelivery]:
        """
        列出投递记录

        Args:
            webhook_id: Webhook ID过滤
            status: 状态过滤
            limit: 返回数量限制

        Returns:
            投递记录列表
        """
        deliveries = list(self._deliveries.values())

        if webhook_id:
            deliveries = [d for d in deliveries if d.webhook_id == webhook_id]

        if status:
            deliveries = [d for d in deliveries if d.status == status]

        # 按创建时间排序
        deliveries.sort(key=lambda d: d.created_at or 0, reverse=True)

        return deliveries[:limit]

    def update_delivery_status(self, delivery_id: str, status: DeliveryStatus, **kwargs) -> Optional[WebhookDelivery]:
        """
        更新投递状态

        Args:
            delivery_id: 投递ID
            status: 新状态
            **kwargs: 其他更新字段

        Returns:
            更新后的投递记录，如果不存在则返回None
        """
        delivery = self.get_delivery(delivery_id)
        if delivery is None:
            return None

        delivery.status = status
        for key, value in kwargs.items():
            if hasattr(delivery, key):
                setattr(delivery, key, value)

        return delivery

    def get_stats(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            统计信息字典
        """
        return {
            **self._stats,
            "endpoints_count": len(self._endpoints),
            "active_endpoints_count": sum(1 for e in self._endpoints.values() if e.is_active),
            "deliveries_count": len(self._deliveries),
            "pending_deliveries": sum(1 for d in self._deliveries.values() if d.status == DeliveryStatus.PENDING),
            "retrying_deliveries": sum(1 for d in self._deliveries.values() if d.status == DeliveryStatus.RETRYING),
        }


# 全局实例
_event_system: Optional[EventSystem] = None


def get_event_system() -> EventSystem:
    """
    获取事件系统实例（单例模式）

    Returns:
        EventSystem实例
    """
    global _event_system
    if _event_system is None:
        _event_system = EventSystem.get_instance()
    return _event_system


def reset_event_system():
    """
    重置事件系统实例（用于测试）
    """
    global _event_system
    if _event_system is not None:
        # 停止事件系统
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(_event_system.stop())
        else:
            loop.run_until_complete(_event_system.stop())

        _event_system = None
        EventSystem._instance = None
