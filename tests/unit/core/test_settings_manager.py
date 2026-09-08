"""
设置管理器测试（对齐 neurova/core/settings_manager.py 真实契约）
测试 SettingsManager 的语言/时区/工作空间设置、持久化与生命周期回调。
"""

import pytest
import json
from pathlib import Path

from neurova.core.settings_manager import (
    SettingsManager,
    get_settings_manager,
    reset_settings_manager,
)


def _make_manager(tmp_path, **extra):
    config = {"data_dir": str(tmp_path / "settings")}
    config.update(extra)
    return SettingsManager(config)


class TestSettingsManager:
    """测试设置管理器"""

    @pytest.fixture
    def settings_manager(self, tmp_path):
        """创建设置管理器实例"""
        reset_settings_manager()
        return _make_manager(tmp_path)

    def test_init(self, tmp_path):
        """测试初始化（data_dir 目录自动创建，默认语言 zh-CN）"""
        manager = _make_manager(tmp_path)

        assert manager is not None
        assert (tmp_path / "settings").exists()
        assert manager.get_setting("language") == "zh-CN"
        assert manager.get_setting("timezone") == "Asia/Shanghai"

    def test_get_user_language_default(self, settings_manager):
        """测试获取用户默认语言（契约：返回语言代码字符串）"""
        language = settings_manager.get_user_language("user1")
        assert language == "zh-CN"

    def test_set_user_language(self, settings_manager):
        """测试设置用户语言（契约：set_user_language(language, user_id)）"""
        success = settings_manager.set_user_language("en-US", "user1")

        assert success is True
        assert settings_manager.get_user_language("user1") == "en-US"

    def test_get_user_timezone_default(self, settings_manager):
        """测试获取用户默认时区"""
        timezone = settings_manager.get_user_timezone("user1")
        assert timezone == "Asia/Shanghai"

    def test_set_user_timezone(self, settings_manager):
        """测试设置用户时区"""
        settings_manager.set_user_timezone("America/New_York", "user1")
        assert settings_manager.get_user_timezone("user1") == "America/New_York"

    def test_get_user_workspace(self, settings_manager):
        """测试用户工作空间设置"""
        assert settings_manager.get_user_workspace("user1") is None

        settings_manager.set_user_workspace("/tmp/ws", "user1")
        assert settings_manager.get_user_workspace("user1") == "/tmp/ws"

    def test_get_all_settings(self, settings_manager):
        """测试获取用户所有设置（8 个标准键，用户覆盖优先）"""
        settings_manager.set_user_language("en-US", "user1")
        settings_manager.set_user_timezone("America/New_York", "user1")

        all_settings = settings_manager.get_all_settings("user1")
        assert all_settings["language"] == "en-US"
        assert all_settings["timezone"] == "America/New_York"
        # 未覆盖的键回落全局默认
        assert all_settings["theme"] == "light"
        assert all_settings["font_size"] == 14

    def test_update_settings(self, settings_manager):
        """测试批量更新用户设置（契约：update_settings(settings, user_id)，白名单键生效）"""
        success = settings_manager.update_settings(
            {"theme": "dark", "font_size": 16, "custom_key": "ignored"},
            "user1",
        )

        assert success is True
        all_settings = settings_manager.get_all_settings("user1")
        assert all_settings["theme"] == "dark"
        assert all_settings["font_size"] == 16
        # 非白名单键不进入标准视图
        assert "custom_key" not in all_settings

    def test_multiple_users(self, settings_manager):
        """测试多用户设置隔离"""
        settings_manager.set_user_language("en-US", "user1")
        settings_manager.set_user_language("zh-CN", "user2")
        settings_manager.set_user_timezone("America/New_York", "user1")
        settings_manager.set_user_timezone("Asia/Tokyo", "user2")

        assert settings_manager.get_user_language("user1") == "en-US"
        assert settings_manager.get_user_language("user2") == "zh-CN"
        assert settings_manager.get_user_timezone("user1") == "America/New_York"
        assert settings_manager.get_user_timezone("user2") == "Asia/Tokyo"

    def test_set_setting_get_setting(self, settings_manager):
        """测试通用单键设置"""
        assert settings_manager.set_setting("custom_key", {"a": 1}) is True
        assert settings_manager.get_setting("custom_key") == {"a": 1}
        assert settings_manager.get_setting("missing", "fallback") == "fallback"

    def test_reset_settings(self, settings_manager):
        """测试重置用户设置为默认值"""
        settings_manager.set_user_language("en-US", "user1")
        settings_manager.set_user_timezone("Asia/Tokyo", "user1")

        assert settings_manager.reset_settings("user1") is True
        assert settings_manager.get_user_language("user1") == "zh-CN"
        assert settings_manager.get_user_timezone("user1") == "Asia/Shanghai"


