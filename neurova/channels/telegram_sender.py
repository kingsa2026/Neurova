from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any

from neurova.channels import ContentType, UnifiedMessage

logger = get_logger(__name__)


class TelegramSenderMixin:
    """Telegram message sending mixin."""

    def send_message(self: Any, message: UnifiedMessage) -> bool:
        if not self._ensure_initialized():
            return False

        # inline_keyboard 透传（补漏 Task 9）：metadata["reply_markup"] 约定
        # 携带 Bot API 原生 dict；发送后清理，避免跨消息残留
        self._current_metadata = message.metadata
        try:
            return self._dispatch_message(message)
        finally:
            self._current_metadata = None

    def _dispatch_message(self: Any, message: UnifiedMessage) -> bool:
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

    def _send_text_message(self: Any, chat_id: str, text: str, parse_mode: str = None) -> bool:
        """发送文本消息。

        parse_mode 缺省取实例配置（默认 legacy "Markdown"，官方仍支持；
        可配置为 MarkdownV2/HTML）。内容与 parse_mode 语法不匹配时官方
        返回 400 can't parse entities —— 此时去掉 parse_mode 以纯文本重发。
        """
        if parse_mode is None:
            parse_mode = getattr(self, "parse_mode", "Markdown")

        payload: dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        # reply_markup 透传（metadata["reply_markup"] 约定，Bot API 原生 dict；
        # parse_mode 语法回退重发时保留键盘）
        reply_markup = (getattr(self, "_current_metadata", None) or {}).get("reply_markup")
        if reply_markup:
            payload["reply_markup"] = reply_markup

        data = self._api_request("POST", f"/bot{self.bot_token}/sendMessage", json=payload)
        if data.get("ok"):
            return True

        if payload.get("parse_mode") and "can't parse entities" in str(data.get("description", "")):
            payload.pop("parse_mode")
            data = self._api_request("POST", f"/bot{self.bot_token}/sendMessage", json=payload)
            if data.get("ok"):
                logger.info("Telegram parse_mode 解析失败，已回退纯文本发送")
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
