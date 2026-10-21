"""
设置管理器测试（对齐 neurova/core/settings_manager.py 真实契约）
测试 SettingsManager 的时区/工作空间设置、持久化与生命周期回调。

**语言那一格不在本档的范围内了**（§6-167，用户 2026-10-12 裁「先取长补短再退役」）：
`get_user_language`/`set_user_language` 连同两处 key 白名单里的 `language` 一起退役，
因为它们是「某个用户默认看什么语言」的第二套词汇而生产消费者 0 处。退役面与防再生的
判据在 `tests/unit/api/test_RetiredGlobalLanguageDefault.py`，本档只留**仍然活着**的那些
契约——原先有 10 个用例把 `set_user_language(...)` 当"给某个用户塞点自有值"的顺手写法，
它们测的是持久化、按用户隔离、重置、损坏回落这些**别的东西**，所以逐格改指
`timezone`/`workspace` 两键，而不是连覆盖一起删掉。
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
        """测试初始化（data_dir 目录自动创建，默认时区 Asia/Shanghai）"""
        manager = _make_manager(tmp_path)

        assert manager is not None
        assert (tmp_path / "settings").exists()
        assert manager.get_setting("timezone") == "Asia/Shanghai"

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
        """测试获取用户所有设置（标准键视图，用户覆盖优先）"""
        settings_manager.set_user_workspace("/ws/a", "user1")
        settings_manager.set_user_timezone("America/New_York", "user1")

        all_settings = settings_manager.get_all_settings("user1")
        assert all_settings["workspace"] == "/ws/a"
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
        settings_manager.set_user_workspace("/ws/one", "user1")
        settings_manager.set_user_workspace("/ws/two", "user2")
        settings_manager.set_user_timezone("America/New_York", "user1")
        settings_manager.set_user_timezone("Asia/Tokyo", "user2")

        assert settings_manager.get_user_workspace("user1") == "/ws/one"
        assert settings_manager.get_user_workspace("user2") == "/ws/two"
        assert settings_manager.get_user_timezone("user1") == "America/New_York"
        assert settings_manager.get_user_timezone("user2") == "Asia/Tokyo"

    def test_set_setting_get_setting(self, settings_manager):
        """测试通用单键设置"""
        assert settings_manager.set_setting("custom_key", {"a": 1}) is True
        assert settings_manager.get_setting("custom_key") == {"a": 1}
        assert settings_manager.get_setting("missing", "fallback") == "fallback"

    def test_reset_settings(self, settings_manager):
        """测试重置用户设置为默认值"""
        settings_manager.set_user_workspace("/ws/a", "user1")
        settings_manager.set_user_timezone("Asia/Tokyo", "user1")

        assert settings_manager.reset_settings("user1") is True
        assert settings_manager.get_user_workspace("user1") is None
        assert settings_manager.get_user_timezone("user1") == "Asia/Shanghai"


class TestSettingsPersistence:
    """测试设置持久化"""

    def test_save_and_reload(self, tmp_path):
        """测试设置落盘并在新实例中恢复（扁平 user_{uid}_* 键）"""
        manager = _make_manager(tmp_path)
        manager.set_user_timezone("America/New_York", "user1")
        manager.set_user_workspace("/ws/a", "user1")

        settings_file = manager._settings_file
        assert settings_file.exists()

        data = json.loads(settings_file.read_text(encoding="utf-8"))
        assert data["user_user1_timezone"] == "America/New_York"

        # 新实例从同一文件恢复
        manager2 = _make_manager(tmp_path)
        assert manager2.get_user_timezone("user1") == "America/New_York"
        assert manager2.get_user_workspace("user1") == "/ws/a"

    def test_load_settings_on_init(self, tmp_path):
        """测试初始化时加载已有设置文件"""
        data_dir = tmp_path / "settings"
        data_dir.mkdir(parents=True)

        settings_file = data_dir / "settings.json"
        settings_file.write_text(
            json.dumps({"user_user1_timezone": "Asia/Tokyo",
                        "user_user1_workspace": "/ws/loaded"}),
            encoding="utf-8",
        )

        manager = _make_manager(tmp_path)

        assert manager.get_user_timezone("user1") == "Asia/Tokyo"
        assert manager.get_user_workspace("user1") == "/ws/loaded"

    def test_corrupt_settings_file_falls_back(self, tmp_path):
        """设置文件损坏时回落默认值不崩"""
        data_dir = tmp_path / "settings"
        data_dir.mkdir(parents=True)
        (data_dir / "settings.json").write_text("{broken json", encoding="utf-8")

        manager = _make_manager(tmp_path)

        assert manager.get_setting("timezone") == "Asia/Shanghai"


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
        manager.set_user_timezone("Asia/Tokyo", "user1")

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

        timezone = manager.get_user_timezone("nonexistent")
        all_settings = manager.get_all_settings("nonexistent")

        assert timezone == "Asia/Shanghai"
        # 标准键视图的闭集：`language` 随 §6-167 退役后不再出现（这一格同时是
        # 「白名单没被顺手加回别的键」的对账面——加一个键就得在这里改一次）
        assert set(all_settings.keys()) == {
            "timezone", "workspace", "theme",
            "font_size", "auto_save", "notifications", "debug_mode",
        }

    def test_empty_user_id(self, tmp_path):
        """测试空用户ID"""
        manager = _make_manager(tmp_path)

        manager.set_user_timezone("UTC", "")
        assert manager.get_user_timezone("") == "UTC"

    def test_special_characters_in_user_id(self, tmp_path):
        """测试用户ID包含特殊字符"""
        manager = _make_manager(tmp_path)

        user_id = "user@example.com"
        manager.set_user_workspace("/ws/special", user_id)
        assert manager.get_user_workspace(user_id) == "/ws/special"

    def test_invalid_timezone_stored_as_is(self, tmp_path):
        """测试无效时区原样存储（不做校验）"""
        manager = _make_manager(tmp_path)

        manager.set_user_timezone("Invalid/Timezone", "user1")
        assert manager.get_user_timezone("user1") == "Invalid/Timezone"

    def test_overwrite_existing_settings(self, tmp_path):
        """测试覆盖现有设置"""
        manager = _make_manager(tmp_path)

        manager.set_user_timezone("Asia/Tokyo", "user1")
        manager.set_user_timezone("Asia/Shanghai", "user1")

        assert manager.get_user_timezone("user1") == "Asia/Shanghai"
