"""
设置管理器测试
测试 SettingsManager 的各种功能，包括语言设置、时区设置、用户设置管理等。
"""

import pytest
import sys
import os
import json
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../../')))

from neurova.core.settings_manager import (
    SettingsManager,
    get_settings_manager,
    reset_settings_manager
)


class TestSettingsManager:
    """测试设置管理器"""

    @pytest.fixture
    def settings_manager(self, tmp_path):
        """创建设置管理器实例"""
        reset_settings_manager()
        config = {
            "data_path": str(tmp_path / "settings"),
            "languages_enabled": True,
            "timezone_enabled": True
        }
        return SettingsManager(config)

    def test_init(self, settings_manager):
        """测试初始化"""
        assert settings_manager is not None
        assert settings_manager.languages_enabled is True
        assert settings_manager.timezone_enabled is True
        assert settings_manager.data_path.exists()

    def test_get_user_language_default(self, settings_manager):
        """测试获取用户默认语言"""
        language = settings_manager.get_user_language("user1")
        assert language["language"] == "zh_CN"
        assert language["fallback_language"] == "en_US"
        assert language["auto_detect"] is False

    def test_set_user_language(self, settings_manager):
        """测试设置用户语言"""
        settings_manager.set_user_language(
            user_id="user1",
            language="en_US",
            fallback_language="zh_CN",
            auto_detect=True
        )
        
        language = settings_manager.get_user_language("user1")
        assert language["language"] == "en_US"
        assert language["fallback_language"] == "zh_CN"
        assert language["auto_detect"] is True

    def test_get_user_timezone_default(self, settings_manager):
        """测试获取用户默认时区"""
        timezone = settings_manager.get_user_timezone("user1")
        assert timezone == "Asia/Shanghai"

    def test_set_user_timezone(self, settings_manager):
        """测试设置用户时区"""
        settings_manager.set_user_timezone("user1", "America/New_York")
        timezone = settings_manager.get_user_timezone("user1")
        assert timezone == "America/New_York"

    def test_get_all_settings(self, settings_manager):
        """测试获取用户所有设置"""
        settings_manager.set_user_language("user1", "en_US")
        settings_manager.set_user_timezone("user1", "America/New_York")
        
        all_settings = settings_manager.get_all_settings("user1")
        assert "language" in all_settings
        assert "timezone" in all_settings
        assert all_settings["language"]["language"] == "en_US"
        assert all_settings["timezone"] == "America/New_York"

    def test_update_settings(self, settings_manager):
        """测试批量更新用户设置"""
        settings_manager.update_settings("user1", {
            "custom_key": "custom_value",
            "another_key": 123
        })
        
        all_settings = settings_manager.get_all_settings("user1")
        assert all_settings["custom_key"] == "custom_value"
        assert all_settings["another_key"] == 123

    def test_multiple_users(self, settings_manager):
        """测试多用户设置"""
        settings_manager.set_user_language("user1", "en_US")
        settings_manager.set_user_language("user2", "zh_CN")
        settings_manager.set_user_timezone("user1", "America/New_York")
        settings_manager.set_user_timezone("user2", "Asia/Tokyo")
        
        lang1 = settings_manager.get_user_language("user1")
        lang2 = settings_manager.get_user_language("user2")
        tz1 = settings_manager.get_user_timezone("user1")
        tz2 = settings_manager.get_user_timezone("user2")
        
        assert lang1["language"] == "en_US"
        assert lang2["language"] == "zh_CN"
        assert tz1 == "America/New_York"
        assert tz2 == "Asia/Tokyo"


