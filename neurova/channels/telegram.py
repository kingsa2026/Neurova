"""Backward-compatible re-export — all logic lives in telegram_adapter.py and mixins."""
from __future__ import annotations

from neurova.channels.telegram_adapter import (
    TelegramAdapter,
    create_telegram_adapter,
)

__all__ = ["TelegramAdapter", "create_telegram_adapter"]
