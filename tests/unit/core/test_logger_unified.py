"""
统一日志库 get_logger 函数测试

验证 neurova.core.logger.get_logger 的行为：
- 函数存在且可调用
- 返回 logging.Logger 实例
- 单例缓存：同名多次调用返回同一实例
- 不同名返回不同实例
- 日志输出方法可用（info/warning/error/debug/critical）
"""

import logging

import pytest

from neurova.core.logger import get_logger


class TestGetLoggerExists:
    """验证 get_logger 函数存在且可调用"""

    def test_get_logger_is_callable(self) -> None:
        """get_logger 应当是可调用对象"""
        assert callable(get_logger)

    def test_get_logger_returns_logger_instance(self) -> None:
        """get_logger 应当返回 logging.Logger 实例"""
        logger = get_logger("neurova.test.unified.exists")
        assert isinstance(logger, logging.Logger)


class TestGetLoggerSingleton:
    """验证单例缓存行为"""

    def test_same_name_returns_same_instance(self) -> None:
        """同名多次调用应返回同一实例（单例缓存）"""
        name = "neurova.test.unified.singleton_same"
        logger1 = get_logger(name)
        logger2 = get_logger(name)
        assert logger1 is logger2

    def test_different_name_returns_different_instance(self) -> None:
        """不同名应返回不同实例"""
        logger_a = get_logger("neurova.test.unified.singleton_a")
        logger_b = get_logger("neurova.test.unified.singleton_b")
        assert logger_a is not logger_b

    def test_cache_returns_cached_object(self) -> None:
        """缓存命中时应返回缓存中的同一对象"""
        name = "neurova.test.unified.cache_hit"
        logger1 = get_logger(name)
        # 再次获取，应命中缓存
        logger2 = get_logger(name)
        assert logger1 is logger2
        # 验证 name 属性一致
        assert logger1.name == name
        assert logger2.name == name


class TestGetLoggerLoggingMethods:
    """验证返回的 logger 具备标准日志方法"""

    def test_logger_has_info_method(self) -> None:
        """logger 应具备 info 方法"""
        logger = get_logger("neurova.test.unified.methods.info")
        assert hasattr(logger, "info")
        assert callable(logger.info)

    def test_logger_has_warning_method(self) -> None:
        """logger 应具备 warning 方法"""
        logger = get_logger("neurova.test.unified.methods.warning")
        assert hasattr(logger, "warning")
        assert callable(logger.warning)

    def test_logger_has_error_method(self) -> None:
        """logger 应具备 error 方法"""
        logger = get_logger("neurova.test.unified.methods.error")
        assert hasattr(logger, "error")
        assert callable(logger.error)

    def test_logger_has_debug_method(self) -> None:
        """logger 应具备 debug 方法"""
        logger = get_logger("neurova.test.unified.methods.debug")
        assert hasattr(logger, "debug")
        assert callable(logger.debug)

    def test_logger_has_critical_method(self) -> None:
        """logger 应具备 critical 方法"""
        logger = get_logger("neurova.test.unified.methods.critical")
        assert hasattr(logger, "critical")
        assert callable(logger.critical)

    def test_logger_can_emit_log_records(self, caplog) -> None:
        """logger 应能正常发出日志记录"""
        name = "neurova.test.unified.emit"
        logger = get_logger(name)
        logger.setLevel(logging.DEBUG)
        with caplog.at_level(logging.DEBUG, logger=name):
            logger.info("test info message")
            logger.warning("test warning message")
            logger.error("test error message")
        # 验证日志记录被捕获
        assert any("test info message" in r.message for r in caplog.records)
        assert any("test warning message" in r.message for r in caplog.records)
        assert any("test error message" in r.message for r in caplog.records)


class TestGetLoggerDefaultName:
    """验证默认参数行为"""

    def test_get_logger_without_args(self) -> None:
        """不传参数时应使用默认 name"""
        logger = get_logger()
        assert isinstance(logger, logging.Logger)
        # 默认 name 应为 "neurova"
        assert logger.name == "neurova"
