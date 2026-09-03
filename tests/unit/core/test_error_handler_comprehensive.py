"""
ErrorHandler 全面单元测试
测试 neurova.core.error_handler 模块的所有功能
"""
import pytest
import sys
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from neurova.core.error_handler import (
    ErrorCode,
    ErrorRecord,
    NeurovaError,
    ModuleLoadError,
    ModuleDependencyError,
    StateError,
    ConfigError,
    ErrorHandler,
    get_error_handler,
    reset_error_handler,
)


class TestErrorCode:
    """测试错误码枚举"""

    def test_common_codes(self):
        """测试通用错误码"""
        assert ErrorCode.UNKNOWN_ERROR == 1000
        assert ErrorCode.INVALID_ARGUMENT == 1001
        assert ErrorCode.NOT_FOUND == 1002
        assert ErrorCode.ALREADY_EXISTS == 1003
        assert ErrorCode.PERMISSION_DENIED == 1004
        assert ErrorCode.TIMEOUT == 1005
        assert ErrorCode.RATE_LIMIT_EXCEEDED == 1006

    def test_module_codes(self):
        """测试模块错误码"""
        assert ErrorCode.MODULE_LOAD_FAILED == 2001
        assert ErrorCode.MODULE_START_FAILED == 2002
        assert ErrorCode.MODULE_STOP_FAILED == 2003
        assert ErrorCode.MODULE_DEPENDENCY_MISSING == 2004
        assert ErrorCode.MODULE_VERSION_CONFLICT == 2005

    def test_state_codes(self):
        """测试状态错误码"""
        assert ErrorCode.STATE_NOT_FOUND == 3001
        assert ErrorCode.STATE_CONFLICT == 3002
        assert ErrorCode.STATE_ROLLBACK_FAILED == 3003

    def test_config_codes(self):
        """测试配置错误码"""
        assert ErrorCode.CONFIG_MISSING == 4001
        assert ErrorCode.CONFIG_INVALID == 4002
        assert ErrorCode.CONFIG_LOAD_FAILED == 4003

    def test_event_codes(self):
        """测试事件错误码"""
        assert ErrorCode.EVENT_HANDLER_FAILED == 5001
        assert ErrorCode.EVENT_BUS_STOPPED == 5002

    def test_network_codes(self):
        """测试网络错误码"""
        assert ErrorCode.CONNECTION_FAILED == 6001
        assert ErrorCode.REQUEST_FAILED == 6002
        assert ErrorCode.RESPONSE_INVALID == 6003


class TestErrorRecord:
    """测试 ErrorRecord 数据类"""

    def test_record_creation_minimal(self):
        """测试最小参数创建错误记录"""
        record = ErrorRecord(code=ErrorCode.UNKNOWN_ERROR, message="Test error")
        assert record.code == ErrorCode.UNKNOWN_ERROR
        assert record.message == "Test error"
        assert record.module is None
        assert record.details == {}
        assert isinstance(record.timestamp, float)
        assert record.traceback is None
        assert record.recovered is False

    def test_record_creation_full(self):
        """测试完整参数创建错误记录"""
        details = {"key": "value"}
        tb = "Traceback (most recent call last):\n  ..."
        
        record = ErrorRecord(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Invalid argument: x",
            module="test_module",
            details=details,
            timestamp=1234567890.0,
            traceback=tb,
            recovered=True,
        )
        
        assert record.code == ErrorCode.INVALID_ARGUMENT
        assert record.message == "Invalid argument: x"
        assert record.module == "test_module"
        assert record.details == details
        assert record.timestamp == 1234567890.0
        assert record.traceback == tb
        assert record.recovered is True

    def test_record_to_dict(self):
        """测试转换为字典"""
        record = ErrorRecord(
            code=ErrorCode.MODULE_LOAD_FAILED,
            message="Module load failed",
            module="test_module",
            details={"module_name": "test", "reason": "not found"},
            recovered=False,
        )
        
        result = record.to_dict()
        assert result["code"] == int(ErrorCode.MODULE_LOAD_FAILED)
        assert result["code_name"] == "MODULE_LOAD_FAILED"
        assert result["message"] == "Module load failed"
        assert result["module"] == "test_module"
        assert result["recovered"] is False


