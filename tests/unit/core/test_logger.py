"""
LogManager 单元测试
"""

import unittest
import time
from unittest.mock import patch, MagicMock

from neurova.core.logger import (
    LogManager,
    LogEntry,
    LogLevel,
    get_log_manager,
    reset_log_manager,
    _sanitize_context,
)


class TestLogManager(unittest.TestCase):
    """LogManager 测试类"""

    def setUp(self) -> None:
        """测试前初始化"""
        reset_log_manager()
        self.log_manager = LogManager()

    def tearDown(self) -> None:
        """测试后清理"""
        reset_log_manager()

    def test_log_creation(self) -> None:
        """测试日志记录（契约：log 方法返回 None，条目经 get_entries 取回）"""
        result = self.log_manager.info(
            module="test_module",
            message="Test message",
            context={"key": "value"}
        )

        self.assertIsNone(result)

        entries = self.log_manager.get_entries(module="test_module")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0].module, "test_module")
        self.assertEqual(entries[0].message, "Test message")
        self.assertEqual(entries[0].context, {"key": "value"})

    def test_log_levels(self) -> None:
        """测试不同日志级别（各级别方法落盘后级别正确）"""
        self.log_manager.set_default_level(LogLevel.DEBUG)
        levels = [
            (LogLevel.DEBUG, self.log_manager.debug),
            (LogLevel.INFO, self.log_manager.info),
            (LogLevel.WARNING, self.log_manager.warning),
            (LogLevel.ERROR, self.log_manager.error),
            (LogLevel.CRITICAL, self.log_manager.critical),
        ]

        for level, method in levels:
            method("test_module", f"Test {level.name}")
            entries = self.log_manager.get_entries(limit=1)
            self.assertEqual(entries[-1].level, level)

    def test_log_filtering(self) -> None:
        """测试日志过滤（低于默认级别的日志被丢弃）"""
        self.log_manager.set_default_level(LogLevel.WARNING)

        # DEBUG 日志应该被过滤（不入条目表）
        self.log_manager.debug("test_module", "Debug message")
        self.assertEqual(self.log_manager.entry_count(), 0)

        # WARNING 日志应该被记录
        self.log_manager.warning("test_module", "Warning message")
        self.assertEqual(self.log_manager.entry_count(), 1)

    def test_module_level_filtering(self) -> None:
        """测试模块级别过滤（per-module 覆盖默认级别）"""
        self.log_manager.set_default_level(LogLevel.INFO)
        self.log_manager.set_level("special_module", LogLevel.DEBUG)

        # 默认模块受默认级别限制（DEBUG 被丢弃）
        self.log_manager.debug("normal_module", "Debug message")
        entries = self.log_manager.get_entries(module="normal_module")
        self.assertEqual(len(entries), 0)

        # special_module 放行 DEBUG
        self.log_manager.debug("special_module", "Debug message")
        entries = self.log_manager.get_entries(module="special_module")
        self.assertEqual(len(entries), 1)

    def test_get_entries(self) -> None:
        """测试获取日志条目"""
        self.log_manager.info("module1", "Message 1")
        self.log_manager.warning("module1", "Message 2")
        self.log_manager.error("module2", "Message 3")

        # 获取所有条目
        all_entries = self.log_manager.get_entries(limit=10)
        self.assertEqual(len(all_entries), 3)

        # 按模块过滤
        module1_entries = self.log_manager.get_entries(module="module1")
        self.assertEqual(len(module1_entries), 2)

        # 按日志级别过滤
        error_entries = self.log_manager.get_entries(level=LogLevel.ERROR)
        self.assertEqual(len(error_entries), 1)

    def test_get_stats(self) -> None:
        """测试获取统计信息"""
        self.log_manager.info("module1", "Message 1")
        self.log_manager.info("module1", "Message 2")
        self.log_manager.error("module2", "Message 3")

        stats = self.log_manager.get_stats()
        self.assertEqual(stats["total_logs"], 3)
        self.assertEqual(stats["by_level"][LogLevel.INFO.value], 2)
        self.assertEqual(stats["by_level"][LogLevel.ERROR.value], 1)

    def test_clear_logs(self) -> None:
        """测试清空日志"""
        self.log_manager.info("test_module", "Test message")
        self.assertEqual(self.log_manager.entry_count(), 1)

        self.log_manager.clear()
        self.assertEqual(self.log_manager.entry_count(), 0)

    def test_rotate_logs(self) -> None:
        """测试日志轮转"""
        with patch("neurova.core.logger.time.time") as mock_time:
            mock_time.return_value = 100.0
            self.log_manager.info("test_module", "Old message")

            mock_time.return_value = 200.0
            self.log_manager.info("test_module", "New message")

            # 轮转掉50秒前的日志（max_age_hours 单位是小时）
            mock_time.return_value = 200.0
            removed = self.log_manager.rotate(max_age_hours=50.0 / 3600.0)
            self.assertEqual(removed, 1)
            self.assertEqual(self.log_manager.entry_count(), 1)

    def test_sensitive_data_sanitization(self) -> None:
        """测试敏感数据脱敏"""
        context = {
            "password": "secret123",
            "token": "abc123",
            "normal_key": "normal_value",
            "nested": {"api_key": "secret_api"}
        }

        sanitized = _sanitize_context(context)
        self.assertEqual(sanitized["password"], "***")
        self.assertEqual(sanitized["token"], "***")
        self.assertEqual(sanitized["normal_key"], "normal_value")
        self.assertEqual(sanitized["nested"]["api_key"], "***")

    def test_global_log_manager(self) -> None:
        """测试全局日志管理器"""
        manager1 = get_log_manager()
        manager2 = get_log_manager()
        self.assertIs(manager1, manager2)

    def test_log_entry_to_dict(self) -> None:
        """测试日志条目转字典"""
        entry = LogEntry(
            timestamp=123.456,
            level=LogLevel.INFO,
            module="test_module",
            message="Test message",
            context={"key": "value"}
        )

        entry_dict = entry.to_dict()
        self.assertEqual(entry_dict["timestamp"], 123.456)
        self.assertEqual(entry_dict["level"], "INFO")
        self.assertEqual(entry_dict["module"], "test_module")

    def test_log_entry_json_roundtrip(self) -> None:
        """测试日志条目 JSON 序列化（契约：to_dict + json.dumps）"""
        import json as jsonlib

        entry = LogEntry(
            timestamp=123.456,
            level=LogLevel.INFO,
            module="test_module",
            message="Test message"
        )

        json_str = jsonlib.dumps(entry.to_dict(), ensure_ascii=False)
        self.assertIn('"level": "INFO"', json_str)
        self.assertIn('"message": "Test message"', json_str)


if __name__ == "__main__":
    unittest.main()
