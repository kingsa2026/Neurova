"""
QClaw 消息渠道适配器

实现 QClaw 消息的发送和接收逻辑。
通过 QClaw 网关与 QClaw 管家通信。
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, Optional

try:
    pass

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False
    logging.warning("requests 库未安装，QClaw 适配器将使用模拟模式")

from neurova.channels import ChannelAdapter, ContentType, MessageChannel, UnifiedMessage
from neurova.channels.qclaw_service import get_qclaw_service

logger = logging.getLogger(__name__)

# QClaw 网关地址（应配置化，不要硬编码）
QCLAW_API_BASE = "https://jprx.m.qq.com"


class QClawAdapter(ChannelAdapter):
    """
    QClaw 消息渠道适配器

    通过 QClaw 网关与 QClaw 管家通信。
    支持文本、图片、语音、视频等消息类型。
    """

    @property
    def channel(self) -> MessageChannel:
        """返回渠道类型"""
        return MessageChannel.QCLAW

    def __init__(self):
        """初始化 QClaw 适配器"""
        # 认证相关
        self.app_id = ""
        self.app_secret = ""
        self.access_token = ""
        self.token_expire_time = 0

        # 配置
        self.bot_prefix = "Kai"
        self.show_tool_messages = True
        self.show_thinking = True
        self.media_directory = ""

        # 绑定ID（用于多用户隔离）
        self.binding_id = None

        # QClaw 服务
        self.qclaw_service = None

        logger.info("QClaw 适配器已初始化")

    def authenticate(self, config: Dict[str, Any]) -> bool:
        """
        认证 QClaw 渠道

        参数:
            config: 配置字典，包含:
                - app_id: QClaw 应用ID
                - app_secret: QClaw 应用密钥
                - binding_id: 绑定记录ID（用于多用户隔离）

        返回:
            认证成功返回 True
        """
        self.app_id = config.get("app_id", "")
        self.app_secret = config.get("app_secret", "")
        self.binding_id = config.get("binding_id")

        if not self.app_id or not self.app_secret:
            logger.error("QClaw 认证失败: 缺少 app_id 或 app_secret")
            return False

        # 获取 QClaw 服务
        self.qclaw_service = get_qclaw_service()

        # 验证凭证
        verify_result = self.qclaw_service.verify_credentials(self.app_id, self.app_secret)

        if not verify_result["valid"]:
            logger.error("QClaw 认证失败: %s", verify_result['error'])
            return False

        # 获取 access_token
        access_token = self.qclaw_service.get_access_token(self.app_id, self.app_secret)

        if not access_token:
            logger.error("QClaw 认证失败: 无法获取 access_token")
            return False

        self.access_token = access_token
        logger.info("QClaw 认证成功 (app_id: %s****)", self.app_id[:4])
        return True

    def send_message(self, message: UnifiedMessage) -> bool:
        """
        发送消息到 QClaw

        参数:
            message: 统一消息对象

        返回:
            发送成功返回 True
        """
        if not self.qclaw_service:
            logger.error("QClaw 服务未初始化")
            return False

        # 获取 chat_id（从消息元数据中）
        chat_id = message.metadata.get("chat_id", "")
        if not chat_id:
            logger.error("发送消息失败: 缺少 chat_id")
            return False

        # 根据内容类型发送不同消息
        if message.content_type == ContentType.TEXT:
            result = self.qclaw_service.send_message(
                app_id=self.app_id,
                app_secret=self.app_secret,
                chat_id=chat_id,
                content=message.content,
                content_type="text",
            )
        elif message.content_type == ContentType.IMAGE:
            # 发送图片
            result = self._send_media_message(chat_id, message, "image")
        elif message.content_type == ContentType.VOICE:
            # 发送语音
            result = self._send_media_message(chat_id, message, "voice")
        elif message.content_type == ContentType.VIDEO:
            # 发送视频
            result = self._send_media_message(chat_id, message, "video")
        elif message.content_type == ContentType.FILE:
            # 发送文件
            result = self._send_media_message(chat_id, message, "file")
        else:
            logger.warning("不支持的消息类型: %s", message.content_type)
            return False

        if result["success"]:
            logger.debug("消息发送成功: %s", result.get('message_id'))
            return True
        else:
            logger.error("消息发送失败: %s", result.get('error'))
            return False

    def receive_message(self) -> Optional[UnifiedMessage]:
        """
        接收消息（Webhook 或轮询）

        返回:
            统一消息对象，无消息返回 None
        """
        # QClaw 使用 Webhook 推送消息，所以这里不需要主动轮询
        # 消息通过 /api/v1/qclaw/message/callback 接口接收
        logger.debug("QClaw 使用 Webhook 接收消息，无需轮询")
        return None

    def parse_raw_message(self, raw_data: Any) -> UnifiedMessage:
        """
        解析原始消息为统一消息

        参数:
            raw_data: QClaw 原始消息数据（字典或JSON字符串）

        返回:
            统一消息对象
        """
        # 解析原始数据
        if isinstance(raw_data, str):
            try:
                data = json.loads(raw_data)
            except json.JSONDecodeError:
                logger.error("解析 QClaw 消息失败: 无效的 JSON")
                return self._create_error_message("无效的消息格式")
        else:
            data = raw_data

        # 提取消息字段（根据实际 QClaw 消息格式调整）
        message_id = data.get("message_id", f"qclaw_{int(time.time())}")
        chat_id = data.get("chat_id", "")
        user_id = data.get("from", {}).get("id", "unknown")
        content = data.get("content", "")
        msg_type = data.get("type", "text")

        # 确定内容类型
        content_type_map = {
            "text": ContentType.TEXT,
            "image": ContentType.IMAGE,
            "voice": ContentType.VOICE,
            "video": ContentType.VIDEO,
            "file": ContentType.FILE,
        }
        content_type = content_type_map.get(msg_type, ContentType.TEXT)

        # 构建统一消息
        message = UnifiedMessage(
            message_id=message_id,
            channel=MessageChannel.QCLAW,
            chat_id=chat_id,
            user_id=user_id,
            agent_id="default",  # 默认 agent，实际应从配置或绑定信息中获取
            content=content,
            content_type=content_type,
            timestamp=datetime.now(),
            metadata={
                "raw_data": data,
                "chat_id": chat_id,
            },
        )

        logger.debug("解析 QClaw 消息: %s, 类型: %s", message_id, msg_type)
        return message

    def get_channel_config(self) -> Dict[str, Any]:
        """获取渠道配置信息"""
        return {
            "app_id": f"{self.app_id[:4]}****{self.app_id[-4:]}" if self.app_id else "",
            "authenticated": bool(self.access_token),
            "binding_id": self.binding_id,
        }

    def _send_media_message(self, chat_id: str, message: UnifiedMessage, media_type: str) -> Dict[str, Any]:
        """
        发送媒体消息

        参数:
            chat_id: 聊天ID
            message: 统一消息对象
            media_type: 媒体类型（image/voice/video/file）

        返回:
            发送结果字典
        """
        if not self.qclaw_service:
            return {"success": False, "error": "QClaw 服务未初始化"}

        # 获取媒体文件 URL 或路径
        file_url = message.file_url
        if not file_url and message.content_type == ContentType.AI_IMAGE:
            # AI 生成的图片
            file_url = message.metadata.get("image_url", "")

        if not file_url:
            return {"success": False, "error": "缺少媒体文件 URL"}

        # 调用 QClaw 服务发送媒体消息
        # 注意：这里需要根据 QClaw API 的实际实现调整
        if not REQUESTS_AVAILABLE:
            # 模拟模式
            logger.warning("模拟模式：模拟发送媒体消息成功")
            return {"success": True, "message_id": f"mock_media_{int(time.time())}"}

        try:
            # 获取 access_token
            access_token = self.qclaw_service.get_access_token(self.app_id, self.app_secret)
            if not access_token:
                return {"success": False, "error": "无法获取 access_token"}

            # 调用 QClaw 媒体消息发送接口（根据实际API调整）
            response = requests.post(
                f"{QCLAW_API_BASE}/api/v1/message/send_media",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {access_token}"},
                json={"chat_id": chat_id, "media_type": media_type, "file_url": file_url, "caption": message.content},
                timeout=10,
            )

            if response.status_code == 200:
                data = response.json()
                if data.get("common", {}).get("code") == 0:
                    return {"success": True, "message_id": data.get("data", {}).get("message_id")}
                else:
                    return {"success": False, "error": data.get("common", {}).get("message", "发送失败")}
            else:
                return {"success": False, "error": f"HTTP {response.status_code}"}

        except Exception as e:
            logger.error("发送媒体消息到 QClaw 失败: %s", e)
            return {"success": False, "error": str(e)}

    def _create_error_message(self, error_msg: str) -> UnifiedMessage:
        """
        创建错误消息

        参数:
            error_msg: 错误信息

        返回:
            错误消息的统一消息对象
        """
        return UnifiedMessage(
            message_id=f"error_{int(time.time())}",
            channel=MessageChannel.QCLAW,
            chat_id="unknown",
            user_id="unknown",
            agent_id="default",
            content=error_msg,
            content_type=ContentType.SYSTEM,
            timestamp=datetime.now(),
        )
