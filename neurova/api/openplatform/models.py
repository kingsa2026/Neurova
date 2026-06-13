from __future__ import annotations

"""
Neurova API 开放平台数据模型

定义开放平台相关的数据结构，包括：
1. 应用模型 - 第三方应用信息
2. Webhook模型 - 事件订阅端点
3. API密钥模型 - 访问凭证
4. 事件模型 - 系统事件定义
"""

import hashlib
import json
import logging
import secrets
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AppType(Enum):
    """应用类型"""

    WEB = "web"  # Web应用
    MOBILE = "mobile"  # 移动应用
    DESKTOP = "desktop"  # 桌面应用
    CLI = "cli"  # 命令行工具
    SERVICE = "service"  # 服务应用
    BOT = "bot"  # 机器人
    PLUGIN = "plugin"  # 插件
    OTHER = "other"  # 其他


class WebhookEventType(Enum):
    """Webhook事件类型"""

    # 用户相关事件
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DELETED = "user.deleted"

    # Agent相关事件
    AGENT_CREATED = "agent.created"
    AGENT_UPDATED = "agent.updated"
    AGENT_DELETED = "agent.deleted"
    AGENT_MESSAGE = "agent.message"
    AGENT_ERROR = "agent.error"

    # 记忆相关事件
    MEMORY_CREATED = "memory.created"
    MEMORY_UPDATED = "memory.updated"
    MEMORY_DELETED = "memory.deleted"

    # 任务相关事件
    TASK_CREATED = "task.created"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"

    # 系统事件
    SYSTEM_ALERT = "system.alert"
    SYSTEM_UPDATE = "system.update"

    # 自定义事件
    CUSTOM = "custom"


class DeliveryStatus(Enum):
    """投递状态"""

    PENDING = "pending"  # 等待投递
    DELIVERED = "delivered"  # 已投递
    FAILED = "failed"  # 投递失败
    RETRYING = "retrying"  # 重试中


class ApiScope(Enum):
    """API权限范围"""

    # 用户管理
    USER_READ = "user:read"
    USER_WRITE = "user:write"
    USER_ADMIN = "user:admin"

    # Agent管理
    AGENT_READ = "agent:read"
    AGENT_WRITE = "agent:write"
    AGENT_ADMIN = "agent:admin"

    # 记忆管理
    MEMORY_READ = "memory:read"
    MEMORY_WRITE = "memory:write"
    MEMORY_ADMIN = "memory:admin"

    # 工具管理
    TOOL_READ = "tool:read"
    TOOL_WRITE = "tool:write"
    TOOL_ADMIN = "tool:admin"

    # Webhook管理
    WEBHOOK_READ = "webhook:read"
    WEBHOOK_WRITE = "webhook:write"
    WEBHOOK_ADMIN = "webhook:admin"

    # API密钥管理
    API_KEY_READ = "api_key:read"
    API_KEY_WRITE = "api_key:write"
    API_KEY_ADMIN = "api_key:admin"

    # 系统管理
    SYSTEM_READ = "system:read"
    SYSTEM_WRITE = "system:write"
    SYSTEM_ADMIN = "system:admin"

    # 分析数据
    ANALYTICS_READ = "analytics:read"
    ANALYTICS_WRITE = "analytics:write"

    # 全部权限
    ALL = "*"


@dataclass
class App:
    """应用模型"""

    app_id: str
    app_name: str
    app_type: AppType
    description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    redirect_uris: Optional[List[str]] = None
    scopes: Optional[List[ApiScope]] = None
    is_active: bool = True
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    owner_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()
        if self.scopes is None:
            self.scopes = []
        if self.redirect_uris is None:
            self.redirect_uris = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["app_type"] = self.app_type.value
        result["scopes"] = [s.value for s in self.scopes] if self.scopes else []
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "App":
        """从字典创建"""
        data = data.copy()
        data["app_type"] = AppType(data["app_type"])
        if "scopes" in data and data["scopes"]:
            data["scopes"] = [ApiScope(s) for s in data["scopes"]]
        return cls(**data)

    def has_scope(self, scope: ApiScope) -> bool:
        """检查是否有指定权限范围"""
        if not self.scopes:
            return False
        return scope in self.scopes or ApiScope.ALL in self.scopes


