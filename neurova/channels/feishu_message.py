"""
飞书消息收发 Mixin

提供消息发送、接收、解析和策略过滤功能。
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 消息类型映射
MESSAGE_TYPE_MAP = {
    "text": "text",
    "image": "image",
    "file": "file",
    "audio": "audio",
    "media": "media",
    "sticker": "sticker",
    "interactive": "interactive",
    "share_chat": "share_chat",
    "share_user": "share_user",
    "system": "system",
}


class MessageMixin:
    """
    飞书消息 Mixin

    提供:
    - 消息发送 (文本、富文本、图片、文件)
    - 消息解析
    - 消息策略过滤
    """

    async def send_text_message(
        self,
        chat_id: str,
        text: str,
        **kwargs,
    ) -> Optional[str]:
        """
        发送文本消息

        参数:
            chat_id: 会话 ID
            text: 消息文本

        返回:
            str: 消息 ID
        """
        content = json.dumps({"text": text})
        return await self.send_message(
            chat_id=chat_id,
            content=content,
            message_type="text",
            **kwargs,
        )

    async def send_rich_text_message(
        self,
        chat_id: str,
        title: str,
        content: List[List[Dict[str, Any]]],
        **kwargs,
    ) -> Optional[str]:
        """
        发送富文本消息

        参数:
            chat_id: 会话 ID
            title: 标题
            content: 富文本内容 (二维数组结构)

        返回:
            str: 消息 ID
        """
        msg_content = {
            "zh_cn": {
                "title": title,
                "content": content,
            }
        }
        return await self.send_message(
            chat_id=chat_id,
            content=json.dumps(msg_content),
            message_type="post",
            **kwargs,
        )

    async def send_image_message(
        self,
        chat_id: str,
        image_key: str,
        **kwargs,
    ) -> Optional[str]:
        """
        发送图片消息

        参数:
            chat_id: 会话 ID
            image_key: 图片 key (需先上传)

        返回:
            str: 消息 ID
        """
        content = json.dumps({"image_key": image_key})
        return await self.send_message(
            chat_id=chat_id,
            content=content,
            message_type="image",
            **kwargs,
        )

    async def send_card_message(
        self,
        chat_id: str,
        card: Dict[str, Any],
        **kwargs,
    ) -> Optional[str]:
        """
        发送卡片消息

        参数:
            chat_id: 会话 ID
            card: 卡片 JSON

        返回:
            str: 消息 ID
        """
        return await self.send_message(
            chat_id=chat_id,
            content=json.dumps(card),
            message_type="interactive",
            **kwargs,
        )

    def parse_message_content(self, message_type: str, content: str) -> str:
        """
        解析消息内容

        参数:
            message_type: 消息类型
            content: 消息内容 JSON 字符串

        返回:
            str: 解析后的文本
        """
        try:
            if message_type == "text":
                content_json = json.loads(content)
                return content_json.get("text", "")

            elif message_type == "post":
                # 富文本: 提取所有文本元素
                content_json = json.loads(content)
                texts = []
                for lang_content in content_json.values():
                    if isinstance(lang_content, dict):
                        lang_content = lang_content.get("content", [])
                    if isinstance(lang_content, list):
                        for paragraph in lang_content:
                            if isinstance(paragraph, list):
                                for elem in paragraph:
                                    if elem.get("tag") == "text":
                                        texts.append(elem.get("text", ""))
                                    elif elem.get("tag") == "at":
                                        texts.append(f"@{elem.get('user_name', 'user')}")
                return " ".join(texts)

            elif message_type == "image":
                return "[图片]"

            elif message_type == "file":
                content_json = json.loads(content)
                file_name = content_json.get("file_name", "文件")
                return f"[文件: {file_name}]"

            elif message_type == "audio":
                return "[语音]"

            elif message_type == "media":
                return "[视频]"

            elif message_type == "sticker":
                return "[表情]"

            elif message_type == "interactive":
                return "[卡片消息]"

            else:
                return f"[{message_type} 消息]"

        except (json.JSONDecodeError, TypeError) as e:
            logger.warning("Failed to parse message content: %s", e)
            return content

    def filter_message(self, message: Dict[str, Any]) -> bool:
        """
        消息策略过滤

        参数:
            message: 消息数据

        返回:
            bool: 是否允许处理
        """
        # 过滤机器人自己的消息
        sender_type = message.get("sender_type", "")
        if sender_type == "app":
            return False

        # 过滤非文本消息（可配置）
        message_type = message.get("message_type", "")
        if message_type not in MESSAGE_TYPE_MAP:
            logger.debug("Unsupported message type: %s", message_type)
            return False

        return True
