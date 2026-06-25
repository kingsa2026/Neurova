# -*- coding: utf-8 -*-
"""
Agent 通信协议模块

提供标准化的 Agent 间消息格式和优先级处理：
1. 标准消息格式（JSON Schema）
2. 消息优先级（urgent/high/normal/low）
3. 消息类型定义
4. 协议版本管理
"""

import json
from neurova.core.logger import get_logger
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class ProtocolVersion:
    """协议版本常量"""

    CURRENT = "2.0"
    SUPPORTED_VERSIONS = ["1.0", "1.5", "2.0"]


class MessagePriority(str, Enum):
    """消息优先级枚举

    优先级从小到大：LOW -> NORMAL -> HIGH -> URGENT
    """

    LOW = "low"  # 低优先级，可延迟处理
    NORMAL = "normal"  # 普通优先级，正常处理
    HIGH = "high"  # 高优先级，尽快处理
    URGENT = "urgent"  # 紧急优先级，立即处理

    @property
    def value_int(self) -> int:
        """获取优先级数值（用于排序）"""
        priority_map = {
            MessagePriority.LOW: 0,
            MessagePriority.NORMAL: 1,
            MessagePriority.HIGH: 2,
            MessagePriority.URGENT: 3,
        }
        return priority_map.get(self, 1)

    @classmethod
    def from_int(cls, value: int) -> "MessagePriority":
        """从整数转换为优先级"""
        if value <= 0:
            return cls.LOW
        elif value == 1:
            return cls.NORMAL
        elif value == 2:
            return cls.HIGH
        else:
            return cls.URGENT


class MessageType(str, Enum):
    """消息类型枚举"""

    # 协作消息
    REQUEST = "request"  # 请求消息
    RESPONSE = "response"  # 响应消息
    NOTIFICATION = "notification"  # 通知消息
    BROADCAST = "broadcast"  # 广播消息

    # 特殊消息
    HEARTBEAT = "heartbeat"  # 心跳消息
    CAPABILITY_QUERY = "capability_query"  # 能力查询
    CAPABILITY_RESPONSE = "capability_response"  # 能力响应
    TASK_ASSIGNMENT = "task_assignment"  # 任务分配
    TASK_RESULT = "task_result"  # 任务结果
    COLLABORATION_INVITE = "collaboration_invite"  # 协作邀请
    COLLABORATION_ACCEPT = "collaboration_accept"  # 协作接受
    COLLABORATION_REJECT = "collaboration_reject"  # 协作拒绝
    COLLABORATION_END = "collaboration_end"  # 协作结束

    # 死信相关
    DEAD_LETTER = "dead_letter"  # 死信消息
    RETRY = "retry"  # 重试消息


class DeadLetterReason(str, Enum):
    """死信原因枚举"""

    TIMEOUT = "timeout"  # 超时
    RECIPIENT_NOT_FOUND = "recipient_not_found"  # 接收者不存在
    RECIPIENT_UNAVAILABLE = "recipient_unavailable"  # 接收者不可用
    INVALID_MESSAGE = "invalid_message"  # 消息格式错误
    PERMISSION_DENIED = "permission_denied"  # 权限不足
    RATE_LIMITED = "rate_limited"  # 速率限制
    SYSTEM_ERROR = "system_error"  # 系统错误
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"  # 超过最大重试次数
    UNKNOWN_ERROR = "unknown_error"  # 未知错误