class TestNeurovaError:
    """测试 NeurovaError 基础异常类"""

    def test_default_error(self):
        """测试默认错误"""
        error = NeurovaError()
        assert error.code == ErrorCode.UNKNOWN_ERROR
        assert error.message == "未知错误"
        assert error.details == {}

    def test_custom_code(self):
        """测试自定义错误码"""
        error = NeurovaError(code=ErrorCode.INVALID_ARGUMENT)
        assert error.code == ErrorCode.INVALID_ARGUMENT
        assert error.message == "无效参数"

    def test_custom_message(self):
        """测试自定义消息"""
        error = NeurovaError(
            code=ErrorCode.NOT_FOUND,
            message="Resource not found: test",
        )
        assert error.code == ErrorCode.NOT_FOUND
        assert error.message == "Resource not found: test"

    def test_with_details(self):
        """测试带详细信息的错误"""
        details = {"resource_id": "123", "resource_type": "user"}
        error = NeurovaError(
            code=ErrorCode.NOT_FOUND,
            message="User not found",
            details=details,
        )
        assert error.details == details

    def test_to_record(self):
        """测试转换为错误记录"""
        error = NeurovaError(
            code=ErrorCode.TIMEOUT,
            message="Operation timed out",
            details={"timeout": 30},
        )
        
        record = error.to_record(module="test_module")
        assert record.code == ErrorCode.TIMEOUT
        assert record.message == "Operation timed out"
        assert record.module == "test_module"
        assert record.details == {"timeout": 30}
        assert record.traceback is not None  # traceback.format_exc() 应该返回字符串


class TestModuleLoadError:
    """测试 ModuleLoadError 异常类"""

    def test_module_load_error(self):
        """测试模块加载错误"""
        error = ModuleLoadError(module_name="test_module", reason="File not found")
        
        assert error.code == ErrorCode.MODULE_LOAD_FAILED
        assert "test_module" in error.message
        assert "File not found" in error.message
        assert error.details["module_name"] == "test_module"
        assert error.details["reason"] == "File not found"


class TestModuleDependencyError:
    """测试 ModuleDependencyError 异常类"""

    def test_module_dependency_error(self):
        """测试模块依赖错误"""
        error = ModuleDependencyError(
            module_name="test_module",
            missing_deps=["dep1", "dep2"],
        )
        
        assert error.code == ErrorCode.MODULE_DEPENDENCY_MISSING
        assert "test_module" in error.message
        assert "dep1" in error.message
        assert "dep2" in error.message
        assert error.details["module_name"] == "test_module"
        assert error.details["missing_deps"] == ["dep1", "dep2"]


class TestStateError:
    """测试 StateError 异常类"""

    def test_state_error(self):
        """测试状态错误"""
        error = StateError(
            message="Invalid state transition",
            details={"from": "stopped", "to": "running"},
        )
        
        assert error.code == ErrorCode.STATE_CONFLICT
        assert error.message == "Invalid state transition"
        assert error.details["from"] == "stopped"
        assert error.details["to"] == "running"


class TestConfigError:
    """测试 ConfigError 异常类"""

    def test_config_error(self):
        """测试配置错误"""
        error = ConfigError(
            message="Invalid configuration: port must be integer",
            details={"key": "server.port", "value": "not_int"},
        )
        
        assert error.code == ErrorCode.CONFIG_INVALID
        assert error.message == "Invalid configuration: port must be integer"
        assert error.details["key"] == "server.port"


class TestErrorHandlerBasic:
    """测试 ErrorHandler 基础功能"""

    @pytest.fixture
    def error_handler(self):
        """创建 ErrorHandler 实例"""
        handler = ErrorHandler(event_bus=None, log_manager=None)
        yield handler
        handler.clear()

    def test_initial_state(self, error_handler):
        """测试初始状态"""
        assert len(error_handler.get_records()) == 0
        assert error_handler.get_stats()["total"] == 0

    def test_handle_neurova_error(self, error_handler):
        """测试处理 NeurovaError"""
        error = NeurovaError(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Invalid input",
        )
        
        record = error_handler.handle(error, module="test_module")
        
        assert record.code == ErrorCode.INVALID_ARGUMENT
        assert record.message == "Invalid input"
        assert record.module == "test_module"
        assert len(error_handler.get_records()) == 1

    def test_handle_generic_exception(self, error_handler):
        """测试处理通用异常"""
        error = ValueError("Invalid value")
        
        record = error_handler.handle(error, module="test_module")
        
        assert record.code == ErrorCode.UNKNOWN_ERROR
        assert "Invalid value" in record.message
        assert record.module == "test_module"
        assert record.traceback is not None

    def test_handle_code(self, error_handler):
        """测试通过错误码处理错误"""
        record = error_handler.handle_code(
            code=ErrorCode.NOT_FOUND,
            message="Resource not found",
            module="api",
            details={"resource_id": "123"},
        )
        
        assert record.code == ErrorCode.NOT_FOUND
        assert record.message == "Resource not found"
        assert record.module == "api"
        assert record.details["resource_id"] == "123"

    def test_handle_with_details(self, error_handler):
        """测试处理错误时附加详细信息"""
        error = NeurovaError(code=ErrorCode.TIMEOUT)
        details = {"operation": "connect", "timeout": 30}
        
        record = error_handler.handle(error, module="network", details=details)
        
        assert record.details["operation"] == "connect"
        assert record.details["timeout"] == 30


