"""
test_config_manager_persistence.py — P0-10: config_manager load/save 静默数据丢失修复

验证：
1. load 处理损坏 JSON 不崩溃
2. load 处理缺失文件优雅返回
3. save 处理权限错误不崩溃
4. save 创建父目录
5. load/save 失败时记录日志（mock logger 验证调用）
"""
import json
from unittest.mock import patch

import pytest

from neurova.core.config_manager import ConfigManager


class TestLoadErrorHandling:
    def test_load_handles_corrupt_json_without_crash(self, tmp_path):
        """损坏 JSON 不应导致崩溃，应记录 warning"""
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{invalid json content", encoding="utf-8")
        cm = ConfigManager(str(cfg_file))
        # 不应抛异常
        cm.load()
        # 数据保持为空（未加载）
        assert cm.get_all() == {}

    def test_load_handles_missing_file_gracefully(self, tmp_path):
        """缺失文件应优雅返回，不抛异常"""
        cm = ConfigManager(str(tmp_path / "nonexistent.json"))
        cm.load()
        assert cm.get_all() == {}

    def test_load_logs_warning_on_corrupt_json(self, tmp_path):
        """损坏 JSON 应触发 logger.warning"""
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{invalid", encoding="utf-8")
        cm = ConfigManager(str(cfg_file))
        with patch("neurova.core.config_manager.logger") as mock_logger:
            cm.load()
            assert mock_logger.warning.called

    def test_load_preserves_existing_data_on_error(self, tmp_path):
        """load 失败时应保留已存在的内存配置"""
        cfg_file = tmp_path / "broken.json"
        cfg_file.write_text("{invalid", encoding="utf-8")
        cm = ConfigManager(str(cfg_file))
        cm.set("existing_key", "existing_value")
        cm.load()
        assert cm.get("existing_key") == "existing_value"


class TestSaveErrorHandling:
    def test_save_handles_permission_error_without_crash(self, tmp_path):
        """权限错误不应导致崩溃，应记录 error"""
        cm = ConfigManager(str(tmp_path / "config.json"))
        cm.set("key", "value")
        with patch("neurova.core.config_manager.json.dump", side_effect=OSError("disk full")):
            with patch("neurova.core.config_manager.logger") as mock_logger:
                cm.save()
                assert mock_logger.error.called

    def test_save_creates_parent_directory(self, tmp_path):
        """save 应自动创建父目录"""
        nested_path = tmp_path / "deep" / "nested" / "config.json"
        cm = ConfigManager(str(nested_path))
        cm.set("key", "value")
        cm.save()
        assert nested_path.exists()
        assert json.loads(nested_path.read_text(encoding="utf-8"))["key"] == "value"

    def test_save_logs_error_on_oserror(self, tmp_path):
        """OSError 应触发 logger.error"""
        cm = ConfigManager(str(tmp_path / "config.json"))
        cm.set("key", "value")
        with patch("neurova.core.config_manager.Path.mkdir", side_effect=OSError("permission denied")):
            with patch("neurova.core.config_manager.logger") as mock_logger:
                cm.save()
                assert mock_logger.error.called


class TestLoggerImport:
    def test_logger_is_available(self):
        """config_manager 模块应导出 logger 实例"""
        from neurova.core import config_manager
        assert hasattr(config_manager, "logger")
        assert config_manager.logger is not None
