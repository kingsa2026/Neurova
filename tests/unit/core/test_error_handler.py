"""
错误处理器测试
测试 ErrorHandler 的各种功能，包括错误记录、恢复策略、统计等。
"""

import pytest
import time
from unittest.mock import MagicMock

from neurova.core.error_handler import (
    ErrorHandler,
    ErrorCode,
    ErrorRecord,
    NeurovaError,
    ModuleLoadError,
    ModuleDependencyError,
    StateError,
    ConfigError,
    get_error_handler,
    reset_error_handler,
)


class TestErrorCode:
    """测试错误码枚举"""

    def test_error_code_values(self):
        """测试错误码值"""
        assert ErrorCode.UNKNOWN.value == 0
        assert ErrorCode.INVALID_ARGUMENT.value == 1001
        assert ErrorCode.NOT_FOUND.value == 1003
        assert ErrorCode.MODULE_LOAD_FAILED.value == 2001
        assert ErrorCode.CONFIG_INVALID.value == 3001
        assert ErrorCode.CONFIG_MISSING.value == 3002
        assert ErrorCode.AUTH_FAILED.value == 5001
        assert ErrorCode.CONNECTION_FAILED.value == 4002
        assert ErrorCode.TIMEOUT.value == 1006


class TestErrorRecord:
    """测试错误记录"""

    def test_create_error_record(self):
        """测试创建错误记录"""
        ts = time.time()
        record = ErrorRecord(
            timestamp=ts,
            code=ErrorCode.INVALID_ARGUMENT,
            message="Invalid parameter",
            module="test_module",
        )
        assert record.code == ErrorCode.INVALID_ARGUMENT
        assert record.message == "Invalid parameter"
        assert record.module == "test_module"

    def test_error_record_to_dict(self):
        """测试错误记录转换为字典"""
        ts = time.time()
        record = ErrorRecord(
            timestamp=ts,
            code=ErrorCode.NOT_FOUND,
            message="Not found",
            module="test",
        )
        data = record.to_dict()
        assert data['code'] == 1003
        assert data['message'] == 'Not found'
        assert data['module'] == 'test'
        assert 'timestamp' in data


class TestNeurovaError:
    """测试基础异常类"""

    def test_create_neurova_error(self):
        """测试创建基础异常"""
        error = NeurovaError(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Invalid argument",
            context={"field": "name"},
        )
        assert error.code == ErrorCode.INVALID_ARGUMENT
        assert error.message == "Invalid argument"
        assert error.context == {"field": "name"}

    def test_neurova_error_to_record(self):
        """测试异常转换为记录"""
        error = NeurovaError(
            code=ErrorCode.NOT_FOUND,
            message="Resource not found",
            module="test_module",
        )
        record = error.to_record()
        assert record.code == ErrorCode.NOT_FOUND
        assert record.message == "Resource not found"
        assert record.module == "test_module"

    def test_module_load_error(self):
        """测试模块加载错误"""
        error = ModuleLoadError("test_module", "dependency missing")
        assert error.code == ErrorCode.MODULE_LOAD_FAILED
        assert "test_module" in error.message
        assert error.module == "test_module"

    def test_module_dependency_error(self):
        """测试模块依赖错误"""
        error = ModuleDependencyError("test_module", "dep1")
        assert error.code == ErrorCode.MODULE_DEPENDENCY_MISSING
        assert "test_module" in error.message
        assert error.context["dependency"] == "dep1"

    def test_state_error(self):
        """测试状态错误"""
        error = StateError("State conflict", module="test_module")
        assert error.code == ErrorCode.INVALID_STATE
        assert error.message == "State conflict"
        assert error.module == "test_module"

    def test_config_error(self):
        """测试配置错误"""
        error = ConfigError("Invalid config", module="test_module")
        assert error.code == ErrorCode.CONFIG_INVALID
        assert error.message == "Invalid config"


