"""
配置管理器测试
测试 ConfigManager 的各种功能，包括配置获取、设置、删除、持久化等。
"""

import pytest
import json
import tempfile
import os
from neurova.core.config_manager import ConfigManager


class TestConfigManager:
    """测试配置管理器"""

    @pytest.fixture
    def config_manager(self):
        """创建配置管理器实例"""
        return ConfigManager()

    def test_init(self, config_manager):
        """测试初始化"""
        assert config_manager is not None
        assert config_manager.get_all() == {}

    def test_set_and_get(self, config_manager):
        """测试设置和获取配置"""
        config_manager.set("test.key", "test_value")
        assert config_manager.get("test.key") == "test_value"

    def test_get_nonexistent(self, config_manager):
        """测试获取不存在的配置"""
        value = config_manager.get("nonexistent", default="default")
        assert value == "default"

    def test_get_with_default_none(self, config_manager):
        """测试获取不存在的配置（默认值为 None）"""
        value = config_manager.get("nonexistent")
        assert value is None

    def test_delete(self, config_manager):
        """测试删除配置"""
        config_manager.set("test.key", "value")
        result = config_manager.delete("test.key")
        assert result is True
        assert config_manager.has("test.key") is False

    def test_delete_nonexistent(self, config_manager):
        """测试删除不存在的配置"""
        result = config_manager.delete("nonexistent")
        assert result is False

    def test_has(self, config_manager):
        """测试检查配置是否存在"""
        config_manager.set("test.key", "value")
        assert config_manager.has("test.key") is True
        assert config_manager.has("nonexistent") is False

    def test_get_all(self, config_manager):
        """测试获取所有配置"""
        config_manager.set("key1", "value1")
        config_manager.set("key2", "value2")
        all_configs = config_manager.get_all()
        assert len(all_configs) == 2
        assert all_configs["key1"] == "value1"
        assert all_configs["key2"] == "value2"

    def test_clear(self, config_manager):
        """测试清空配置"""
        config_manager.set("key1", "value1")
        config_manager.set("key2", "value2")
        config_manager.clear()
        assert config_manager.get_all() == {}

    def test_save_to_file(self, config_manager):
        """测试保存配置到文件"""
        config_manager.set("key1", "value1")
        config_manager.set("key2", 123)

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            temp_path = f.name

        try:
            config_manager.save(temp_path)
            with open(temp_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            assert data["key1"] == "value1"
            assert data["key2"] == 123
        finally:
            os.unlink(temp_path)

    def test_load_from_file(self, config_manager):
        """测试从文件加载配置"""
        config_data = {"key1": "value1", "key2": 123}

        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            config_manager.load(temp_path)
            assert config_manager.get("key1") == "value1"
            assert config_manager.get("key2") == 123
        finally:
            os.unlink(temp_path)

    def test_load_from_env(self, config_manager):
        """测试从环境变量加载"""
        os.environ["NEUVA_TEST_KEY"] = "env_value"
        try:
            count = config_manager.load_from_env("NEUVA_")
            assert count >= 1
            assert config_manager.get("test_key") == "env_value"
        finally:
            del os.environ["NEUVA_TEST_KEY"]

    def test_nested_key(self, config_manager):
        """测试嵌套键"""
        config_manager.set("server.port", 8080)
        assert config_manager.get("server.port") == 8080

    def test_complex_value(self, config_manager):
        """测试复杂值"""
        complex_value = {
            "list": [1, 2, 3],
            "nested": {"key": "value"},
        }
        config_manager.set("complex", complex_value)
        retrieved = config_manager.get("complex")
        assert retrieved["list"] == [1, 2, 3]

    def test_none_value(self, config_manager):
        """测试 None 值"""
        config_manager.set("null_key", None)
        assert config_manager.get("null_key") is None

    def test_boolean_value(self, config_manager):
        """测试布尔值"""
        config_manager.set("enabled", True)
        assert config_manager.get("enabled") is True

    def test_update_existing(self, config_manager):
        """测试更新已存在的配置"""
        config_manager.set("key", "value1")
        config_manager.set("key", "value2")
        assert config_manager.get("key") == "value2"

    def test_init_with_config_path(self):
        """测试带配置路径初始化"""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.json') as f:
            json.dump({"init_key": "init_value"}, f)
            temp_path = f.name

        try:
            manager = ConfigManager(config_path=temp_path)
            manager.load()
            assert manager.get("init_key") == "init_value"
        finally:
            os.unlink(temp_path)
