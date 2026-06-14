from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from neurova.channels import ContentType, MessageChannel, UnifiedMessage

logger = logging.getLogger(__name__)


class TelegramParserMixin:
    """Telegram message receive & parse mixin."""

    def receive_message(self: Any) -> Optional[UnifiedMessage]:
        if not self._ensure_initialized():
            return None

        try:
            data = self._api_request(
                "GET",
                f"/bot{self.bot_token}/getUpdates",
                params={
                    "offset": self._last_update_id + 1,
                    "limit": self._polling_limit,
                    "timeout": self._polling_timeout,
                },
                timeout=self._polling_timeout + 5,
            )

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    update_id = update.get("update_id", 0)
                    if update_id > self._last_update_id:
                        self._last_update_id = update_id
                    message = self.parse_raw_message(update)
                    if message:
                        return message
            return None
        except Exception as e:
            logger.error("Telegram 接收消息异常: %s", e)
            return None

    def parse_raw_message(self: Any, raw_data: Any) -> Optional[UnifiedMessage]:
        if isinstance(raw_data, str):
            try:
                raw_data = json.loads(raw_data)
            except json.JSONDecodeError:
                logger.error("Telegram JSON 解析失败: %s", raw_data)
                return None

        msg = raw_data.get("message") or raw_data.get("edited_message") or {}
        if not msg:
            return None

        chat = msg.get("chat", {})
        sender = msg.get("from", {})

        content = msg.get("text", "")
        content_type = ContentType.TEXT

        if msg.get("photo"):
            content_type = ContentType.IMAGE
            content = "[图片]"
        elif msg.get("voice"):
            content_type = ContentType.VOICE
            content = "[语音]"
        elif msg.get("video"):
            content_type = ContentType.VIDEO
            content = "[视频]"
        elif msg.get("document"):
            content_type = ContentType.FILE
            content = "[文件]"
        elif msg.get("location"):
            content_type = ContentType.LOCATION
            loc = msg["location"]
            content = f"[位置] Lat:{loc.get('latitude', '')}, Lng:{loc.get('longitude', '')}"
        elif msg.get("audio"):
            content_type = ContentType.VOICE
            content = "[音频]"
        elif msg.get("sticker"):
            content_type = ContentType.IMAGE
            content = "[表情]"

        timestamp = None
        msg_date = msg.get("date")
        if msg_date:
            try:
                timestamp = datetime.fromtimestamp(msg_date)
            except (ValueError, TypeError):
                timestamp = datetime.now()

        is_mentioned = self._check_mention(content, msg.get("entities", []))

        command = None
        if content.startswith("/"):
            parts = content.split()
            command = parts[0][1:].lower()

        if command and command in self._command_handlers:
            handler = self._command_handlers[command]
            temp_message = UnifiedMessage(
                message_id=str(msg.get("message_id", "")),
                channel=MessageChannel.TELEGRAM,
                chat_id=str(chat.get("id", "")),
                user_id=str(sender.get("id", "")),
                agent_id="",
                content=content,
                content_type=content_type,
                timestamp=timestamp,
                raw_message=raw_data,
                metadata={
                    "display_name": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
                    "username": sender.get("username", ""),
                    "chat_type": chat.get("type", ""),
                    "chat_title": chat.get("title", ""),
                    "is_mentioned": is_mentioned,
                    "command": command,
                },
            )
            try:
                response = handler(temp_message)
                self._send_text_message(str(chat.get("id", "")), response)
            except Exception as e:
                logger.error("命令处理异常 /%s: %s", command, e)

        return UnifiedMessage(
            message_id=str(msg.get("message_id", "")),
            channel=MessageChannel.TELEGRAM,
            chat_id=str(chat.get("id", "")),
            user_id=str(sender.get("id", "")),
            agent_id="",
            content=content,
            content_type=content_type,
            timestamp=timestamp,
            raw_message=raw_data,
            metadata={
                "display_name": f"{sender.get('first_name', '')} {sender.get('last_name', '')}".strip(),
                "username": sender.get("username", ""),
                "chat_type": chat.get("type", ""),
                "chat_title": chat.get("title", ""),
                "is_mentioned": is_mentioned,
                "command": command,
                "message_thread_id": msg.get("message_thread_id"),
                "reply_to_message": msg.get("reply_to_message"),
            },
        )

    def _check_mention(self: Any, text: str, entities: List[Dict]) -> bool:
        for entity in entities:
            if entity.get("type") == "mention":
                start = entity.get("offset", 0)
                length = entity.get("length", 0)
                mentioned_name = text[start: start + length]
                bot_names = [
                    f"@{self.bot_prefix}",
                    f"@{self.bot_prefix.lower()}",
                    f"@{self._bot_username}",
                ]
                if mentioned_name in bot_names:
                    return True
        return False
