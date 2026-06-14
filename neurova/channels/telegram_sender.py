from __future__ import annotations

import logging
from typing import Any

from neurova.channels import ContentType, UnifiedMessage

logger = logging.getLogger(__name__)


class TelegramSenderMixin:
    """Telegram message sending mixin."""

    def send_message(self: Any, message: UnifiedMessage) -> bool:
        if not self._ensure_initialized():
            return False

        try:
            if self.show_typing:
                self._send_chat_action(message.chat_id, "typing")

            if message.content_type == ContentType.TEXT:
                return self._send_text_message(message.chat_id, message.content)
            elif message.content_type == ContentType.IMAGE:
                return self._send_photo(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.VOICE:
                return self._send_voice(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.VIDEO:
                return self._send_video(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.FILE:
                return self._send_document(message.chat_id, message.file_url or message.content)
            elif message.content_type == ContentType.LOCATION:
                return self._send_location(message.chat_id, message.content)
            elif message.content_type == ContentType.CARD:
                return self._send_text_message(message.chat_id, message.content)
            else:
                return self._send_text_message(message.chat_id, message.content)
        except Exception as e:
            logger.error("Telegram 消息发送异常: %s", e)
            return False

    def _send_text_message(self: Any, chat_id: str, text: str, parse_mode: str = "Markdown") -> bool:
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
        )
        if data.get("ok"):
            return True
        logger.error("Telegram 文本消息发送失败: %s", data)
        return False

    def _send_photo(self: Any, chat_id: str, photo: str, caption: str = "") -> bool:
        payload: dict[str, Any] = {"chat_id": chat_id, "photo": photo}
        if caption:
            payload["caption"] = caption
        data = self._api_request("POST", f"/bot{self.bot_token}/sendPhoto", json=payload)
        return data.get("ok", False)

    def _send_voice(self: Any, chat_id: str, voice: str, caption: str = "") -> bool:
        payload: dict[str, Any] = {"chat_id": chat_id, "voice": voice}
        if caption:
            payload["caption"] = caption
        data = self._api_request("POST", f"/bot{self.bot_token}/sendVoice", json=payload)
        return data.get("ok", False)

    def _send_video(self: Any, chat_id: str, video: str, caption: str = "") -> bool:
        payload: dict[str, Any] = {"chat_id": chat_id, "video": video}
        if caption:
            payload["caption"] = caption
        data = self._api_request("POST", f"/bot{self.bot_token}/sendVideo", json=payload)
        return data.get("ok", False)

    def _send_document(self: Any, chat_id: str, document: str, caption: str = "") -> bool:
        payload: dict[str, Any] = {"chat_id": chat_id, "document": document}
        if caption:
            payload["caption"] = caption
        data = self._api_request("POST", f"/bot{self.bot_token}/sendDocument", json=payload)
        return data.get("ok", False)

    def _send_location(self: Any, chat_id: str, location_data: str) -> bool:
        try:
            parts = location_data.replace("[位置] ", "").split(",")
            lat = float(parts[0].replace("Lat:", "").strip())
            lng = float(parts[1].replace("Lng:", "").strip())
            data = self._api_request(
                "POST",
                f"/bot{self.bot_token}/sendLocation",
                json={"chat_id": chat_id, "latitude": lat, "longitude": lng},
            )
            return data.get("ok", False)
        except (ValueError, IndexError):
            logger.error("位置数据解析失败: %s", location_data)
            return False

    def _send_chat_action(self: Any, chat_id: str, action: str) -> bool:
        if not self.show_typing:
            return True
        self._api_request(
            "POST",
            f"/bot{self.bot_token}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
        )
        return True