class TestErrorHandlerRecovery:
    """测试 ErrorHandler 错误恢复功能"""

    @pytest.fixture
    def error_handler(self):
        """创建 ErrorHandler 实例"""
        handler = ErrorHandler(event_bus=None, log_manager=None)
        yield handler
        handler.clear()

    def test_register_and_trigger_recovery(self, error_handler):
        """测试注册和触发恢复策略"""
        recovery_called = []
        
        def recovery_strategy(record):
            recovery_called.append(record)
            return True
        
        error_handler.register_recovery(ErrorCode.TIMEOUT, recovery_strategy)
        
        error = NeurovaError(code=ErrorCode.TIMEOUT)
        record = error_handler.handle(error)
        
        assert len(recovery_called) == 1
        assert record.recovered is True

    def test_recovery_failure(self, error_handler):
        """测试恢复策略失败"""
        def failing_recovery(record):
            raise ValueError("Recovery failed")
        
        error_handler.register_recovery(ErrorCode.TIMEOUT, failing_recovery)
        
        error = NeurovaError(code=ErrorCode.TIMEOUT)
        record = error_handler.handle(error)
        
        # 恢复失败不应该影响错误处理
        assert record.recovered is False

    def test_recovery_returns_false(self, error_handler):
        """测试恢复策略返回 False"""
        def unsuccessful_recovery(record):
            return False
        
        error_handler.register_recovery(ErrorCode.TIMEOUT, unsuccessful_recovery)
        
        error = NeurovaError(code=ErrorCode.TIMEOUT)
        record = error_handler.handle(error)
        
        assert record.recovered is False


class TestErrorHandlerCallbacks:
    """测试 ErrorHandler 错误回调功能"""

    @pytest.fixture
    def error_handler(self):
        """创建 ErrorHandler 实例"""
        handler = ErrorHandler(event_bus=None, log_manager=None)
        yield handler
        handler.clear()

    def test_on_error_callback(self, error_handler):
        """测试注册错误回调"""
        callback_records = []
        
        def callback(record):
            callback_records.append(record)
        
        error_handler.on_error(callback)
        
        error = NeurovaError(code=ErrorCode.INVALID_ARGUMENT)
        error_handler.handle(error)
        
        assert len(callback_records) == 1
        assert callback_records[0].code == ErrorCode.INVALID_ARGUMENT

    def test_multiple_callbacks(self, error_handler):
        """测试多个回调"""
        callback1_records = []
        callback2_records = []
        
        def callback1(record):
            callback1_records.append(record)
        
        def callback2(record):
            callback2_records.append(record)
        
        error_handler.on_error(callback1)
        error_handler.on_error(callback2)
        
        error = NeurovaError(code=ErrorCode.NOT_FOUND)
        error_handler.handle(error)
        
        assert len(callback1_records) == 1
        assert len(callback2_records) == 1

    def test_callback_exception(self, error_handler):
        """测试回调异常不影响错误处理"""
        def failing_callback(record):
            raise ValueError("Callback failed")
        
        def success_callback(record):
            success_callback.called = True
        
        success_callback.called = False
        
        error_handler.on_error(failing_callback)
        error_handler.on_error(success_callback)
        
        error = NeurovaError(code=ErrorCode.UNKNOWN_ERROR)
        # 不应该抛出异常
        error_handler.handle(error)
        
        assert success_callback.called is True

    def test_remove_callback(self, error_handler):
        """测试移除回调"""
        callback_records = []
        
        def callback(record):
            callback_records.append(record)
        
        error_handler.on_error(callback)
        error_handler.remove_error_callback(callback)
        
        error = NeurovaError(code=ErrorCode.INVALID_ARGUMENT)
        error_handler.handle(error)
        
        # 回调应该被移除，不会收到错误
        assert len(callback_records) == 0


