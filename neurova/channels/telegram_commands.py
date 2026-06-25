from __future__ import annotations

from neurova.core.logger import get_logger
from typing import Any, Callable

from neurova.channels import UnifiedMessage

logger = get_logger(__name__)


class TelegramCommandMixin:
    """Telegram command registration & handling mixin."""

    def _register_default_commands(self: Any) -> None:
        self._command_handlers["start"] = self._handle_start
        self._command_handlers["help"] = self._handle_help

    def register_command_handler(self: Any, command: str, handler: Callable) -> None:
        self._command_handlers[command.lower()] = handler
        logger.info("注册 Telegram 命令处理器: /%s", command)

    def _handle_start(self: Any, message: UnifiedMessage) -> str:
        display_name = message.metadata.get("display_name", "用户")
        return f"欢迎 {display_name}! 我是 {self.bot_prefix} 机器人，有什么可以帮你的？"

    def _handle_help(self: Any, message: UnifiedMessage) -> str:
        commands = ", ".join([f"/{cmd}" for cmd in self._command_handlers.keys()])
        return f"可用命令: {commands}\n\n直接发送消息即可与我对话。"
