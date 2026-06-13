"""
WebSocket 消息渠道适配器

支持:
- 通用 WebSocket 客户端连接
- WSS (WebSocket Secure) 加密连接
- 自定义 Headers 和 Subprotocols
- 自动重连机制
- 心跳保活 (Ping/Pong)
- 消息队列缓冲

依赖:
pip install websockets
"""

import asyncio
import json
import logging
import ssl
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

try:
    import websockets

    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage


class WebSocketAdapter(ChannelAdapter):
    """
    WebSocket 消息渠道适配器

    支持:
    - 通用 WebSocket 客户端连接
    - WSS (WebSocket Secure) 加密连接
    - 自定义 Headers 和 Subprotocols
    - 自动重连机制
    - 心跳保活 (Ping/Pong)
    - 消息队列缓冲
    """

    @property
    def channel(self) -> MessageChannel:
        return MessageChannel.WEBSOCKET

    def __init__(self):
        # 基础配置
        self.bot_prefix = "@bot"
        self.show_tool_messages = True
        self.show_thinking = True

        # WebSocket 连接配置
        self.ws_url = ""
        self.headers: Dict[str, str] = {}
        self.subprotocols: List[str] = []
        self.ping_interval = 20  # 心跳间隔 (秒)
        self.ping_timeout = 10  # 心跳超时 (秒)
        self.close_timeout = 10  # 关闭超时 (秒)

        # 重连配置
        self.reconnect_enabled = True
        self.reconnect_interval = 5  # 重连间隔 (秒)
        self.reconnect_max_attempts = 0  # 最大重连次数 (0=无限)
        self.reconnect_attempts = 0

        # 认证配置
        self.auth_type = "none"  # none / bearer / basic / api_key
        self.auth_token = ""
        self.auth_username = ""
        self.auth_password = ""
        self.api_key_header = "X-API-Key"
        self.api_key_value = ""

        # 消息配置
        self.message_format = "json"  # json / text / binary
        self.content_field = "content"  # JSON 消息中内容的字段名
        self.user_id_field = "user_id"  # JSON 消息中用户 ID 的字段名

        # 内部状态
        self._initialized = False
        self._ws_connection = None
        self._connected = False
        self._receive_task = None
        self._message_queue: List[UnifiedMessage] = []
        self._client_id = f"ws_{int(time.time())}"
        self._event_loop = None

    def authenticate(self, config: Dict[str, str]) -> bool:
        """
        认证 WebSocket 连接

        参数:
        config: {
            "bot_prefix": "@bot",
            "show_tool_messages": "true/false",
            "show_thinking": "true/false",
            "ws_url": "WebSocket 服务器地址",
            "headers": "自定义 Headers (JSON)",
            "subprotocols": "子协议列表 (逗号分隔)",
            "ping_interval": "20",
            "ping_timeout": "10",
            "close_timeout": "10",
            "reconnect_enabled": "true/false",
            "reconnect_interval": "5",
            "reconnect_max_attempts": "0",
            "auth_type": "none/bearer/basic/api_key",
            "auth_token": "认证 Token",
            "auth_username": "用户名",
            "auth_password": "密码",
            "api_key_header": "X-API-Key",
            "api_key_value": "API Key 值",
            "message_format": "json/text/binary",
            "content_field": "content",
            "user_id_field": "user_id",
        }
        """
        # 基础配置
        self.bot_prefix = config.get("bot_prefix", "@bot")
        self.show_tool_messages = config.get("show_tool_messages", "true").lower() == "true"
        self.show_thinking = config.get("show_thinking", "true").lower() == "true"

        # WebSocket 连接配置
        self.ws_url = config.get("ws_url", "")

        # 解析 Headers
        headers_str = config.get("headers", "")
        if headers_str:
            try:
                self.headers = json.loads(headers_str)
            except json.JSONDecodeError:
                logging.warning("Headers 解析失败: %s", headers_str)

        # 解析子协议
        subprotocols_str = config.get("subprotocols", "")
        if subprotocols_str:
            self.subprotocols = [s.strip() for s in subprotocols_str.split(",") if s.strip()]

        self.ping_interval = int(config.get("ping_interval", "20"))
        self.ping_timeout = int(config.get("ping_timeout", "10"))
        self.close_timeout = int(config.get("close_timeout", "10"))

        # 重连配置
        self.reconnect_enabled = config.get("reconnect_enabled", "true").lower() == "true"
        self.reconnect_interval = int(config.get("reconnect_interval", "5"))
        self.reconnect_max_attempts = int(config.get("reconnect_max_attempts", "0"))

        # 认证配置
        self.auth_type = config.get("auth_type", "none")
        self.auth_token = config.get("auth_token", "")
        self.auth_username = config.get("auth_username", "")
        self.auth_password = config.get("auth_password", "")
        self.api_key_header = config.get("api_key_header", "X-API-Key")
        self.api_key_value = config.get("api_key_value", "")

        # 消息配置
        self.message_format = config.get("message_format", "json")
        self.content_field = config.get("content_field", "content")
        self.user_id_field = config.get("user_id_field", "user_id")

        if not self.ws_url:
            logging.error("WebSocket 认证失败: ws_url 不能为空")
            return False

        return self._init_connection()

    def _get_auth_headers(self) -> Dict[str, str]:
        """获取认证 Headers"""
        headers = dict(self.headers)  # 复制自定义 headers

        if self.auth_type == "bearer" and self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        elif self.auth_type == "basic" and self.auth_username:
            import base64

            credentials = base64.b64encode(f"{self.auth_username}:{self.auth_password}".encode()).decode()
            headers["Authorization"] = f"Basic {credentials}"
        elif self.auth_type == "api_key" and self.api_key_value:
            headers[self.api_key_header] = self.api_key_value

        return headers

    def _init_connection(self) -> bool:
        """初始化 WebSocket 连接"""
        if not WEBSOCKETS_AVAILABLE:
            logging.warning("websockets 未安装，WebSocket 模式不可用")
            logging.info("安装命令: pip install websockets")
            self._initialized = True  # 模拟初始化
            return True

        # 获取事件循环
        try:
            self._event_loop = asyncio.get_event_loop()
        except RuntimeError:
            self._event_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._event_loop)

        # 异步初始化连接
        try:
            self._event_loop.run_until_complete(self._async_init_connection())
            return True
        except Exception as e:
            logging.error("WebSocket 连接初始化失败: %s", e)
            self._initialized = True  # 允许继续，连接可以后续重试
            return True

    async def _async_init_connection(self):
        """异步初始化 WebSocket 连接"""
        try:
            # 构建 SSL 上下文 (如果是 wss://)
            ssl_context = None
            if self.ws_url.startswith("wss://"):
                ssl_context = ssl.create_default_context()

            # 获取认证 headers
            extra_headers = self._get_auth_headers()

            # 建立 WebSocket 连接
            self._ws_connection = await websockets.connect(
                self.ws_url,
                extra_headers=extra_headers,
                subprotocols=self.subprotocols if self.subprotocols else None,
                ping_interval=self.ping_interval if self.ping_interval > 0 else None,
                ping_timeout=self.ping_timeout if self.ping_timeout > 0 else None,
                close_timeout=self.close_timeout,
                ssl=ssl_context,
            )

            self._connected = True
            self._reconnect_attempts = 0
            logging.info("WebSocket 连接成功: %s", self.ws_url)
            self._initialized = True

            # 启动消息接收循环
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            logging.error("WebSocket 连接失败: %s", e)
            raise

    async def _receive_loop(self):
        """WebSocket 消息接收循环"""
        if not self._ws_connection:
            return

        try:
            async for message in self._ws_connection:
                try:
                    unified_msg = self._parse_websocket_message(message)
                    if unified_msg:
                        self._message_queue.append(unified_msg)
                except Exception as e:
                    logging.error("WebSocket 消息解析异常: %s", e)
        except websockets.exceptions.ConnectionClosed as e:
            logging.warning("WebSocket 连接已关闭: %s", e)
            self._connected = False
            self._ws_connection = None

            # 自动重连
            if self.reconnect_enabled:
                await self._reconnect()
        except Exception as e:
            logging.error("WebSocket 接收循环异常: %s", e)
            self._connected = False

    async def _reconnect(self):
        """自动重连"""
        if self.reconnect_max_attempts > 0 and self._reconnect_attempts >= self.reconnect_max_attempts:
            logging.error("WebSocket 达到最大重连次数 (%s)，停止重连", self.reconnect_max_attempts)
            return

        self._reconnect_attempts += 1
        logging.info("WebSocket 尝试重连 (%s/%s)...", self._reconnect_attempts, self.reconnect_max_attempts or '∞')

        await asyncio.sleep(self.reconnect_interval)

        try:
            await self._async_init_connection()
            logging.info("WebSocket 重连成功")
        except Exception as e:
            logging.error("WebSocket 重连失败: %s", e)
            # 继续尝试重连
            if self.reconnect_enabled:
                asyncio.create_task(self._reconnect())

    def _parse_websocket_message(self, raw_message: str) -> Optional[UnifiedMessage]:
        """解析 WebSocket 消息"""
        try:
            if self.message_format == "json":
                data = json.loads(raw_message)
                content = data.get(self.content_field, raw_message)
                user_id = data.get(self.user_id_field, self._client_id)
                message_id = data.get("message_id", f"ws_{int(time.time())}")
                timestamp_str = data.get("timestamp", "")
            else:
                # 纯文本或二进制模式
                data = {"content": raw_message}
                content = raw_message
                user_id = self._client_id
                message_id = f"ws_{int(time.time())}"
                timestamp_str = ""

            # 解析时间戳
            timestamp = None
            if timestamp_str:
                try:
                    timestamp = datetime.fromisoformat(timestamp_str)
                except ValueError:
                    timestamp = datetime.now()
            else:
                timestamp = datetime.now()

            return UnifiedMessage(
                message_id=message_id,
                channel=MessageChannel.WEBSOCKET,
                chat_id=user_id,
                user_id=user_id,
                agent_id="",
                content=content,
                content_type=ContentType.TEXT,
                timestamp=timestamp,
                global_user_id=f"ws:{user_id}",
                session_id=f"ws:{self._client_id}",
                raw_message=raw_message,
                metadata={
                    "ws_url": self.ws_url,
                    "message_format": self.message_format,
                    "parsed_data": data if self.message_format == "json" else None,
                },
            )
        except json.JSONDecodeError:
            # 如果不是有效的 JSON，作为纯文本处理
            return UnifiedMessage(
                message_id=f"ws_{int(time.time())}",
                channel=MessageChannel.WEBSOCKET,
                chat_id=self._client_id,
                user_id=self._client_id,
                agent_id="",
                content=raw_message,
                content_type=ContentType.TEXT,
                timestamp=datetime.now(),
                global_user_id=f"ws:{self._client_id}",
                session_id=f"ws:{self._client_id}",
                raw_message=raw_message,
                metadata={
                    "ws_url": self.ws_url,
                    "message_format": "text",
                },
            )

    def send_message(self, message: UnifiedMessage) -> bool:
        """发送 WebSocket 消息"""
        if not self._initialized or not self._connected:
            logging.error("WebSocket 未连接")
            return False

        if not WEBSOCKETS_AVAILABLE or not self._ws_connection:
            logging.info("[WebSocket模拟] 发送消息: %s", message.content[:50])
            return True

        try:
            # 构建消息体
            if self.message_format == "json":
                payload = json.dumps(
                    {
                        "message_id": message.message_id,
                        self.content_field: message.content,
                        "content_type": message.content_type.value,
                        "timestamp": datetime.now().isoformat(),
                        "chat_id": message.chat_id,
                        "agent_id": message.agent_id,
                        **(message.metadata or {}),
                    },
                    ensure_ascii=False,
                )
            else:
                payload = message.content

            # 异步发送消息
            self._event_loop.run_until_complete(self._ws_connection.send(payload))
            return True
        except Exception as e:
            logging.error("WebSocket 消息发送异常: %s", e)
            return False

    def receive_message(self) -> Optional[UnifiedMessage]:
        """接收 WebSocket 消息"""
        if self._message_queue:
            return self._message_queue.pop(0)
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """解析 WebSocket 原始消息"""
        if isinstance(raw_data, str):
            return self._parse_websocket_message(raw_data)

        # 如果是字典，尝试转换为 JSON 字符串
        if isinstance(raw_data, dict):
            return self._parse_websocket_message(json.dumps(raw_data, ensure_ascii=False))

        return None

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置"""
        return {
            "channel": self.channel.value,
            "ws_url": self.ws_url,
            "headers": self.headers,
            "subprotocols": self.subprotocols,
            "ping_interval": self.ping_interval,
            "ping_timeout": self.ping_timeout,
            "reconnect_enabled": self.reconnect_enabled,
            "reconnect_interval": self.reconnect_interval,
            "auth_type": self.auth_type,
            "message_format": self.message_format,
            "connected": self._connected,
            "authenticated": self._initialized,
        }

    def update_config(self, config_updates: Dict):
        """更新配置"""
        if "ws_url" in config_updates:
            self.ws_url = config_updates["ws_url"]
        if "headers" in config_updates:
            try:
                self.headers = json.loads(config_updates["headers"])
            except json.JSONDecodeError as e:
                logging.warning("WebSocket headers JSON 解析失败: %s", e)
        if "subprotocols" in config_updates:
            self.subprotocols = [s.strip() for s in config_updates["subprotocols"].split(",") if s.strip()]
        if "ping_interval" in config_updates:
            self.ping_interval = int(config_updates["ping_interval"])
        if "ping_timeout" in config_updates:
            self.ping_timeout = int(config_updates["ping_timeout"])
        if "reconnect_enabled" in config_updates:
            self.reconnect_enabled = config_updates["reconnect_enabled"]
        if "reconnect_interval" in config_updates:
            self.reconnect_interval = int(config_updates["reconnect_interval"])
        if "auth_type" in config_updates:
            self.auth_type = config_updates["auth_type"]
        if "auth_token" in config_updates:
            self.auth_token = config_updates["auth_token"]
        if "message_format" in config_updates:
            self.message_format = config_updates["message_format"]
        if "content_field" in config_updates:
            self.content_field = config_updates["content_field"]
        if "user_id_field" in config_updates:
            self.user_id_field = config_updates["user_id_field"]

    def disconnect(self):
        """断开 WebSocket 连接"""
        if self._ws_connection:
            self._event_loop.run_until_complete(self._ws_connection.close())
            self._connected = False
            logging.info("WebSocket 连接已断开")


def create_websocket_adapter(ws_url: str = "", auth_type: str = "none", auth_token: str = "") -> WebSocketAdapter:
    """创建 WebSocket 适配器"""
    adapter = WebSocketAdapter()
    if ws_url:
        adapter.authenticate(
            {
                "ws_url": ws_url,
                "auth_type": auth_type,
                "auth_token": auth_token,
            }
        )
    return adapter
