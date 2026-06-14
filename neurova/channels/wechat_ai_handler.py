"""
微信 AI 生成请求处理 Mixin

检测消息中的AI生成请求并执行生成。
"""
from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any

from neurova.channels.base import MessageChannel
from neurova.channels.models import ContentType, UnifiedMessage

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class WeChatAIHandlerMixin:
    """微信 AI 处理 Mixin — 提取提示词、分发AI生成请求"""

    def __init__(self, adapter: Any) -> None:
        self.adapter = adapter

    def _extract_prompt(self, content: str) -> str:
        """从消息内容中提取AI生成提示词

        参数:
            content: 消息内容

        返回:
            提取的提示词
        """
        patterns = [
            r"生成?\s*(?:一张|个)?\s*(?:图片?|画).*?[:：]?\s*(.+)",
            r"画.*?[:：]?\s*(.+)",
            r"生成?\s*(?:一段|个)?\s*视频.*?[:：]?\s*(.+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return content

    async def handle_ai_generation(self, message: UnifiedMessage) -> bool:
        """处理AI生成请求

        检测消息中的AI生成请求并执行生成

        参数:
            message: 统一消息对象

        返回:
            处理成功返回 True
        """
        a = self.adapter
        content = message.content.lower()

        has_image = message.content_type == ContentType.IMAGE
        has_video = message.content_type == ContentType.VIDEO

        image_url = message.metadata.get("file_url", "") or message.metadata.get("pic_url", "")
        video_url = message.metadata.get("file_url", "")

        if "生成图片" in content or "画一张" in content or "生成一张图片" in content:
            if has_image:
                prompt = self._extract_prompt(message.content) or ""
                if image_url:
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="正在生成图片，请稍候...",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    image_data = await a.generate_image_to_image(image_url, prompt)
                    if image_data:
                        temp_path = await a._save_temp_file(image_data, "png")
                        if temp_path:
                            media_id = a.upload_media(temp_path, "image")
                            if media_id:
                                if a.mode == "wecom":
                                    a._send_app_message(
                                        UnifiedMessage(
                                            message_id="temp",
                                            channel=MessageChannel.WECHAT,
                                            chat_id=message.chat_id,
                                            user_id=message.user_id,
                                            agent_id="",
                                            content="",
                                            content_type=ContentType.IMAGE,
                                            timestamp=datetime.now(),
                                            file_url=media_id,
                                        )
                                    )
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                        if a.mode == "wecom":
                            a._send_app_message(
                                UnifiedMessage(
                                    message_id="temp",
                                    channel=MessageChannel.WECHAT,
                                    chat_id=message.chat_id,
                                    user_id=message.user_id,
                                    agent_id="",
                                    content="图片生成失败",
                                    content_type=ContentType.TEXT,
                                    timestamp=datetime.now(),
                                )
                            )
                        return False
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="图片生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
            else:
                prompt = self._extract_prompt(message.content)
                if prompt:
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="正在生成图片，请稍候...",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    image_data = await a.generate_text_to_image(prompt)
                    if image_data:
                        temp_path = await a._save_temp_file(image_data, "png")
                        if temp_path:
                            media_id = a.upload_media(temp_path, "image")
                            if media_id:
                                if a.mode == "wecom":
                                    a._send_app_message(
                                        UnifiedMessage(
                                            message_id="temp",
                                            channel=MessageChannel.WECHAT,
                                            chat_id=message.chat_id,
                                            user_id=message.user_id,
                                            agent_id="",
                                            content="",
                                            content_type=ContentType.IMAGE,
                                            timestamp=datetime.now(),
                                            file_url=media_id,
                                        )
                                    )
                                os.unlink(temp_path)
                                return True
                            os.unlink(temp_path)
                        if a.mode == "wecom":
                            a._send_app_message(
                                UnifiedMessage(
                                    message_id="temp",
                                    channel=MessageChannel.WECHAT,
                                    chat_id=message.chat_id,
                                    user_id=message.user_id,
                                    agent_id="",
                                    content="图片生成失败",
                                    content_type=ContentType.TEXT,
                                    timestamp=datetime.now(),
                                )
                            )
                        return False
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="图片生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False

        elif has_image and (
            "图生图" in content or "以图生图" in content or "生成相似图片" in content or "生成新图片" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成图片，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                image_data = await a.generate_image_to_image(image_url, prompt)
                if image_data:
                    temp_path = await a._save_temp_file(image_data, "png")
                    if temp_path:
                        media_id = a.upload_media(temp_path, "image")
                        if media_id:
                            if a.mode == "wecom":
                                a._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.IMAGE,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="图片生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="图片生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif has_image and (
            "图生视频" in content or "图片转视频" in content or "让图片动起来" in content or "图片生成视频" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if image_url:
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await a.generate_image_to_video(image_url, prompt)
                if video_data:
                    temp_path = await a._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = a.upload_media(temp_path, "video")
                        if media_id:
                            if a.mode == "wecom":
                                a._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif ("首尾帧" in content or "首帧到尾帧" in content or "首尾帧生成视频" in content) and message.metadata.get(
            "images_count", 0
        ) >= 2:
            start_url = message.metadata.get("first_image_url", "")
            end_url = message.metadata.get("last_image_url", "")
            if start_url and end_url:
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await a.generate_keyframe_to_video(start_url, end_url)
                if video_data:
                    temp_path = await a._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = a.upload_media(temp_path, "video")
                        if media_id:
                            if a.mode == "wecom":
                                a._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif has_video and (
            "视频生成" in content or "视频风格" in content or "修改视频" in content or "视频转视频" in content
        ):
            prompt = self._extract_prompt(message.content) or ""
            if video_url:
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await a.generate_video_to_video(video_url, prompt)
                if video_data:
                    temp_path = await a._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = a.upload_media(temp_path, "video")
                        if media_id:
                            if a.mode == "wecom":
                                a._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        elif "生成视频" in content or "生成一段视频" in content:
            prompt = self._extract_prompt(message.content)
            if prompt:
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="正在生成视频，请稍候...",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                video_data = await a.generate_text_to_video(prompt)
                if video_data:
                    temp_path = await a._save_temp_file(video_data, "mp4")
                    if temp_path:
                        media_id = a.upload_media(temp_path, "video")
                        if media_id:
                            if a.mode == "wecom":
                                a._send_app_message(
                                    UnifiedMessage(
                                        message_id="temp",
                                        channel=MessageChannel.WECHAT,
                                        chat_id=message.chat_id,
                                        user_id=message.user_id,
                                        agent_id="",
                                        content="",
                                        content_type=ContentType.VIDEO,
                                        timestamp=datetime.now(),
                                        file_url=media_id,
                                    )
                                )
                            os.unlink(temp_path)
                            return True
                        os.unlink(temp_path)
                    if a.mode == "wecom":
                        a._send_app_message(
                            UnifiedMessage(
                                message_id="temp",
                                channel=MessageChannel.WECHAT,
                                chat_id=message.chat_id,
                                user_id=message.user_id,
                                agent_id="",
                                content="视频生成失败",
                                content_type=ContentType.TEXT,
                                timestamp=datetime.now(),
                            )
                        )
                    return False
                if a.mode == "wecom":
                    a._send_app_message(
                        UnifiedMessage(
                            message_id="temp",
                            channel=MessageChannel.WECHAT,
                            chat_id=message.chat_id,
                            user_id=message.user_id,
                            agent_id="",
                            content="视频生成失败",
                            content_type=ContentType.TEXT,
                            timestamp=datetime.now(),
                        )
                    )
                return False

        return False