class TestErrorHandlerSafeExecute:
    """测试 ErrorHandler 安全执行功能"""

    @pytest.fixture
    def error_handler(self):
        """创建 ErrorHandler 实例"""
        handler = ErrorHandler(event_bus=None, log_manager=None)
        yield handler
        handler.clear()

    def test_safe_execute_success(self, error_handler):
        """测试成功执行"""
        def success_func(x, y):
            return x + y
        
        result = error_handler.safe_execute(success_func, 1, 2)
        
        assert result == 3

    def test_safe_execute_failure(self, error_handler):
        """测试执行失败"""
        def failing_func():
            raise ValueError("Function failed")
        
        result = error_handler.safe_execute(failing_func)
        
        assert result is None
        assert len(error_handler.get_records()) == 1

    def test_safe_execute_with_fallback(self, error_handler):
        """测试带回退的执行"""
        def failing_func():
            raise ValueError("Function failed")
        
        def fallback(record):
            return "fallback_result"
        
        result = error_handler.safe_execute(
            failing_func,
            fallback=fallback,
        )
        
        assert result == "fallback_result"

    def test_safe_execute_with_module(self, error_handler):
        """测试带模块名称的安全执行"""
        def failing_func():
            raise ValueError("Error")
        
        error_handler.safe_execute(failing_func, module="test_module")
        
        records = error_handler.get_records()
        assert len(records) == 1
        assert records[0].module == "test_module"


class TestErrorHandlerQuery:
    """测试 ErrorHandler 查询功能"""

    @pytest.fixture
    def error_handler(self):
        """创建 ErrorHandler 实例并添加测试数据"""
        handler = ErrorHandler(event_bus=None, log_manager=None)
        
        # 添加一些测试错误记录
        handler.handle_code(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Error 1",
            module="module_a",
        )
        handler.handle_code(
            code=ErrorCode.NOT_FOUND,
            message="Error 2",
            module="module_b",
        )
        handler.handle_code(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Error 3",
            module="module_a",
        )
        handler.handle_code(
            code=ErrorCode.TIMEOUT,
            message="Error 4",
            module="module_c",
        )
        
        yield handler
        handler.clear()

    def test_get_records_all(self, error_handler):
        """测试获取所有记录"""
        records = error_handler.get_records()
        assert len(records) == 4

    def test_get_records_by_module(self, error_handler):
        """测试按模块过滤记录"""
        records = error_handler.get_records(module="module_a")
        assert len(records) == 2
        assert all(r.module == "module_a" for r in records)

    def test_get_records_by_code(self, error_handler):
        """测试按错误码过滤记录"""
        records = error_handler.get_records(code=ErrorCode.INVALID_ARGUMENT)
        assert len(records) == 2
        assert all(r.code == ErrorCode.INVALID_ARGUMENT for r in records)

    def test_get_records_with_limit(self, error_handler):
        """测试限制返回数量"""
        records = error_handler.get_records(limit=2)
        assert len(records) == 2

    def test_get_stats(self, error_handler):
        """测试获取统计信息"""
        stats = error_handler.get_stats()
        
        assert stats["total"] == 4
        assert stats["by_code"]["INVALID_ARGUMENT"] == 2
        assert stats["by_code"]["NOT_FOUND"] == 1
        assert stats["by_code"]["TIMEOUT"] == 1

    def test_clear(self, error_handler):
        """测试清空记录"""
        assert len(error_handler.get_records()) == 4
        
        error_handler.clear()
        
        assert len(error_handler.get_records()) == 0
        assert error_handler.get_stats()["total"] == 0


class TestErrorHandlerReport:
    """测试 ErrorHandler 报告生成功能"""

    @pytest.fixture
    def error_handler(self):
        """创建 ErrorHandler 实例并添加测试数据"""
        handler = ErrorHandler(event_bus=None, log_manager=None)
        
        handler.handle_code(
            code=ErrorCode.INVALID_ARGUMENT,
            message="Test error 1",
            module="test_module",
        )
        handler.handle_code(
            code=ErrorCode.TIMEOUT,
            message="Test error 2",
            module="test_module",
        )
        
        yield handler
        handler.clear()

    def test_generate_report(self, error_handler):
        """测试生成错误报告"""
        report = error_handler.generate_report()
        
        assert "错误报告" in report
        assert "总错误数: 2" in report
        assert "INVALID_ARGUMENT" in report
        assert "TIMEOUT" in report
        assert "Test error 1" in report
        assert "Test error 2" in report


class TestGlobalErrorHandler:
    """测试全局 ErrorHandler 函数"""

    def teardown_method(self):
        """每个测试后重置全局处理器"""
        reset_error_handler()

    def test_get_error_handler_singleton(self):
        """测试全局处理器单例"""
        handler1 = get_error_handler()
        handler2 = get_error_handler()
        assert handler1 is handler2

    def test_get_error_handler_type(self):
        """测试全局处理器类型"""
        handler = get_error_handler()
        assert isinstance(handler, ErrorHandler)

    def test_reset_error_handler(self):
        """测试重置全局处理器"""
        handler1 = get_error_handler()
        reset_error_handler()
        handler2 = get_error_handler()
        assert handler1 is not handler2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
