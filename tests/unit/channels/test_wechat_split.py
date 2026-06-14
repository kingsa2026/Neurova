"""
WeChat模块拆分验证测试

验证拆分后的模块可以正确导入，且原有接口保持兼容。
"""

import pytest


class TestWeChatModuleImports:
    """测试所有模块可导入"""

    def test_import_core_adapter(self):
        """核心适配器可导入"""
        from neurova.channels.wechat import WeChatAdapter, create_wechat_adapter
        assert WeChatAdapter is not None
        assert create_wechat_adapter is not None

    def test_import_auth_module(self):
        """认证模块可导入"""
        from neurova.channels.wechat_auth import WeChatAuthMixin
        assert WeChatAuthMixin is not None

    def test_import_parsing_module(self):
        """解析模块可导入"""
        from neurova.channels.wechat_parsing import WeChatParsingMixin
        assert WeChatParsingMixin is not None

    def test_import_messaging_module(self):
        """消息模块可导入"""
        from neurova.channels.wechat_messaging import WeChatMessagingMixin
        assert WeChatMessagingMixin is not None

    def test_import_media_module(self):
        """媒体模块可导入"""
        from neurova.channels.wechat_media import WeChatMediaMixin
        assert WeChatMediaMixin is not None

    def test_import_ai_generation_module(self):
        """AI生成模块可导入"""
        from neurova.channels.wechat_ai_generation import WeChatAIGenerationMixin
        assert WeChatAIGenerationMixin is not None

    def test_import_ai_handler_module(self):
        """AI处理模块可导入"""
        from neurova.channels.wechat_ai_handler import WeChatAIHandlerMixin
        assert WeChatAIHandlerMixin is not None


class TestWeChatAdapterInheritance:
    """测试适配器正确继承所有Mixin"""

    def test_adapter_has_auth_methods(self):
        """适配器有认证方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, '_authenticate_wecom')
        assert hasattr(WeChatAdapter, '_authenticate_ilink')
        assert hasattr(WeChatAdapter, '_authenticate_official')
        assert hasattr(WeChatAdapter, 'verify_signature')

    def test_adapter_has_parsing_methods(self):
        """适配器有解析方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'parse_raw_message')
        assert hasattr(WeChatAdapter, '_parse_wecom_message')
        assert hasattr(WeChatAdapter, '_parse_ilink_message')
        assert hasattr(WeChatAdapter, '_parse_official_message')

    def test_adapter_has_messaging_methods(self):
        """适配器有消息方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'send_message')
        assert hasattr(WeChatAdapter, '_send_wecom_message')
        assert hasattr(WeChatAdapter, '_send_ilink_message')
        assert hasattr(WeChatAdapter, '_send_official_message')

    def test_adapter_has_media_methods(self):
        """适配器有媒体方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'upload_media')
        assert hasattr(WeChatAdapter, 'download_media')

    def test_adapter_has_ai_generation_methods(self):
        """适配器有AI生成方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'generate_text_to_image')
        assert hasattr(WeChatAdapter, 'generate_image_to_image')
        assert hasattr(WeChatAdapter, 'generate_text_to_video')

    def test_adapter_has_ai_handler_methods(self):
        """适配器有AI处理方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'handle_ai_generation')

    def test_adapter_has_core_methods(self):
        """适配器有核心方法"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'authenticate')
        assert hasattr(WeChatAdapter, 'get_channel_config')
        assert hasattr(WeChatAdapter, 'update_config')
        assert hasattr(WeChatAdapter, 'get_user_info')


class TestWeChatAdapterStructure:
    """测试适配器结构正确"""

    def test_adapter_is_singleton_class(self):
        """适配器是单一类"""
        from neurova.channels.wechat import WeChatAdapter
        from neurova.channels.base import ChannelAdapter
        assert issubclass(WeChatAdapter, ChannelAdapter)

    def test_adapter_has_channel_property(self):
        """适配器有channel属性"""
        from neurova.channels.wechat import WeChatAdapter
        assert hasattr(WeChatAdapter, 'channel')

    def test_core_file_is_slim(self):
        """核心文件不超过600行"""
        import os
        core_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'neurova', 'channels', 'wechat.py')
        with open(core_path, 'r', encoding='utf-8') as f:
            lines = len(f.readlines())
        assert lines < 600, f"wechat.py is {lines} lines, expected < 600"