class TestSettingsPersistence:
    """测试设置持久化"""

    @pytest.fixture
    def settings_manager_with_data(self, tmp_path):
        """创建带数据的设置管理器"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        manager.set_user_language("user1", "en_US")
        manager.set_user_timezone("user1", "America/New_York")
        manager.update_settings("user1", {"custom": "value"})
        
        return manager

    def test_save_settings_sync(self, settings_manager_with_data):
        """测试同步保存设置"""
        settings_manager_with_data._save_settings_sync()
        
        settings_file = settings_manager_with_data._user_settings_path
        assert settings_file.exists()
        
        with open(settings_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert "user1" in data
        assert data["user1"]["language"]["language"] == "en_US"

    def test_load_settings_on_init(self, tmp_path):
        """测试初始化时加载设置"""
        data_path = tmp_path / "settings"
        data_path.mkdir(parents=True)
        
        settings_file = data_path / "user_settings.json"
        initial_data = {
            "user1": {
                "language": {
                    "language": "ja_JP",
                    "fallback_language": "en_US",
                    "auto_detect": False
                },
                "timezone": "Asia/Tokyo"
            }
        }
        
        with open(settings_file, 'w', encoding='utf-8') as f:
            json.dump(initial_data, f)
        
        config = {"data_path": str(data_path)}
        manager = SettingsManager(config)
        
        language = manager.get_user_language("user1")
        timezone = manager.get_user_timezone("user1")
        
        assert language["language"] == "ja_JP"
        assert timezone == "Asia/Tokyo"


class TestSettingsManagerLifecycle:
    """测试设置管理器生命周期"""

    @pytest.fixture
    def settings_manager(self, tmp_path):
        """创建设置管理器实例"""
        config = {"data_path": str(tmp_path / "settings")}
        return SettingsManager(config)

    def test_on_init(self, settings_manager):
        """测试初始化阶段"""
        settings_manager._on_init()
        assert settings_manager.data_path.exists()

    def test_on_start(self, settings_manager):
        """测试启动阶段"""
        settings_manager._on_start()

    def test_on_stop(self, settings_manager):
        """测试停止阶段"""
        settings_manager.set_user_language("user1", "en_US")
        settings_manager._on_stop()

    @pytest.mark.asyncio
    async def test_initialize(self, settings_manager):
        """测试异步初始化"""
        await settings_manager.initialize()
        assert settings_manager.data_path.exists()

    @pytest.mark.asyncio
    async def test_start(self, settings_manager):
        """测试异步启动"""
        await settings_manager.start()

    @pytest.mark.asyncio
    async def test_stop(self, settings_manager):
        """测试异步停止"""
        settings_manager.set_user_language("user1", "en_US")
        await settings_manager.stop()


class TestGetSettingsManager:
    """测试获取设置管理器单例"""

    def test_get_settings_manager(self):
        """测试获取设置管理器实例"""
        reset_settings_manager()
        manager1 = get_settings_manager()
        manager2 = get_settings_manager()
        assert manager1 is manager2

    def test_reset_settings_manager(self):
        """测试重置设置管理器"""
        reset_settings_manager()
        manager1 = get_settings_manager()
        reset_settings_manager()
        manager2 = get_settings_manager()
        assert manager1 is not manager2


class TestEdgeCases:
    """测试边界情况"""

    def test_nonexistent_user(self, tmp_path):
        """测试不存在的用户"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        language = manager.get_user_language("nonexistent")
        timezone = manager.get_user_timezone("nonexistent")
        all_settings = manager.get_all_settings("nonexistent")
        
        assert language["language"] == "zh_CN"
        assert timezone == "Asia/Shanghai"
        assert all_settings == {}

    def test_empty_user_id(self, tmp_path):
        """测试空用户ID"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        manager.set_user_language("", "en_US")
        language = manager.get_user_language("")
        
        assert language["language"] == "en_US"

    def test_special_characters_in_user_id(self, tmp_path):
        """测试用户ID包含特殊字符"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        user_id = "user@example.com"
        manager.set_user_language(user_id, "en_US")
        language = manager.get_user_language(user_id)
        
        assert language["language"] == "en_US"

    def test_invalid_timezone(self, tmp_path):
        """测试无效时区"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        manager.set_user_timezone("user1", "Invalid/Timezone")
        timezone = manager.get_user_timezone("user1")
        
        assert timezone == "Invalid/Timezone"

    def test_update_empty_settings(self, tmp_path):
        """测试更新空设置"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        manager.update_settings("user1", {})
        all_settings = manager.get_all_settings("user1")
        
        assert all_settings == {}

    def test_overwrite_existing_settings(self, tmp_path):
        """测试覆盖现有设置"""
        config = {"data_path": str(tmp_path / "settings")}
        manager = SettingsManager(config)
        
        manager.set_user_language("user1", "en_US")
        manager.set_user_language("user1", "zh_CN")
        
        language = manager.get_user_language("user1")
        assert language["language"] == "zh_CN"