@dataclass
class AppCreate:
    """应用创建请求"""

    app_name: str
    app_type: AppType
    description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    redirect_uris: Optional[List[str]] = None
    scopes: Optional[List[ApiScope]] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["app_type"] = self.app_type.value
        result["scopes"] = [s.value for s in self.scopes] if self.scopes else []
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppCreate":
        """从字典创建"""
        data = data.copy()
        data["app_type"] = AppType(data["app_type"])
        if "scopes" in data and data["scopes"]:
            data["scopes"] = [ApiScope(s) for s in data["scopes"]]
        return cls(**data)


@dataclass
class AppUpdate:
    """应用更新请求"""

    app_name: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    logo_url: Optional[str] = None
    redirect_uris: Optional[List[str]] = None
    scopes: Optional[List[ApiScope]] = None
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        if self.scopes is not None:
            result["scopes"] = [s.value for s in self.scopes]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppUpdate":
        """从字典创建"""
        data = data.copy()
        if "scopes" in data and data["scopes"]:
            data["scopes"] = [ApiScope(s) for s in data["scopes"]]
        return cls(**data)


@dataclass
class WebhookEndpoint:
    """Webhook端点模型"""

    webhook_id: str
    app_id: str
    url: str
    secret: Optional[str] = None
    events: Optional[List[WebhookEventType]] = None
    description: Optional[str] = None
    is_active: bool = True
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()
        if self.secret is None:
            self.secret = secrets.token_hex(32)
        if self.events is None:
            self.events = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["events"] = [e.value for e in self.events] if self.events else []
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookEndpoint":
        """从字典创建"""
        data = data.copy()
        if "events" in data and data["events"]:
            data["events"] = [WebhookEventType(e) for e in data["events"]]
        return cls(**data)

    def generate_signature(self, payload: str) -> str:
        """生成签名"""
        if not self.secret:
            return ""
        return hashlib.sha256(f"{self.secret}{payload}".encode()).hexdigest()

    def verify_signature(self, payload: str, signature: str) -> bool:
        """验证签名"""
        expected = self.generate_signature(payload)
        return secrets.compare_digest(expected, signature)


@dataclass
class WebhookCreate:
    """Webhook创建请求"""

    app_id: str
    url: str
    events: Optional[List[WebhookEventType]] = None
    description: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["events"] = [e.value for e in self.events] if self.events else []
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookCreate":
        """从字典创建"""
        data = data.copy()
        if "events" in data and data["events"]:
            data["events"] = [WebhookEventType(e) for e in data["events"]]
        return cls(**data)


@dataclass
class WebhookUpdate:
    """Webhook更新请求"""

    url: Optional[str] = None
    events: Optional[List[WebhookEventType]] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        if self.events is not None:
            result["events"] = [e.value for e in self.events]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookUpdate":
        """从字典创建"""
        data = data.copy()
        if "events" in data and data["events"]:
            data["events"] = [WebhookEventType(e) for e in data["events"]]
        return cls(**data)


@dataclass
class WebhookEvent:
    """Webhook事件模型"""

    event_id: str
    event_type: WebhookEventType
    app_id: str
    webhook_id: str
    payload: Dict[str, Any]
    timestamp: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["event_type"] = self.event_type.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookEvent":
        """从字典创建"""
        data = data.copy()
        data["event_type"] = WebhookEventType(data["event_type"])
        return cls(**data)

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_json(cls, json_str: str) -> "WebhookEvent":
        """从JSON字符串创建"""
        return cls.from_dict(json.loads(json_str))


