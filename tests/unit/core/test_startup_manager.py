"""StartupManager 单元测试（对齐真实实现）。

真实 API（neurova/core/startup_manager.py + neurova/core/module_system.py）：
    StartupManager(config: Optional[StartupConfig] = None)
    config / registry / is_started / uptime 属性
    register_module(name, module_class, dependencies=None, **kwargs)
    register_module_class(module_class, name=None, dependencies=None)
    register_shutdown_hook(hook)
    start() -> StartupResult        # 注意是 start，不是 startup
    stop()                          # 注意是 stop，不是 shutdown
    get_status() -> {"started","uptime","modules","total_modules"}
    get_module_instance(name) -> Optional[Module]

Module 基类子类需实现 _on_init/_on_start/_on_stop。
旧测试引用的 _modules / load_config / set_config / startup / shutdown /
get_module / get_module_config / health_check / restart_module / unregister_module
在真实实现中不存在，相应测试移除。
"""

import pytest

from neurova.core.module_system import Module, ModuleState
from neurova.core.startup_manager import StartupConfig, StartupManager


class _DummyModule(Module):
    def __init__(self, config=None, event_bus=None, **kwargs):
        super().__init__(config=config, event_bus=event_bus, **kwargs)
        self.init_called = False
        self.start_called = False
        self.stop_called = False

    def _on_init(self) -> None:
        self.init_called = True

    def _on_start(self) -> None:
        self.start_called = True

    def _on_stop(self) -> None:
        self.stop_called = True


@pytest.fixture
def manager():
    return StartupManager()


class TestConstruction:
    def test_default_config(self, manager):
        assert isinstance(manager.config, StartupConfig)
        assert manager.is_started is False
        assert manager.uptime == 0.0

    def test_custom_config(self):
        cfg = StartupConfig(startup_timeout=5.0, data_dir="custom")
        mgr = StartupManager(config=cfg)
        assert mgr.config.startup_timeout == 5.0
        assert mgr.config.data_dir == "custom"


class TestRegistration:
    def test_register_module(self, manager):
        manager.register_module("dummy", _DummyModule)
        assert "dummy" in manager.registry.resolver.get_all_modules()

    def test_register_module_class_uses_class_name(self, manager):
        manager.register_module_class(_DummyModule)
        assert "_DummyModule" in manager.registry.resolver.get_all_modules()

    def test_register_module_with_dependencies(self, manager):
        manager.register_module("dummy", _DummyModule, dependencies=[])
        assert "dummy" in manager.registry.resolver.get_all_modules()


class TestLifecycle:
    def test_start_starts_modules(self, manager):
        manager.register_module("dummy", _DummyModule)
        result = manager.start()
        assert result.success is True
        assert manager.is_started is True
        assert "dummy" in result.modules_started

    def test_double_start_is_noop_success(self, manager):
        manager.register_module("dummy", _DummyModule)
        manager.start()
        result = manager.start()
        assert result.success is True

    def test_stop_stops_system(self, manager):
        manager.register_module("dummy", _DummyModule)
        manager.start()
        manager.stop()
        assert manager.is_started is False

    def test_shutdown_hook_runs_on_stop(self, manager):
        calls = []
        manager.register_shutdown_hook(lambda: calls.append(1))
        manager.register_module("dummy", _DummyModule)
        manager.start()
        manager.stop()
        assert calls == [1]


class TestStatus:
    def test_get_status_shape(self, manager):
        manager.register_module("dummy", _DummyModule)
        manager.start()
        status = manager.get_status()
        assert status["started"] is True
        assert status["total_modules"] == 1
        assert "dummy" in status["modules"]
        assert "uptime" in status

    def test_get_status_module_state_running(self, manager):
        manager.register_module("dummy", _DummyModule)
        manager.start()
        status = manager.get_status()
        assert status["modules"]["dummy"]["state"] == ModuleState.RUNNING.value

    def test_get_module_instance(self, manager):
        manager.register_module("dummy", _DummyModule)
        manager.start()
        instance = manager.get_module_instance("dummy")
        assert instance is not None
        assert instance.start_called is True
