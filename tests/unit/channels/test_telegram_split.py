from __future__ import annotations

import importlib
import sys

import pytest


class TestTelegramAdapterSplit:
    """Verify the 8-mixin split of TelegramAdapter is correct."""

    def test_adapter_class_exists(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        assert TelegramAdapter is not None

    def test_backward_compat_import(self):
        from neurova.channels.telegram import TelegramAdapter
        assert TelegramAdapter is not None

    def test_factory_function(self):
        from neurova.channels.telegram import create_telegram_adapter
        adapter = create_telegram_adapter()
        assert adapter is not None

    def test_mixin_classes_exist(self):
        from neurova.channels.telegram_api_client import TelegramAPIMixin
        from neurova.channels.telegram_sender import TelegramSenderMixin
        from neurova.channels.telegram_parser import TelegramParserMixin
        from neurova.channels.telegram_commands import TelegramCommandMixin
        from neurova.channels.telegram_webhook import TelegramWebhookMixin
        from neurova.channels.telegram_chat_management import TelegramChatManagementMixin
        from neurova.channels.telegram_message_management import TelegramMessageManagementMixin
        from neurova.channels.telegram_ai_generation import TelegramAIGenerationMixin
        assert all([
            TelegramAPIMixin, TelegramSenderMixin, TelegramParserMixin,
            TelegramCommandMixin, TelegramWebhookMixin, TelegramChatManagementMixin,
            TelegramMessageManagementMixin, TelegramAIGenerationMixin,
        ])

    def test_adapter_has_mixin_methods(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        # API client
        assert hasattr(adapter, "_api_request")
        assert hasattr(adapter, "_download_url")
        assert hasattr(adapter, "_save_temp_file")
        # Sender
        assert hasattr(adapter, "send_message")
        assert hasattr(adapter, "_send_text_message")
        assert hasattr(adapter, "_send_photo")
        assert hasattr(adapter, "_send_voice")
        assert hasattr(adapter, "_send_video")
        assert hasattr(adapter, "_send_document")
        assert hasattr(adapter, "_send_location")
        assert hasattr(adapter, "_send_chat_action")
        # Parser
        assert hasattr(adapter, "receive_message")
        assert hasattr(adapter, "parse_raw_message")
        assert hasattr(adapter, "_check_mention")
        # Commands
        assert hasattr(adapter, "_register_default_commands")
        assert hasattr(adapter, "register_command_handler")
        assert hasattr(adapter, "_handle_start")
        assert hasattr(adapter, "_handle_help")
        # Webhook
        assert hasattr(adapter, "set_webhook")
        assert hasattr(adapter, "delete_webhook")
        assert hasattr(adapter, "get_webhook_info")
        assert hasattr(adapter, "verify_webhook_signature")
        # Chat management
        assert hasattr(adapter, "get_user_info")
        assert hasattr(adapter, "get_chat_info")
        assert hasattr(adapter, "get_chat_administrators")
        assert hasattr(adapter, "ban_chat_member")
        assert hasattr(adapter, "unban_chat_member")
        # Message management
        assert hasattr(adapter, "delete_message")
        assert hasattr(adapter, "pin_message")
        assert hasattr(adapter, "unpin_message")
        # AI generation
        assert hasattr(adapter, "generate_text_to_image")
        assert hasattr(adapter, "generate_image_to_image")
        assert hasattr(adapter, "generate_text_to_video")
        assert hasattr(adapter, "generate_image_to_video")
        assert hasattr(adapter, "generate_keyframe_to_video")
        assert hasattr(adapter, "generate_video_to_video")
        assert hasattr(adapter, "_extract_prompt")
        assert hasattr(adapter, "handle_ai_generation")

    def test_adapter_core_methods(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        from neurova.channels import MessageChannel
        adapter = TelegramAdapter()
        assert adapter.channel == MessageChannel.TELEGRAM
        assert adapter.get_bot_info() == {}
        config = adapter.get_channel_config()
        assert config["channel"] == MessageChannel.TELEGRAM.value
        assert config["authenticated"] is False

    def test_command_handlers_registered(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        assert "start" in adapter._command_handlers
        assert "help" in adapter._command_handlers

    def test_should_process_message_open(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        update = {"message": {"chat": {"type": "private", "id": 1}, "from": {"id": 123}}}
        assert adapter.should_process_message(update) is True

    def test_should_process_message_closed(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        adapter.private_chat_strategy = "closed"
        update = {"message": {"chat": {"type": "private", "id": 1}, "from": {"id": 123}}}
        assert adapter.should_process_message(update) is False

    def test_should_process_message_no_message(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        assert adapter.should_process_message({}) is False

    def test_authenticate_missing_token(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        assert adapter.authenticate({}) is False

    def test_verify_webhook_signature(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        # No secret set → always passes
        assert adapter.verify_webhook_signature({}) is True
        # Secret set → must match
        adapter._webhook_secret = "abc123"
        assert adapter.verify_webhook_signature({"X-Telegram-Bot-Api-Secret-Token": "abc123"}) is True
        assert adapter.verify_webhook_signature({"X-Telegram-Bot-Api-Secret-Token": "wrong"}) is False

    def test_update_config(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        adapter.update_config({"bot_prefix": "newbot"})
        assert adapter.bot_prefix == "newbot"
        adapter.update_config({"show_typing": True})
        assert adapter.show_typing is True

    def test_reset_polling_offset(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        adapter._last_update_id = 100
        adapter.reset_polling_offset()
        assert adapter._last_update_id == 0

    def test_extract_prompt(self):
        from neurova.channels.telegram_adapter import TelegramAdapter
        adapter = TelegramAdapter()
        assert adapter._extract_prompt("生成图片: 一只猫") == "一只猫"
        assert adapter._extract_prompt("画: 风景") == "风景"
        assert adapter._extract_prompt("生成一段视频: 日落") == "日落"
        assert adapter._extract_prompt("hello world") == "hello world"
