"""
测试基础模块
"""
import pytest
from neurova.core.base_module import (
    ModuleState,
    BaseModule,
)


class TestModuleState:
    """测试ModuleState枚举"""

    def test_module_state_members(self):
        """测试模块状态枚举成员"""
        assert ModuleState.UNINITIALIZED.value == "uninitialized"
        assert ModuleState.INITIALIZING.value == "initializing"
        assert ModuleState.INITIALIZED.value == "initialized"
        assert ModuleState.STARTING.value == "starting"
        assert ModuleState.RUNNING.value == "running"
        assert ModuleState.STOPPING.value == "stopping"
        assert ModuleState.STOPPED.value == "stopped"
        assert ModuleState.ERROR.value == "error"


class TestBaseModule:
    """测试BaseModule抽象基类"""

    class ConcreteModule(BaseModule):
        """用于测试的具体模块实现"""

        def on_initialize(self):
            pass

        def on_start(self):
            pass

        def on_stop(self):
            pass

    def test_init_defaults(self):
        """测试默认初始化"""
        module = self.ConcreteModule()
        assert module.MODULE_ID == "base_module"
        assert module.get_state() == ModuleState.UNINITIALIZED

    def test_init_with_params(self):
        """测试参数初始化"""
        module = self.ConcreteModule(
            module_id="test_module",
            name="Test Module",
            version="1.0.0",
        )
        assert module.MODULE_ID == "test_module"
        assert module.MODULE_NAME == "Test Module"
        assert module.MODULE_VERSION == "1.0.0"
        assert module.get_state() == ModuleState.UNINITIALIZED

    def test_init_with_config(self):
        """测试配置初始化"""
        module = self.ConcreteModule(config={"key": "value"})
        assert module._config == {"key": "value"}

    def test_set_state(self):
        """测试设置状态"""
        module = self.ConcreteModule()
        module.set_state(ModuleState.INITIALIZED)
        assert module.get_state() == ModuleState.INITIALIZED

    def test_set_state_value(self):
        """测试设置状态值"""
        module = self.ConcreteModule()
        module.set_state_value("key1", "value1")
        assert module.get_state_value("key1") == "value1"
        assert module.get_state_value("key2", "default") == "default"

    def test_initialize(self):
        """测试初始化"""
        module = self.ConcreteModule()
        module.initialize()
        assert module.get_state() == ModuleState.INITIALIZED

    def test_initialize_already_initialized(self):
        """测试重复初始化"""
        module = self.ConcreteModule()
        module.initialize()
        module.initialize()
        assert module.get_state() == ModuleState.INITIALIZED

    def test_start(self):
        """测试启动"""
        module = self.ConcreteModule()
        module.initialize()
        module.start()
        assert module.get_state() == ModuleState.RUNNING

    def test_start_not_initialized(self):
        """测试未初始化时启动"""
        module = self.ConcreteModule()
        module.start()
        assert module.get_state() == ModuleState.UNINITIALIZED

    def test_stop(self):
        """测试停止"""
        module = self.ConcreteModule()
        module.initialize()
        module.start()
        module.stop()
        assert module.get_state() == ModuleState.STOPPED

    def test_stop_not_running(self):
        """测试未运行时停止"""
        module = self.ConcreteModule()
        module.stop()
        assert module.get_state() == ModuleState.UNINITIALIZED

    def test_initialize_error(self):
        """测试初始化错误"""
        class ErrorModule(BaseModule):
            def on_initialize(self):
                raise ValueError("Init failed")
            def on_start(self):
                pass
            def on_stop(self):
                pass

        module = ErrorModule()
        with pytest.raises(ValueError, match="Init failed"):
            module.initialize()
        assert module.get_state() == ModuleState.ERROR

    def test_start_error(self):
        """测试启动错误"""
        class ErrorModule(BaseModule):
            def on_initialize(self):
                pass
            def on_start(self):
                raise ValueError("Start failed")
            def on_stop(self):
                pass

        module = ErrorModule()
        module.initialize()
        with pytest.raises(ValueError, match="Start failed"):
            module.start()
        assert module.get_state() == ModuleState.ERROR

    def test_stop_error(self):
        """测试停止错误"""
        class ErrorModule(BaseModule):
            def on_initialize(self):
                pass
            def on_start(self):
                pass
            def on_stop(self):
                raise ValueError("Stop failed")

        module = ErrorModule()
        module.initialize()
        module.start()
        with pytest.raises(ValueError, match="Stop failed"):
            module.stop()
        assert module.get_state() == ModuleState.ERROR

    def test_log_info(self):
        """测试记录信息日志"""
        module = self.ConcreteModule()
        module.log_info("test info")

    def test_log_debug(self):
        """测试记录调试日志"""
        module = self.ConcreteModule()
        module.log_debug("test debug")

    def test_log_warning(self):
        """测试记录警告日志"""
        module = self.ConcreteModule()
        module.log_warning("test warning")

    def test_log_error(self):
        """测试记录错误日志"""
        module = self.ConcreteModule()
        module.log_error("test error")

    def test_emit_event_no_bus(self):
        """测试无事件总线时发送事件"""
        module = self.ConcreteModule()
        module.emit_event("test_event", {"key": "value"})

    def test_emit_event_with_bus(self):
        """测试有事件总线时发送事件"""
        from unittest.mock import MagicMock
        bus = MagicMock()
        module = self.ConcreteModule(event_bus=bus)
        module.emit_event("test_event", {"key": "value"})
        bus.emit.assert_called_once()
