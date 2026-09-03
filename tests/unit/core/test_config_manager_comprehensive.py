"""
ConfigManager 全面单元测试
测试 neurova.core.config_manager 模块的所有功能
"""
import pytest
import os
import json
from pathlib import Path

from neurova.core.config_manager import ConfigManager


class TestConfigManagerBasic:
    """测试 ConfigManager 基础功能"""

    @pytest.fixture
    def config_manager(self, tmp_path):
        """创建 ConfigManager 实例"""
        config_file = tmp_path / "test_config.json"
        manager = ConfigManager(config_path=str(config_file))
        yield manager

    def test_set_and_get(self, config_manager):
        """测试设置和获取配置"""
        config_manager.set("test_key", "test_value")
        assert config_manager.get("test_key") == "test_value"

    def test_get_with_default(self, config_manager):
        """测试获取不存在的配置(使用默认值)"""
        assert config_manager.get("nonexistent") is None
        assert config_manager.get("nonexistent", default="default") == "default"

    def test_has(self, config_manager):
        """测试检查配置是否存在"""
        assert config_manager.has("nonexistent") is False
        config_manager.set("exists", "value")
        assert config_manager.has("exists") is True

    def test_delete(self, config_manager):
        """测试删除配置"""
        config_manager.set("to_delete", "value")
        assert config_manager.has("to_delete") is True
        result = config_manager.delete("to_delete")
        assert result is True
        assert config_manager.has("to_delete") is False

    def test_delete_nonexistent(self, config_manager):
        """测试删除不存在的配置"""
        result = config_manager.delete("nonexistent")
        assert result is False

    def test_get_all(self, config_manager):
        """测试获取所有配置"""
        config_manager.set("key1", "value1")
        config_manager.set("key2", "value2")
        config_manager.set("key3", "value3")
        all_configs = config_manager.get_all()
        assert len(all_configs) == 3
        assert all_configs["key1"] == "value1"

    def test_save_and_load(self, config_manager):
        """测试保存配置"""
        config_manager.set("save_key1", "value1")
        config_manager.set("save_key2", 42)
        config_manager.save()
        assert config_manager.get("save_key1") == "value1"

    def test_load_nonexistent(self, config_manager):
        """测试加载不存在的文件"""
        config_manager.load("/nonexistent/path.json")
        assert config_manager.get("nonexistent") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