@dataclass
class WebhookDelivery:
    """Webhook投递记录"""

    delivery_id: str
    event_id: str
    webhook_id: str
    status: DeliveryStatus
    url: str
    payload: Dict[str, Any]
    response_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    attempts: int = 0
    max_attempts: int = 3
    created_at: Optional[float] = None
    delivered_at: Optional[float] = None
    next_retry_at: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WebhookDelivery":
        """从字典创建"""
        data = data.copy()
        data["status"] = DeliveryStatus(data["status"])
        return cls(**data)

    def mark_delivered(self, response_status: int, response_body: Optional[str] = None):
        """标记为已投递"""
        self.status = DeliveryStatus.DELIVERED
        self.response_status = response_status
        self.response_body = response_body
        self.delivered_at = time.time()
        self.attempts += 1

    def mark_failed(self, error_message: str, response_status: Optional[int] = None):
        """标记为投递失败"""
        self.status = DeliveryStatus.FAILED
        self.error_message = error_message
        self.response_status = response_status
        self.attempts += 1

        # 计算下次重试时间（指数退避）
        if self.attempts < self.max_attempts:
            self.status = DeliveryStatus.RETRYING
            retry_delay = min(300, 2**self.attempts * 10)  # 最大5分钟
            self.next_retry_at = time.time() + retry_delay

    def should_retry(self) -> bool:
        """是否应该重试"""
        if self.status != DeliveryStatus.RETRYING:
            return False
        if self.attempts >= self.max_attempts:
            return False
        if self.next_retry_at and time.time() < self.next_retry_at:
            return False
        return True


@dataclass
class ApiKey:
    """API密钥模型"""

    key_id: str
    key_hash: str
    app_id: str
    name: str
    scopes: List[ApiScope]
    is_active: bool = True
    created_at: Optional[float] = None
    expires_at: Optional[float] = None
    last_used_at: Optional[float] = None
    usage_count: int = 0
    rate_limit: int = 1000  # 每小时请求数限制
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["scopes"] = [s.value for s in self.scopes]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApiKey":
        """从字典创建"""
        data = data.copy()
        data["scopes"] = [ApiScope(s) for s in data["scopes"]]
        return cls(**data)

    @property
    def is_expired(self) -> bool:
        """是否已过期"""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    @property
    def is_valid(self) -> bool:
        """是否有效"""
        return self.is_active and not self.is_expired

    def has_scope(self, scope: ApiScope) -> bool:
        """检查是否有指定权限范围"""
        return scope in self.scopes or ApiScope.ALL in self.scopes

    def record_usage(self):
        """记录使用"""
        self.usage_count += 1
        self.last_used_at = time.time()


@dataclass
class ApiKeyCreate:
    """API密钥创建请求"""

    app_id: str
    name: str
    scopes: List[ApiScope]
    expires_in: Optional[int] = None  # 过期时间（秒）
    rate_limit: int = 1000
    metadata: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["scopes"] = [s.value for s in self.scopes]
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ApiKeyCreate":
        """从字典创建"""
        data = data.copy()
        data["scopes"] = [ApiScope(s) for s in data["scopes"]]
        return cls(**data)


# 工具函数
def generate_app_id() -> str:
    """生成应用ID"""
    return f"app_{secrets.token_hex(16)}"


def generate_webhook_id() -> str:
    """生成Webhook ID"""
    return f"wh_{secrets.token_hex(16)}"


def generate_event_id() -> str:
    """生成事件ID"""
    return f"evt_{secrets.token_hex(16)}"


def generate_delivery_id() -> str:
    """生成投递ID"""
    return f"dlv_{secrets.token_hex(16)}"


def generate_key_id() -> str:
    """生成密钥ID"""
    return f"key_{secrets.token_hex(16)}"


def generate_api_key() -> str:
    """生成API密钥"""
    return f"nk_{secrets.token_hex(32)}"


def hash_api_key(api_key: str) -> str:
    """哈希API密钥"""
    return hashlib.sha256(api_key.encode()).hexdigest()


def verify_api_key(api_key: str, key_hash: str) -> bool:
    """验证API密钥"""
    return hash_api_key(api_key) == key_hash
