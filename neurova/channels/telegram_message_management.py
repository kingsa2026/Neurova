from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any

logger = get_logger(__name__)


class TelegramMessageManagementMixin:
    """Telegram message pin/unpin/delete mixin."""

    def delete_message(self: Any, chat_id: str, message_id: str) -> bool:
        if not self._ensure_initialized():
            return False
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/deleteMessage",
            json={"chat_id": chat_id, "message_id": message_id},
        )
        return data.get("ok", False)

    def pin_message(self: Any, chat_id: str, message_id: str, disable_notification: bool = False) -> bool:
        if not self._ensure_initialized():
            return False
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/pinChatMessage",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "disable_notification": disable_notification,
            },
        )
        return data.get("ok", False)

    def unpin_message(self: Any, chat_id: str, message_id: str = None) -> bool:
        if not self._ensure_initialized():
            return False
        payload: dict[str, Any] = {"chat_id": chat_id}
        if message_id:
            payload["message_id"] = message_id
        data = self._api_request("POST", f"/bot{self.bot_token}/unpinChatMessage", json=payload)
        return data.get("ok", False)
