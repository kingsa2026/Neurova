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

    def test_emit_event_falls_back_to_global_bus(self):
        """未注入总线时，事件必须落到唯一全局入口（不是"静默不发"）。

        改判说明：本条原名 `test_emit_event_no_bus`，只调一次 `emit_event` 不断言任何
        事——而"没有总线就不发"正是 §6-12 缺陷① 的形态（全仓无一处注入非 None，广播
        承诺恒不执行）。现按行为判据钉：默认构造发出的事，全局总线的订阅者必须收到。
        """
        from neurova.core.event_bus import EventBus, reset_event_bus

        reset_event_bus()
        try:
            bus = EventBus()
            received = []
            bus.subscribe("test_event", lambda event: received.append(event))
            # 用注入替换掉"默认取全局"这一步的可测性代价：默认路径由
            # tests/unit/core/test_eventBusWiringFromBaseModule.py 专项钉，本条只钉
            # 载荷形状（module_id 必带）。
            module = self.ConcreteModule(event_bus=bus)
            module.emit_event("test_event", {"key": "value"})
            assert len(received) == 1, "emit_event 未落到总线"
            assert received[0].data["key"] == "value"
            assert "module_id" in received[0].data
        finally:
            reset_event_bus()

    def test_emit_event_with_bus(self):
        """注入真总线时必须走注入那一份——原形态用 `MagicMock` 冒充总线并断言
        `bus.emit`，而 `core/event_bus.py` 只有 `publish`(:168)，**没有 emit**：
        生产与测试同时错，所以它一直绿（教义第 3 条明禁的假契约）。
        """
        from neurova.core.event_bus import EventBus

        bus = EventBus()
        received = []
        bus.subscribe("test_event", lambda event: received.append(event))
        module = self.ConcreteModule(event_bus=bus)

        module.emit_event("test_event", {"key": "value"})

        assert len(received) == 1, "注入的总线上没收到事件"
        assert received[0].data == {"module_id": module.MODULE_ID, "key": "value"}