class TestErrorHandler:
    """测试错误处理器"""

    @pytest.fixture
    def error_handler(self):
        """创建错误处理器实例"""
        reset_error_handler()
        return ErrorHandler(max_records=100)

    @pytest.fixture
    def mock_error_callback(self):
        """创建模拟错误回调"""
        return MagicMock()

    def test_init(self, error_handler):
        """测试初始化"""
        assert error_handler is not None
        assert len(error_handler._records) == 0

    def test_handle_neurova_error(self, error_handler):
        """测试处理 NeurovaError"""
        error = NeurovaError(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Invalid argument",
        )
        record = error_handler.handle(error, module="test_module")

        assert record is not None
        assert record.code == ErrorCode.INVALID_ARGUMENT
        assert record.message == "Invalid argument"
        assert record.module == "test_module"
        assert len(error_handler._records) == 1

    def test_handle_generic_exception(self, error_handler):
        """测试处理普通异常"""
        error = ValueError("Test error")
        record = error_handler.handle(error, module="test_module")

        assert record is not None
        assert record.code == ErrorCode.UNKNOWN
        assert record.message == "Test error"
        assert record.module == "test_module"

    def test_handle_with_context(self, error_handler):
        """测试处理带上下文的错误"""
        error = NeurovaError(
            code=ErrorCode.NOT_FOUND,
            message="Not found",
        )
        record = error_handler.handle(
            error,
            module="test_module",
            context={"id": "123"},
        )

        assert record.context["id"] == "123"

    def test_handle_code(self, error_handler):
        """测试处理错误码"""
        record = error_handler.handle_code(
            ErrorCode.TIMEOUT,
            message="Operation timeout",
            module="test_module",
        )

        assert record.code == ErrorCode.TIMEOUT
        assert record.message == "Operation timeout"
        assert record.module == "test_module"

    def test_register_recovery(self, error_handler):
        """测试注册恢复策略"""
        def recovery(exception, module):
            return True

        error_handler.register_recovery(ErrorCode.TIMEOUT, recovery)
        assert ErrorCode.TIMEOUT in error_handler._recovery_strategies

    def test_on_error_callback(self, error_handler, mock_error_callback):
        """测试注册错误回调"""
        error_handler.on_error(mock_error_callback)
        assert mock_error_callback in error_handler._error_callbacks

    def test_remove_error_callback(self, error_handler, mock_error_callback):
        """测试移除错误回调"""
        error_handler.on_error(mock_error_callback)
        result = error_handler.remove_error_callback(mock_error_callback)
        assert result is True
        assert mock_error_callback not in error_handler._error_callbacks

    def test_remove_nonexistent_callback(self, error_handler):
        """测试移除不存在的回调"""
        callback = MagicMock()
        result = error_handler.remove_error_callback(callback)
        assert result is False

    def test_get_records(self, error_handler):
        """测试获取错误记录"""
        for i in range(5):
            error_handler.handle_code(
                ErrorCode.UNKNOWN,
                message=f"Error {i}",
            )

        records = error_handler.get_records()
        assert len(records) == 5

    def test_get_records_by_module(self, error_handler):
        """测试按模块过滤记录"""
        error_handler.handle_code(
            ErrorCode.UNKNOWN,
            message="err1",
            module="module1",
        )
        error_handler.handle_code(
            ErrorCode.INVALID_ARGUMENT,
            message="err2",
            module="module2",
        )

        records = error_handler.get_records(module="module1")
        assert len(records) == 1
        assert records[0].module == "module1"

    def test_get_records_by_code(self, error_handler):
        """测试按错误码过滤记录"""
        error_handler.handle_code(ErrorCode.INVALID_ARGUMENT, message="err1")
        error_handler.handle_code(ErrorCode.TIMEOUT, message="err2")
        error_handler.handle_code(ErrorCode.INVALID_ARGUMENT, message="err3")

        records = error_handler.get_records(code=ErrorCode.INVALID_ARGUMENT)
        assert len(records) == 2

    def test_get_records_with_limit(self, error_handler):
        """测试获取记录数量限制"""
        for i in range(20):
            error_handler.handle_code(
                ErrorCode.UNKNOWN,
                message=f"Error {i}",
            )

        records = error_handler.get_records(limit=5)
        assert len(records) == 5

    def test_get_stats(self, error_handler):
        """测试获取错误统计"""
        error_handler.handle_code(ErrorCode.UNKNOWN, message="e1")
        error_handler.handle_code(ErrorCode.UNKNOWN, message="e2")
        error_handler.handle_code(ErrorCode.INVALID_ARGUMENT, message="e3")

        stats = error_handler.get_stats()
        assert stats['total_errors'] == 3
        assert stats['by_code']['UNKNOWN'] == 2
        assert stats['by_code']['INVALID_ARGUMENT'] == 1

    def test_clear(self, error_handler):
        """测试清空记录"""
        error_handler.handle_code(ErrorCode.UNKNOWN, message="e1")
        error_handler.handle_code(ErrorCode.INVALID_ARGUMENT, message="e2")

        error_handler.clear()
        assert len(error_handler._records) == 0

    def test_generate_report(self, error_handler):
        """测试生成错误报告"""
        error_handler.handle_code(
            ErrorCode.UNKNOWN,
            module="test",
            message="Test error",
        )

        report = error_handler.generate_report()
        assert report["total_errors"] == 1
        assert "UNKNOWN" in report["by_code"]

    def test_max_records_limit(self, error_handler):
        """测试最大记录数限制"""
        for i in range(150):
            error_handler.handle_code(
                ErrorCode.UNKNOWN,
                message=f"Error {i}",
            )

        assert len(error_handler._records) == 100


class TestGetErrorHandler:
    """测试获取错误处理器单例"""

    def test_get_error_handler(self):
        """测试获取错误处理器实例"""
        reset_error_handler()
        handler1 = get_error_handler()
        handler2 = get_error_handler()
        assert handler1 is handler2

    def test_reset_error_handler(self):
        """测试重置错误处理器"""
        reset_error_handler()
        handler1 = get_error_handler()
        reset_error_handler()
        handler2 = get_error_handler()
        assert handler1 is not handler2


class TestEdgeCases:
    """测试边界情况"""

    def test_empty_error_message(self):
        """测试空错误消息"""
        error = NeurovaError(code=ErrorCode.UNKNOWN)
        assert error.message == ""

    def test_error_record_default_values(self):
        """测试错误记录默认值"""
        record = ErrorRecord(
            timestamp=time.time(),
            code=ErrorCode.UNKNOWN,
            message="Test",
            module="",
        )
        assert record.context == {}

    def test_multiple_callbacks(self):
        """测试多个回调"""
        reset_error_handler()
        handler = ErrorHandler()

        callback1 = MagicMock()
        callback2 = MagicMock()

        handler.on_error(callback1)
        handler.on_error(callback2)

        error = NeurovaError(code=ErrorCode.UNKNOWN)
        handler.handle(error)

        assert callback1.called
        assert callback2.called

    def test_callback_exception_handling(self):
        """测试回调异常处理"""
        reset_error_handler()
        handler = ErrorHandler()

        def bad_callback(record):
            raise Exception("Callback error")

        handler.on_error(bad_callback)

        error = NeurovaError(code=ErrorCode.UNKNOWN)
        record = handler.handle(error)

        assert record is not None
