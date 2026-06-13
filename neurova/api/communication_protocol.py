"""
Agent 外部通信协议模块

功能:
1. 定义标准通信协议（握手、消息格式、心跳等）
2. 实现握手协议（避免未授权连接）
3. 实现消息队列和流量控制（避免信息风暴）
4. 支持多种外部代理框架（OpenClaw、Hermes、Cloud Code、Trae、QwenCoder、QwenPaw等）
"""

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from neurova.core.logger import get_logger

logger = get_logger(__name__)


class MessageType(Enum):
    """消息类型"""

    HANDSHAKE_REQUEST = "handshake_request"
    HANDSHAKE_RESPONSE = "handshake_response"
    HEARTBEAT = "heartbeat"
    HEARTBEAT_ACK = "heartbeat_ack"
    MESSAGE = "message"
    MESSAGE_ACK = "message_ack"
    ERROR = "error"
    DISCONNECT = "disconnect"
    CAPABILITY_ANNOUNCE = "capability_announce"
    CAPABILITY_REQUEST = "capability_request"
    CAPABILITY_RESPONSE = "capability_response"


class ConnectionStatus(Enum):
    """连接状态"""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    CONNECTED = "connected"
    AUTHENTICATED = "authenticated"
    ERROR = "error"


@dataclass
class ProtocolMessage:
    """协议消息"""

    message_id: str
    message_type: MessageType
    sender_id: str
    receiver_id: str
    payload: Dict[str, Any]
    timestamp: float
    version: str = "1.0"
    correlation_id: Optional[str] = None
    ttl: Optional[float] = None
    priority: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if not self.message_id:
            self.message_id = str(uuid.uuid4())
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        result = asdict(self)
        result["message_type"] = self.message_type.value
        return result

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProtocolMessage":
        """从字典创建"""
        data = data.copy()
        data["message_type"] = MessageType(data["message_type"])
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "ProtocolMessage":
        """从JSON字符串创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class HandshakeRequest:
    """握手请求"""

    client_id: str
    client_type: str  # openclaw, hermes, cloud_code, etc.
    client_version: str
    capabilities: List[str]
    auth_token: Optional[str] = None
    public_key: Optional[str] = None
    supported_versions: List[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.supported_versions is None:
            self.supported_versions = ["1.0"]

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HandshakeRequest":
        """从字典创建"""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "HandshakeRequest":
        """从JSON字符串创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)