@dataclass
class AgentMessage:
    """Agent 间标准消息格式

    符合 JSON Schema 规范的消息结构：
    {
        "message_id": "uuid",
        "version": "1.0.0",
        "type": "request|response|notification|...",
        "priority": "low|normal|high|urgent",
        "sender": {
            "agent_id": "string",
            "agent_name": "string",
            "capabilities": [...]
        },
        "receiver": {
            "agent_id": "string",
            "agent_name": "string"
        },
        "content": {
            "action": "string",
            "params": {...},
            "data": {...}
        },
        "correlation_id": "uuid (用于请求-响应对)",
        "reply_to": "uuid (回复地址)",
        "timestamp": 1234567890.123,
        "expires_at": 1234567890.123,
        "metadata": {...},
        "attachments": [...]
    }
    """

    # 核心字段
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    version: str = ProtocolVersion.CURRENT

    # 消息类型和优先级
    type: MessageType = MessageType.REQUEST
    priority: MessagePriority = MessagePriority.NORMAL

    # 发送者和接收者
    sender_id: str = ""
    sender_name: str = ""
    sender_capabilities: List[str] = field(default_factory=list)

    receiver_id: str = ""
    receiver_name: str = ""

    # 消息内容
    action: str = ""  # 操作类型
    params: Dict[str, Any] = field(default_factory=dict)
    data: Dict[str, Any] = field(default_factory=dict)

    # 关联和回复
    correlation_id: Optional[str] = None  # 关联ID（请求-响应对）
    reply_to: Optional[str] = None  # 回复地址

    # 时间戳
    timestamp: float = field(default_factory=time.time)
    expires_at: Optional[float] = None  # 过期时间（可选）

    # 元数据和附件
    metadata: Dict[str, Any] = field(default_factory=dict)
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    # 追踪字段
    retry_count: int = 0
    max_retries: int = 3
    trace_id: Optional[str] = None  # 分布式追踪ID

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "message_id": self.message_id,
            "version": self.version,
            "type": self.type.value if isinstance(self.type, MessageType) else self.type,
            "priority": self.priority.value if isinstance(self.priority, MessagePriority) else self.priority,
            "sender": {
                "agent_id": self.sender_id,
                "agent_name": self.sender_name,
                "capabilities": self.sender_capabilities,
            },
            "receiver": {
                "agent_id": self.receiver_id,
                "agent_name": self.receiver_name,
            },
            "content": {
                "action": self.action,
                "params": self.params,
                "data": self.data,
            },
            "correlation_id": self.correlation_id,
            "reply_to": self.reply_to,
            "timestamp": self.timestamp,
            "expires_at": self.expires_at,
            "metadata": self.metadata,
            "attachments": self.attachments,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "trace_id": self.trace_id,
        }

    def to_json(self) -> str:
        """转换为 JSON 字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentMessage":
        """从字典创建消息"""
        sender = data.get("sender", {})
        receiver = data.get("receiver", {})
        content = data.get("content", {})

        return cls(
            message_id=data.get("message_id", str(uuid.uuid4())),
            version=data.get("version", ProtocolVersion.CURRENT),
            type=MessageType(data.get("type", "request")),
            priority=MessagePriority(data.get("priority", "normal")),
            sender_id=sender.get("agent_id", ""),
            sender_name=sender.get("agent_name", ""),
            sender_capabilities=sender.get("capabilities", []),
            receiver_id=receiver.get("agent_id", ""),
            receiver_name=receiver.get("agent_name", ""),
            action=content.get("action", ""),
            params=content.get("params", {}),
            data=content.get("data", {}),
            correlation_id=data.get("correlation_id"),
            reply_to=data.get("reply_to"),
            timestamp=data.get("timestamp", time.time()),
            expires_at=data.get("expires_at"),
            metadata=data.get("metadata", {}),
            attachments=data.get("attachments", []),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            trace_id=data.get("trace_id"),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "AgentMessage":
        """从 JSON 字符串创建消息"""
        return cls.from_dict(json.loads(json_str))

    def create_response(
        self,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> "AgentMessage":
        """创建响应消息"""
        return AgentMessage(
            message_id=str(uuid.uuid4()),
            version=self.version,
            type=MessageType.RESPONSE,
            priority=self.priority,
            sender_id=self.receiver_id,
            sender_name=self.receiver_name,
            receiver_id=self.sender_id,
            receiver_name=self.sender_name,
            action=f"{self.action}_response",
            params={"success": success},
            data=result or {},
            correlation_id=self.message_id,  # 关联到请求消息
            metadata={
                "original_action": self.action,
                "error": error,
            },
        )

    def is_expired(self) -> bool:
        """检查消息是否过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def increment_retry(self) -> bool:
        """增加重试次数

        Returns:
            如果还可以重试返回 True，否则返回 False
        """
        self.retry_count += 1
        return self.retry_count < self.max_retries


