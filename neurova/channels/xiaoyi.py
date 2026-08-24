"""
小艺 (华为云智能体) 渠道适配器

支持华为云智能体平台 WebSocket 连接

API 文档: https://developer.huawei.com/consumer/cn/
"""

import asyncio
import hashlib
import hmac
import json
from neurova.core.logger import get_logger
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import websockets

from .base import ChannelAdapter, ChannelConfig

logger = get_logger(__name__)


class XiaoYiAdapter(ChannelAdapter):
    """
    小艺 (华为云智能体) 渠道适配器

    支持:
    - 华为云智能体平台 WebSocket 连接
    - AK/SK 签名认证
    - 消息发送和接收
    """

    channel = "xiaoyi"

    def __init__(self):
        super().__init__()
        self.config: Optional[ChannelConfig] = None
        self.authenticated = False
        self.ws = None
        self.bot_prefix = "@bot"
        self.show_tool_messages = True
        self.show_thinking = True
        self._receive_task = None
        self._connected = False

    async def authenticate(self, config: Dict[str, Any]) -> bool:
        """
        认证小艺 (华为云智能体)

        参数:
        config: {
            "access_key": "Access Key (AK)",
            "secret_key": "Secret Key (SK)",
            "agent_id": "Agent ID",
            "ws_url": "WebSocket URL",
            "bot_prefix": "@bot",
            "show_tool_messages": "true/false",
            "show_thinking": "true/false",
        }
        """
        try:
            self.config = ChannelConfig(
                channel="xiaoyi",
                config={
                    "access_key": config.get("access_key"),
                    "secret_key": config.get("secret_key"),
                    "agent_id": config.get("agent_id"),
                    "ws_url": config.get("ws_url", "wss://hag.cloud.huawei.com/openclaw/v1/ws/link"),
                    "bot_prefix": config.get("bot_prefix", "@bot"),
                    "show_tool_messages": config.get("show_tool_messages", "true"),
                    "show_thinking": config.get("show_thinking", "true"),
                },
            )

            # 验证必需参数
            if not all(
                [
                    self.config.config.get("access_key"),
                    self.config.config.get("secret_key"),
                    self.config.config.get("agent_id"),
                ]
            ):
                logger.error("小艺认证失败: AK, SK, Agent ID 不能为空")
                return False

            self.authenticated = True
            logger.info("小艺认证成功")
            return True

        except Exception as e:
            logger.error("小艺认证失败: %s", e)
            return False

    def _generate_signature(self, method: str, url: str, body: str = "", content_type: str = "") -> Dict[str, str]:
        """
        生成华为云 AK/SK 签名

        参数:
        method: HTTP 方法 (GET/POST)
        url: 请求 URL
        body: 请求体
        content_type: 内容类型

        返回:
        签名字典，包含 Authorization 等头部
        """
        try:
            # 解析URL
            parsed = urlparse(url)
            host = parsed.hostname
            path = parsed.path

            # 生成时间戳
            now = datetime.now(timezone.utc)
            date_str = now.strftime("%Y%m%dT%H%M%SZ")

            # 生成随机数
            nonce = str(uuid.uuid4())

            # 构建签名字符串
            string_to_sign = (
                f"{method}\n{path}\n\ncontent-type:{content_type}\nhost:{host}\nx-date:{date_str}\nx-nonce:{nonce}\n"
            )

            # HMAC-SHA256签名
            secret_key = self.config.config.get("secret_key")
            signature = hmac.new(secret_key.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

            # 构建Authorization头部
            access_key = self.config.config.get("access_key")
            authorization = f"SDK-HMAC-SHA256 Access={access_key}, SignedHeaders=content-type;host;x-date;x-nonce, Signature={signature}"

            return {
                "Authorization": authorization,
                "X-Date": date_str,
                "X-Nonce": nonce,
                "Content-Type": content_type,
                "Host": host,
            }

        except Exception as e:
            logger.error("生成签名失败: %s", e)
            return {}

    async def _init_connection(self) -> bool:
        """初始化 WebSocket 连接"""
        try:
            # 尝试导入websockets
            try:
                pass
            except ImportError:
                logger.warning("websockets 未安装，使用模拟模式")
                self._connected = True
                return True

            # 初始化WebSocket连接
            await self._async_init_connection()
            return True

        except Exception as e:
            logger.error("小艺连接初始化失败: %s", e)
            return False

    async def _async_init_connection(self):
        """异步初始化 WebSocket 连接"""
        try:
            ws_url = self.config.config.get("ws_url")

            # 生成认证头
            headers = self._generate_signature("GET", ws_url)

            # 建立WebSocket连接
            self.ws = await websockets.connect(ws_url, extra_headers=headers)
            self._connected = True

            logger.info("小艺 WebSocket 连接成功: %s", ws_url)

            # 启动接收消息循环
            self._receive_task = asyncio.create_task(self._receive_loop())

        except Exception as e:
            logger.error("小艺 WebSocket 连接失败: %s", e)
            self._connected = False
            raise

    async def _receive_loop(self):
        """WebSocket 消息接收循环"""
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    await self._handle_message(data)
                except json.JSONDecodeError:
                    logger.warning("小艺收到非 JSON 消息: %s", message)
        except websockets.ConnectionClosed:
            logger.info("小艺 WebSocket 连接已关闭")
        except Exception as e:
            logger.error("小艺消息接收异常: %s", e)
        finally:
            self._connected = False

    async def _handle_message(self, data: Dict[str, Any]):
        """处理收到的消息"""
        try:
            msg_type = data.get("type")

            if msg_type == "message":
                # 处理消息
                content = data.get("content", "")
                session_id = data.get("session_id", "")

                logger.info("小艺收到消息: %s", content)

                # 发送消息事件
                if hasattr(self, "on_message"):
                    await self.on_message(content, {"session_id": session_id, "channel": "xiaoyi"})

            elif msg_type == "session_start":
                session_id = data.get("session_id", "")
                logger.info("小艺会话开始: %s", session_id)

            elif msg_type == "session_end":
                logger.info("小艺会话结束")

            elif msg_type == "error":
                error_msg = data.get("message", "Unknown error")
                logger.error("小艺错误: %s", error_msg)

            else:
                logger.warning("小艺收到未知消息类型: %s", msg_type)

        except Exception as e:
            logger.error("处理小艺消息失败: %s", e)

    async def send_message(self, message: str, session_id: str = None, **kwargs) -> bool:
        """发送小艺消息"""
        if not self.authenticated:
            logger.warning("小艺未初始化")
            return False

        try:
            if not self._connected:
                logger.warning("[小艺模拟] 发送消息: ", message)
                return True

            # 构建消息
            msg_data = {
                "type": "message",
                "session_id": session_id or str(uuid.uuid4()),
                "content": message,
                "message_id": str(uuid.uuid4()),
                "timestamp": datetime.now().isoformat(),
                "metadata": kwargs,
            }

            # 发送消息
            await self.ws.send(json.dumps(msg_data))
            logger.info("小艺消息发送成功: %s...", message[:50])
            return True

        except Exception as e:
            logger.error("小艺消息发送异常: %s", e)
            return False

    async def receive_message(self) -> Optional[Dict[str, Any]]:
        """接收小艺消息"""
        try:
            if not self._connected:
                return None

            # 等待消息
            message = await self.ws.recv()
            return json.loads(message)

        except Exception as e:
            logger.error("小艺消息接收异常: %s", e)
            return None

    def parse_raw_message(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        解析小艺原始消息

        小艺消息格式:
        {
            "type": "message",
            "session_id": "会话ID",
            "message_id": "消息ID",
            "user_id": "用户ID",
            "content": "消息内容",
            "timestamp": "时间戳",
            "metadata": {
                "device": "设备信息",
                "location": "位置信息"
            }
        }
        """
        try:
            if not isinstance(raw_data, dict):
                logger.error("解析小艺消息失败: 无效JSON格式")
                return {}

            # 提取字段
            message_id = raw_data.get("message_id", str(uuid.uuid4()))
            session_id = raw_data.get("session_id", "")
            user_id = raw_data.get("user_id", "")
            content = raw_data.get("content", "")
            timestamp = raw_data.get("timestamp", datetime.now().isoformat())
            metadata = raw_data.get("metadata", {})

            # 构建标准消息格式
            parsed = {
                "id": message_id,
                "session_id": session_id,
                "sender_id": user_id,
                "content": content,
                "timestamp": timestamp,
                "channel": "xiaoyi",
                "metadata": {
                    "device": metadata.get("device", ""),
                    "location": metadata.get("location", ""),
                    "ws_url": self.config.config.get("ws_url") if self.config else "",
                },
            }

            return parsed

        except Exception as e:
            logger.error("解析小艺消息失败: %s", e)
            return {}

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置"""
        if not self.config:
            return {}

        return {
            "channel": "xiaoyi",
            "access_key": self.config.config.get("access_key"),
            "agent_id": self.config.config.get("agent_id"),
            "ws_url": self.config.config.get("ws_url"),
            "bot_prefix": self.bot_prefix,
            "show_tool_messages": self.show_tool_messages,
            "show_thinking": self.show_thinking,
            "authenticated": self.authenticated,
        }

    def update_config(self, config_updates: Dict[str, Any]) -> bool:
        """更新配置"""
        try:
            if not self.config:
                return False

            # 更新配置
            for key, value in config_updates.items():
                if key in [
                    "access_key",
                    "secret_key",
                    "agent_id",
                    "ws_url",
                    "bot_prefix",
                    "show_tool_messages",
                    "show_thinking",
                ]:
                    self.config.config[key] = value

            return True

        except Exception as e:
            logger.error("更新配置失败: %s", e)
            return False


def create_xiaoyi_adapter(access_key: str, secret_key: str, agent_id: str) -> XiaoYiAdapter:
    """创建小艺适配器"""
    adapter = XiaoYiAdapter()
    adapter.config = ChannelConfig(
        channel="xiaoyi", config={"access_key": access_key, "secret_key": secret_key, "agent_id": agent_id}
    )
    return adapter