class TestSettingsPersistence:
    """测试设置持久化"""

    def test_save_and_reload(self, tmp_path):
        """测试设置落盘并在新实例中恢复（扁平 user_{uid}_* 键）"""
        manager = _make_manager(tmp_path)
        manager.set_user_language("en-US", "user1")
        manager.set_user_timezone("America/New_York", "user1")

        settings_file = manager._settings_file
        assert settings_file.exists()

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["user_user1_language"] == "en-US"

        # 新实例从同一文件恢复
        manager2 = _make_manager(tmp_path)
        assert manager2.get_user_language("user1") == "en-US"
        assert manager2.get_user_timezone("user1") == "America/New_York"

    def test_load_settings_on_init(self, tmp_path):
        """测试初始化时加载已有设置文件"""
        data_dir = tmp_path / "settings"
        data_dir.mkdir(parents=True)

        settings_file = data_dir / "settings.json"
        settings_file.write_text(
            json.dumps({"user_user1_language": "ja-JP", "user_user1_timezone": "Asia/Tokyo"}),
            encoding="utf-8",
        )

        manager = _make_manager(tmp_path)

        assert manager.get_user_language("user1") == "ja-JP"
        assert manager.get_user_timezone("user1") == "Asia/Tokyo"

    def test_corrupt_settings_file_falls_back(self, tmp_path):
        """设置文件损坏时回落默认值不崩"""
        data_dir = tmp_path / "settings"
        data_dir.mkdir(parents=True)
        (data_dir / "settings.json").write_text("{broken json", encoding="utf-8")

        manager = _make_manager(tmp_path)

        assert manager.get_setting("language") == "zh-CN"


class TestSettingsManagerLifecycle:
    """测试设置管理器生命周期（契约：_on_init/_on_start/_on_stop 同步回调）"""

    def test_on_init(self, tmp_path):
        """测试初始化阶段回调"""
        manager = _make_manager(tmp_path)
        manager._on_init()
        assert (tmp_path / "settings").exists()

    def test_on_start(self, tmp_path):
        """测试启动阶段回调"""
        manager = _make_manager(tmp_path)
        manager._on_start()

    def test_on_stop_saves(self, tmp_path):
        """测试停止阶段回调触发落盘"""
        manager = _make_manager(tmp_path)
        manager.set_user_language("en-US", "user1")

        # 手动清掉文件模拟未保存状态，_on_stop 应重新落盘
        manager._settings_file.unlink()
        manager._on_stop()

        assert manager._settings_file.exists()


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
        """测试不存在的用户回落全局默认"""
        manager = _make_manager(tmp_path)

        language = manager.get_user_language("nonexistent")
        timezone = manager.get_user_timezone("nonexistent")
        all_settings = manager.get_all_settings("nonexistent")

        assert language == "zh-CN"
        assert timezone == "Asia/Shanghai"
        assert set(all_settings.keys()) == {
            "language", "timezone", "workspace", "theme",
            "font_size", "auto_save", "notifications", "debug_mode",
        }

    def test_empty_user_id(self, tmp_path):
        """测试空用户ID"""
        manager = _make_manager(tmp_path)

        manager.set_user_language("en-US", "")
        assert manager.get_user_language("") == "en-US"

    def test_special_characters_in_user_id(self, tmp_path):
        """测试用户ID包含特殊字符"""
        manager = _make_manager(tmp_path)

        user_id = "user@example.com"
        manager.set_user_language("en-US", user_id)
        assert manager.get_user_language(user_id) == "en-US"

    def test_invalid_timezone_stored_as_is(self, tmp_path):
        """测试无效时区原样存储（不做校验）"""
        manager = _make_manager(tmp_path)

        manager.set_user_timezone("Invalid/Timezone", "user1")
        assert manager.get_user_timezone("user1") == "Invalid/Timezone"

    def test_overwrite_existing_settings(self, tmp_path):
        """测试覆盖现有设置"""
        manager = _make_manager(tmp_path)

        manager.set_user_language("en-US", "user1")
        manager.set_user_language("zh-CN", "user1")

        assert manager.get_user_language("user1") == "zh-CN"
