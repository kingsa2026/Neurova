from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TelegramChatManagementMixin:
    """Telegram user & chat management mixin."""

    def get_user_info(self: Any, user_id: str) -> Optional[Dict]:
        return None

    def get_chat_info(self: Any, chat_id: str) -> Optional[Dict]:
        if not self._ensure_initialized():
            return None
        data = self._api_request("GET", f"/bot{self.bot_token}/getChat", params={"chat_id": chat_id})
        if data.get("ok"):
            return data.get("result")
        return None

    def get_chat_administrators(self: Any, chat_id: str) -> List[Dict]:
        if not self._ensure_initialized():
            return []
        data = self._api_request("GET", f"/bot{self.bot_token}/getChatAdministrators", params={"chat_id": chat_id})
        if data.get("ok"):
            return data.get("result", [])
        return []

    def ban_chat_member(self: Any, chat_id: str, user_id: str, until_date: int = 0) -> bool:
        if not self._ensure_initialized():
            return False
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/banChatMember",
            json={"chat_id": chat_id, "user_id": user_id, "until_date": until_date},
        )
        return data.get("ok", False)

    def unban_chat_member(self: Any, chat_id: str, user_id: str, only_if_banned: bool = False) -> bool:
        if not self._ensure_initialized():
            return False
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/unbanChatMember",
            json={"chat_id": chat_id, "user_id": user_id, "only_if_banned": only_if_banned},
        )
        return data.get("ok", False)