@dataclass
class DeadLetterMessage:
    """死信消息（无法投递或处理失败的消息）"""

    original_message: AgentMessage
    reason: DeadLetterReason
    error_details: str
    failed_at: float = field(default_factory=time.time)
    handler_id: Optional[str] = None
    original_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "original_message": self.original_message.to_dict(),
            "reason": self.reason.value,
            "error_details": self.error_details,
            "failed_at": self.failed_at,
            "failed_at_iso": datetime.fromtimestamp(self.failed_at).isoformat(),
            "handler_id": self.handler_id,
            "original_error": self.original_error,
        }


class MessageQueue:
    """优先级消息队列"""

    def __init__(self):
        self._queues: Dict[MessagePriority, list] = {
            MessagePriority.URGENT: [],
            MessagePriority.HIGH: [],
            MessagePriority.NORMAL: [],
            MessagePriority.LOW: [],
        }
        self._total_count = 0

    def enqueue(self, message: AgentMessage) -> None:
        """入队（按优先级插入）"""
        self._queues[message.priority].append(message)
        self._total_count += 1

    def dequeue(self) -> Optional[AgentMessage]:
        """出队（按优先级，先高后低）"""
        for priority in [MessagePriority.URGENT, MessagePriority.HIGH, MessagePriority.NORMAL, MessagePriority.LOW]:
            if self._queues[priority]:
                self._total_count -= 1
                return self._queues[priority].pop(0)
        return None

    def peek(self) -> Optional[AgentMessage]:
        """查看队首消息（不移除）"""
        for priority in [MessagePriority.URGENT, MessagePriority.HIGH, MessagePriority.NORMAL, MessagePriority.LOW]:
            if self._queues[priority]:
                return self._queues[priority][0]
        return None

    def size(self) -> int:
        """获取队列长度"""
        return self._total_count

    def is_empty(self) -> bool:
        """检查队列是否为空"""
        return self._total_count == 0

    def get_by_priority(self, priority: MessagePriority) -> List[AgentMessage]:
        """获取指定优先级的所有消息"""
        return self._queues.get(priority, []).copy()

    def clear(self) -> None:
        """清空队列"""
        for queue in self._queues.values():
            queue.clear()
        self._total_count = 0


class MessageSerializer:
    """消息序列化工具"""

    @staticmethod
    def serialize(message: AgentMessage) -> bytes:
        """序列化为字节串"""
        return message.to_json().encode("utf-8")

    @staticmethod
    def deserialize(data: bytes) -> AgentMessage:
        """从字节串反序列化"""
        return AgentMessage.from_json(data.decode("utf-8"))

    @staticmethod
    def serialize_batch(messages: List[AgentMessage]) -> bytes:
        """批量序列化"""
        return json.dumps([msg.to_dict() for msg in messages], ensure_ascii=False).encode("utf-8")

    @staticmethod
    def deserialize_batch(data: bytes) -> List[AgentMessage]:
        """批量反序列化"""
        return [AgentMessage.from_dict(d) for d in json.loads(data.decode("utf-8"))]


# 全局消息队列实例
_global_message_queue: Optional[MessageQueue] = None


def get_message_queue() -> MessageQueue:
    """获取全局消息队列"""
    global _global_message_queue
    if _global_message_queue is None:
        _global_message_queue = MessageQueue()
    return _global_message_queue
