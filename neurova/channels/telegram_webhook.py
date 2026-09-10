from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any, Dict, Optional

logger = get_logger(__name__)


class TelegramWebhookMixin:
    """Telegram webhook management mixin."""

    def set_webhook(self: Any, webhook_url: str, secret_token: str = "") -> bool:
        self._webhook_url = webhook_url
        self._webhook_secret = secret_token

        payload: dict[str, Any] = {"url": webhook_url}
        if secret_token:
            payload["secret_token"] = secret_token

        data = self._api_request("POST", f"/bot{self.bot_token}/setWebhook", json=payload)

        if data.get("ok"):
            logger.info("Telegram Webhook 已设置: %s", webhook_url)
            return True
        logger.error("Telegram Webhook 设置失败: %s", data)
        return False

    def delete_webhook(self: Any, drop_pending_updates: bool = False) -> bool:
        data = self._api_request(
            "POST",
            f"/bot{self.bot_token}/deleteWebhook",
            json={"drop_pending_updates": drop_pending_updates},
        )
        if data.get("ok"):
            logger.info("Telegram Webhook 已删除")
            return True
        logger.error("Telegram Webhook 删除失败: %s", data)
        return False

    def get_webhook_info(self: Any) -> Optional[Dict]:
        data = self._api_request("GET", f"/bot{self.bot_token}/getWebhookInfo")
        if data.get("ok"):
            return data.get("result")
        return None

    def verify_webhook_signature(self: Any, headers: Dict) -> bool:
        # BUG AUDIT C-10: 此前 _webhook_secret 为空时直接 return True → 任何人
        # 可伪造 Webhook 推送。改为 fail-closed：无密钥时拒绝（返回 False）。
        if not self._webhook_secret:
            logger.warning("Telegram Webhook 未配置 _webhook_secret，拒绝未校验的推送")
            return False
        # 恒定时间比较，防时序攻击探测 secret（同 S-20）
        import hmac

        return hmac.compare_digest(
            str(headers.get("X-Telegram-Bot-Api-Secret-Token", "")).encode("utf-8", "ignore"),
            str(self._webhook_secret).encode("utf-8"),
        )