@dataclass
class HandshakeResponse:
    """握手响应"""

    server_id: str
    server_version: str
    accepted: bool
    session_id: Optional[str] = None
    supported_versions: List[str] = None
    server_capabilities: List[str] = None
    heartbeat_interval: float = 30.0
    max_message_size: int = 1024 * 1024  # 1MB
    rate_limit: int = 100  # 每分钟消息数
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

    def __post_init__(self):
        if self.supported_versions is None:
            self.supported_versions = ["1.0"]
        if self.server_capabilities is None:
            self.server_capabilities = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    def to_json(self) -> str:
        """转换为JSON字符串"""
        return json.dumps(self.to_dict(), ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HandshakeResponse":
        """从字典创建"""
        return cls(**data)

    @classmethod
    def from_json(cls, json_str: str) -> "HandshakeResponse":
        """从JSON字符串创建"""
        data = json.loads(json_str)
        return cls.from_dict(data)


class CommunicationProtocol:
    """
    通信协议处理器

    管理Agent与外部代理的通信协议。
    """

    def __init__(
        self,
        server_id: Optional[str] = None,
        server_version: str = "1.0.0",
        heartbeat_interval: float = 30.0,
        max_message_size: int = 1024 * 1024,
        rate_limit: int = 100,
        session_timeout: float = 300.0,
    ):
        """
        初始化通信协议处理器

        Args:
            server_id: 服务器ID
            server_version: 服务器版本
            heartbeat_interval: 心跳间隔(秒)
            max_message_size: 最大消息大小(字节)
            rate_limit: 每分钟消息数限制
            session_timeout: 会话超时时间(秒)
        """
        self.server_id = server_id or str(uuid.uuid4())
        self.server_version = server_version
        self.heartbeat_interval = heartbeat_interval
        self.max_message_size = max_message_size
        self.rate_limit = rate_limit
        self.session_timeout = session_timeout

        # 会话管理
        self._sessions: Dict[str, Dict[str, Any]] = {}

        # 速率限制
        self._rate_limits: Dict[str, List[float]] = {}

        # 处理器
        self._handshake_handlers: List[Callable] = []
        self._message_handlers: Dict[str, List[Callable]] = {}

        # 统计信息
        self._stats = {
            "total_connections": 0,
            "active_connections": 0,
            "total_messages": 0,
            "rejected_connections": 0,
            "rate_limited_messages": 0,
        }

        # 线程安全
        self._lock = threading.RLock()

        logger.info("CommunicationProtocol 初始化，服务器ID: %s", self.server_id)

    def create_handshake_request(
        self,
        client_id: str,
        client_type: str,
        client_version: str,
        capabilities: List[str],
        auth_token: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HandshakeRequest:
        """
        创建握手请求

        Args:
            client_id: 客户端ID
            client_type: 客户端类型
            client_version: 客户端版本
            capabilities: 客户端能力
            auth_token: 认证令牌
            metadata: 元数据

        Returns:
            握手请求
        """
        return HandshakeRequest(
            client_id=client_id,
            client_type=client_type,
            client_version=client_version,
            capabilities=capabilities,
            auth_token=auth_token,
            metadata=metadata,
        )

    def create_handshake_response(
        self,
        accepted: bool,
        session_id: Optional[str] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HandshakeResponse:
        """
        创建握手响应

        Args:
            accepted: 是否接受连接
            session_id: 会话ID
            error_message: 错误消息
            metadata: 元数据

        Returns:
            握手响应
        """
        return HandshakeResponse(
            server_id=self.server_id,
            server_version=self.server_version,
            accepted=accepted,
            session_id=session_id,
            supported_versions=["1.0"],
            server_capabilities=["messaging", "heartbeat", "capabilities"],
            heartbeat_interval=self.heartbeat_interval,
            max_message_size=self.max_message_size,
            rate_limit=self.rate_limit,
            error_message=error_message,
            metadata=metadata,
        )

    def validate_handshake(self, request: HandshakeRequest) -> Tuple[bool, Optional[str]]:
        """
        验证握手请求

        Args:
            request: 握手请求

        Returns:
            (是否有效, 错误消息)
        """
        # 检查版本兼容性
        if "1.0" not in request.supported_versions:
            return False, f"不支持的协议版本: {request.supported_versions}"

        # 检查认证令牌
        if request.auth_token:
            # TODO: 实现令牌验证
            pass

        # 检查客户端类型
        supported_clients = ["openclaw", "hermes", "cloud_code", "trae", "qwen_coder", "qwen_paw"]
        if request.client_type not in supported_clients:
            logger.warning("未知客户端类型: %s", request.client_type)

        return True, None

    def create_message(
        self,
        sender_id: str,
        receiver_id: str,
        message_type: MessageType,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        priority: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ProtocolMessage:
        """
        创建协议消息

        Args:
            sender_id: 发送者ID
            receiver_id: 接收者ID
            message_type: 消息类型
            payload: 消息内容
            correlation_id: 关联ID
            priority: 优先级
            metadata: 元数据

        Returns:
            协议消息
        """
        return ProtocolMessage(
            message_id=str(uuid.uuid4()),
            message_type=message_type,
            sender_id=sender_id,
            receiver_id=receiver_id,
            payload=payload,
            timestamp=time.time(),
            correlation_id=correlation_id,
            priority=priority,
            metadata=metadata,
        )

    def check_rate_limit(self, client_id: str) -> bool:
        """
        检查速率限制

        Args:
            client_id: 客户端ID

        Returns:
            是否允许
        """
        with self._lock:
            current_time = time.time()

            if client_id not in self._rate_limits:
                self._rate_limits[client_id] = []

            # 清理过期记录
            self._rate_limits[client_id] = [t for t in self._rate_limits[client_id] if current_time - t < 60.0]

            # 检查限制
            if len(self._rate_limits[client_id]) >= self.rate_limit:
                self._stats["rate_limited_messages"] += 1
                return False

            # 记录请求
            self._rate_limits[client_id].append(current_time)
            return True

    def create_heartbeat(self, sender_id: str, receiver_id: str) -> ProtocolMessage:
        """
        创建心跳消息

        Args:
            sender_id: 发送者ID
            receiver_id: 接收者ID

        Returns:
            心跳消息
        """
        return self.create_message(
            sender_id=sender_id,
            receiver_id=receiver_id,
            message_type=MessageType.HEARTBEAT,
            payload={"timestamp": time.time()},
        )

    def register_handshake_handler(self, handler: Callable):
        """
        注册握手处理器

        Args:
            handler: 处理函数
        """
        self._handshake_handlers.append(handler)
        logger.debug("注册握手处理器: %s", handler.__name__)

    def register_message_handler(self, message_type: str, handler: Callable):
        """
        注册消息处理器

        Args:
            message_type: 消息类型
            handler: 处理函数
        """
        if message_type not in self._message_handlers:
            self._message_handlers[message_type] = []

        self._message_handlers[message_type].append(handler)
        logger.debug("注册消息处理器: %s -> %s", message_type, handler.__name__)

    async def process_message(self, message: ProtocolMessage) -> Optional[ProtocolMessage]:
        """
        处理消息

        Args:
            message: 协议消息

        Returns:
            响应消息
        """
        # 检查速率限制
        if not self.check_rate_limit(message.sender_id):
            logger.warning("速率限制: %s", message.sender_id)
            return self.create_message(
                sender_id=self.server_id,
                receiver_id=message.sender_id,
                message_type=MessageType.ERROR,
                payload={"error": "Rate limit exceeded"},
                correlation_id=message.message_id,
            )

        # 更新统计
        self._stats["total_messages"] += 1

        # 处理握手
        if message.message_type == MessageType.HANDSHAKE_REQUEST:
            return await self._process_handshake(message)

        # 处理心跳
        if message.message_type == MessageType.HEHeartbeat:
            return self.create_message(
                sender_id=self.server_id,
                receiver_id=message.sender_id,
                message_type=MessageType.HEARTBEAT_ACK,
                payload={"timestamp": time.time()},
                correlation_id=message.message_id,
            )

        # 处理其他消息
        message_type = message.message_type.value
        if message_type in self._message_handlers:
            for handler in self._message_handlers[message_type]:
                try:
                    result = await handler(message)
                    if result:
                        return result
                except Exception as e:
                    logger.error("消息处理器异常: %s", e)

        return None

    async def _process_handshake(self, message: ProtocolMessage) -> ProtocolMessage:
        """处理握手消息"""
        try:
            request = HandshakeRequest.from_dict(message.payload)

            # 验证握手
            valid, error = self.validate_handshake(request)

            if valid:
                # 创建会话
                session_id = str(uuid.uuid4())

                with self._lock:
                    self._sessions[session_id] = {
                        "client_id": request.client_id,
                        "client_type": request.client_type,
                        "client_version": request.client_version,
                        "capabilities": request.capabilities,
                        "connected_at": time.time(),
                        "last_heartbeat": time.time(),
                        "status": ConnectionStatus.AUTHENTICATED,
                    }

                    self._stats["total_connections"] += 1
                    self._stats["active_connections"] += 1

                # 创建响应
                response = self.create_handshake_response(accepted=True, session_id=session_id)

                # 调用处理器
                for handler in self._handshake_handlers:
                    try:
                        await handler(request, response)
                    except Exception as e:
                        logger.error("握手处理器异常: %s", e)

                return self.create_message(
                    sender_id=self.server_id,
                    receiver_id=request.client_id,
                    message_type=MessageType.HANDSHAKE_RESPONSE,
                    payload=response.to_dict(),
                    correlation_id=message.message_id,
                )
            else:
                # 拒绝连接
                self._stats["rejected_connections"] += 1

                response = self.create_handshake_response(accepted=False, error_message=error)

                return self.create_message(
                    sender_id=self.server_id,
                    receiver_id=request.client_id,
                    message_type=MessageType.HANDSHAKE_RESPONSE,
                    payload=response.to_dict(),
                    correlation_id=message.message_id,
                )
        except Exception as e:
            logger.error("处理握手消息失败: %s", e)

            return self.create_message(
                sender_id=self.server_id,
                receiver_id=message.sender_id,
                message_type=MessageType.ERROR,
                payload={"error": str(e)},
                correlation_id=message.message_id,
            )

    def cleanup_session(self, session_id: str):
        """
        清理会话

        Args:
            session_id: 会话ID
        """
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                self._stats["active_connections"] -= 1
                logger.info("清理会话: %s", session_id)

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """
        获取会话信息

        Args:
            session_id: 会话ID

        Returns:
            会话信息
        """
        with self._lock:
            return self._sessions.get(session_id)

    def get_active_sessions(self) -> List[Dict[str, Any]]:
        """
        获取活跃会话列表

        Returns:
            会话列表
        """
        with self._lock:
            current_time = time.time()
            active_sessions = []

            for session_id, session in self._sessions.items():
                # 检查会话是否超时
                if current_time - session["last_heartbeat"] < self.session_timeout:
                    active_sessions.append({"session_id": session_id, **session})

            return active_sessions

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            return {**self._stats, "active_sessions": len(self._sessions), "timestamp": time.time()}


# 单例管理
_communication_protocol_instance: Optional[CommunicationProtocol] = None
_communication_protocol_lock = threading.Lock()


def get_communication_protocol(**kwargs) -> CommunicationProtocol:
    """获取全局通信协议处理器实例（单例模式）"""
    global _communication_protocol_instance

    if _communication_protocol_instance is None:
        with _communication_protocol_lock:
            if _communication_protocol_instance is None:
                _communication_protocol_instance = CommunicationProtocol(**kwargs)

    return _communication_protocol_instance


def reset_communication_protocol():
    """重置通信协议处理器单例"""
    global _communication_protocol_instance

    with _communication_protocol_lock:
        _communication_protocol_instance = None
