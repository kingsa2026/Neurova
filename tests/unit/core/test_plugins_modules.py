"""
测试 plugins 模块（对齐 neurova/plugins/plugin_manager.py 真实契约）
实现直接查 _plugins 字典，不经过 get_plugin/list_plugins 包装。
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from neurova.plugins.plugin_manager import (
    PluginRecord,
    PluginManager,
    get_plugin_manager,
    reset_plugin_manager,
)


def _make_manager(tmp_path):
    """创建隔离插件目录的管理器"""
    return PluginManager(plugin_dir=str(tmp_path / "plugins"))


def _record(name="test-plugin", **kwargs):
    return PluginRecord(name=name, **kwargs)


class TestPluginRecord:
    """测试 PluginRecord 数据类"""

    def test_plugin_record_creation(self):
        """测试 PluginRecord 创建"""
        record = PluginRecord(
            name="test-plugin",
            version="1.0.0",
            description="A test plugin",
            author="test",
            enabled=True,
        )

        assert record.name == "test-plugin"
        assert record.version == "1.0.0"
        assert record.description == "A test plugin"
        assert record.author == "test"
        assert record.enabled is True

    def test_plugin_record_to_dict(self):
        """测试 PluginRecord 转字典"""
        record = PluginRecord(name="test-plugin", version="1.0.0", description="A test plugin")

        data = record.to_dict()
        assert isinstance(data, dict)
        assert data["name"] == "test-plugin"
        assert data["version"] == "1.0.0"

    def test_plugin_record_from_dict(self):
        """测试从字典创建 PluginRecord"""
        data = {"name": "test-plugin", "version": "1.0.0", "description": "A test plugin"}

        record = PluginRecord.from_dict(data)
        assert record.name == "test-plugin"
        assert record.version == "1.0.0"


class TestPluginManager:
    """测试 PluginManager 类"""

    def test_manager_initialization(self, tmp_path):
        """测试 PluginManager 初始化"""
        manager = _make_manager(tmp_path)

        assert manager is not None
        assert hasattr(manager, "discover_plugins")
        assert hasattr(manager, "install_plugin")
        assert hasattr(manager, "load_plugin")

    def test_set_plugin_dir(self, tmp_path):
        """测试设置插件目录"""
        manager = _make_manager(tmp_path)
        test_dir = str(tmp_path / "new_plugins")

        manager.set_plugin_dir(test_dir)
        assert manager.plugin_dir == test_dir
        assert Path(test_dir).exists()

    def test_discover_plugins(self, tmp_path):
        """测试发现插件（空目录返回空列表）"""
        manager = _make_manager(tmp_path)

        plugins = manager.discover_plugins()
        assert isinstance(plugins, list)

    def test_install_plugin(self, tmp_path):
        """测试安装插件（真实目录 + mock manifest）"""
        manager = _make_manager(tmp_path)

        plugin_path = tmp_path / "test-plugin"
        plugin_path.mkdir(parents=True)

        with patch.object(manager, "_load_manifest", return_value={"name": "test-plugin"}):
            result = manager.install_plugin(str(plugin_path))

        assert result is True
        assert "test-plugin" in manager._plugins

    def test_install_plugin_nonexistent_path(self, tmp_path):
        """安装不存在的路径失败"""
        manager = _make_manager(tmp_path)

        assert manager.install_plugin(str(tmp_path / "ghost")) is False

    def test_uninstall_plugin(self, tmp_path):
        """测试卸载插件"""
        manager = _make_manager(tmp_path)

        plugin_path = tmp_path / "test-plugin"
        plugin_path.mkdir(parents=True)

        with patch.object(manager, "_load_manifest", return_value={"name": "test-plugin"}):
            manager.install_plugin(str(plugin_path))

        result = manager.uninstall_plugin("test-plugin")
        assert result is True
        assert "test-plugin" not in manager._plugins

    def test_load_plugin(self, tmp_path):
        """测试加载插件（mock 模块含可实例化插件类）"""
        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(enabled=True)

        mock_module = MagicMock()
        plugin_class = type("FakePlugin", (), {"__init__": lambda self: None, "on_enable": lambda self: None})
        mock_module.FakePlugin = plugin_class

        with patch.object(manager, "_load_plugin_module", return_value=mock_module):
            result = manager.load_plugin("test-plugin")

        assert result is True
        assert manager._plugins["test-plugin"].loaded is True
        assert "test-plugin" in manager._modules

    def test_load_plugin_not_enabled(self, tmp_path):
        """未启用插件加载失败"""
        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(enabled=False)

        assert manager.load_plugin("test-plugin") is False

    def test_unload_plugin(self, tmp_path):
        """测试卸载插件模块"""
        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(loaded=True)

        result = manager.unload_plugin("test-plugin")

        assert result is True
        assert manager._plugins["test-plugin"].loaded is False

    def test_unload_plugin_not_loaded(self, tmp_path):
        """未加载时 unload 幂等成功"""
        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(loaded=False)

        assert manager.unload_plugin("test-plugin") is True

    def test_enable_plugin(self, tmp_path):
        """测试启用插件"""
        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(enabled=False)

        result = manager.enable_plugin("test-plugin")

        assert result is True
        assert manager._plugins["test-plugin"].enabled is True

    def test_disable_plugin(self, tmp_path):
        """测试禁用插件"""
        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(enabled=True)

        result = manager.disable_plugin("test-plugin")

        assert result is True
        assert manager._plugins["test-plugin"].enabled is False

    def test_check_dependencies(self, tmp_path):
        """测试检查依赖（依赖已启用→True；缺失→False）"""
        manager = _make_manager(tmp_path)
        manager._plugins["dep1"] = _record(name="dep1", enabled=True)
        manager._plugins["dep2"] = _record(name="dep2", enabled=True)
        manager._plugins["test-plugin"] = _record(name="test-plugin", dependencies=["dep1", "dep2"])

        assert manager._check_dependencies(manager._plugins["test-plugin"]) is True

        manager._plugins["dep2"].enabled = False
        assert manager._check_dependencies(manager._plugins["test-plugin"]) is False

    def test_resolve_load_order(self, tmp_path):
        """测试解析加载顺序（拓扑排序）"""
        manager = _make_manager(tmp_path)
        manager._plugins["plugin1"] = _record(name="plugin1", dependencies=[])
        manager._plugins["plugin2"] = _record(name="plugin2", dependencies=["plugin1"])

        order = manager.resolve_load_order()

        assert isinstance(order, list)
        assert len(order) == 2
        assert order[0] == "plugin1"
        assert order[1] == "plugin2"

    def test_load_all(self, tmp_path):
        """测试加载所有插件（只加载已启用未加载的）"""
        manager = _make_manager(tmp_path)
        manager._plugins["plugin1"] = _record(name="plugin1", enabled=True)
        manager._plugins["plugin2"] = _record(name="plugin2", enabled=True)
        manager._plugins["plugin3"] = _record(name="plugin3", enabled=False)

        def _fake_module(record):
            mock_module = MagicMock()
            plugin_class = type("FakePlugin", (), {"__init__": lambda self: None, "on_enable": lambda self: None})
            mock_module.FakePlugin = plugin_class
            return mock_module

        with patch.object(manager, "_load_plugin_module", side_effect=_fake_module):
            result = manager.load_all()

        assert result == 2

    def test_get_plugin(self, tmp_path):
        """测试获取插件"""
        manager = _make_manager(tmp_path)
        record = _record()
        manager._plugins["test-plugin"] = record

        assert manager.get_plugin("test-plugin") is record
        assert manager.get_plugin("nonexistent") is None

    def test_list_plugins(self, tmp_path):
        """测试列出插件"""
        manager = _make_manager(tmp_path)
        manager._plugins = {"plugin1": _record(name="plugin1"), "plugin2": _record(name="plugin2")}

        plugins = manager.list_plugins()
        assert isinstance(plugins, list)
        assert len(plugins) == 2

    def test_has_plugin(self, tmp_path):
        """测试检查插件是否存在"""
        manager = _make_manager(tmp_path)
        manager._plugins = {"test-plugin": _record()}

        assert manager.has_plugin("test-plugin") is True
        assert manager.has_plugin("nonexistent") is False

    def test_get_enabled_plugins(self, tmp_path):
        """测试获取已启用的插件"""
        manager = _make_manager(tmp_path)
        manager._plugins = {
            "plugin1": _record(name="plugin1", enabled=True),
            "plugin2": _record(name="plugin2", enabled=False),
        }

        enabled = manager.get_enabled_plugins()
        assert len(enabled) == 1
        assert enabled[0].name == "plugin1"

    def test_get_status(self, tmp_path):
        """测试获取插件状态（按插件名分组的字典）"""
        manager = _make_manager(tmp_path)
        manager._plugins = {"test-plugin": _record(enabled=True, loaded=True)}

        status = manager.get_status()
        assert isinstance(status, dict)
        assert "test-plugin" in status
        assert status["test-plugin"]["enabled"] is True
        assert status["test-plugin"]["loaded"] is True


class TestLifecycleEvent:
    """测试 LifecycleEvent 枚举"""

    def test_lifecycle_events(self):
        """测试生命周期事件枚举"""
        from neurova.plugins.plugin_lifecycle import LifecycleEvent

        assert LifecycleEvent.BEFORE_INSTALL.value == "before_install"
        assert LifecycleEvent.AFTER_INSTALL.value == "after_install"
        assert LifecycleEvent.BEFORE_ENABLE.value == "before_enable"
        assert LifecycleEvent.AFTER_ENABLE.value == "after_enable"
        assert LifecycleEvent.BEFORE_DISABLE.value == "before_disable"
        assert LifecycleEvent.AFTER_DISABLE.value == "after_disable"
        assert LifecycleEvent.BEFORE_UNINSTALL.value == "before_uninstall"
        assert LifecycleEvent.AFTER_UNINSTALL.value == "after_uninstall"


class TestLifecycleHook:
    """测试 LifecycleHook 数据类"""

    def test_lifecycle_hook_creation(self):
        """测试 LifecycleHook 创建"""
        from neurova.plugins.plugin_lifecycle import LifecycleHook, LifecycleEvent

        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin",
        )

        assert hook.event == LifecycleEvent.BEFORE_INSTALL
        assert hook.priority == 10
        assert hook.plugin_name == "test-plugin"

    def test_lifecycle_hook_to_dict(self):
        """测试 LifecycleHook 转字典"""
        from neurova.plugins.plugin_lifecycle import LifecycleHook, LifecycleEvent

        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin",
        )

        data = hook.to_dict()
        assert isinstance(data, dict)
        assert data["event"] == "before_install"
        assert data["priority"] == 10


class TestPluginLifecycleManager:
    """测试 PluginLifecycleManager 类"""

    def test_manager_initialization(self):
        """测试 PluginLifecycleManager 初始化"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager

        manager = PluginLifecycleManager()
        assert manager is not None
        assert hasattr(manager, "register_hook")
        assert hasattr(manager, "execute_lifecycle")

    def test_register_hook(self):
        """测试注册钩子"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager, LifecycleEvent, LifecycleHook

        manager = PluginLifecycleManager()

        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin",
        )

        manager.register_hook(hook)

        hooks = manager._collect_hooks(LifecycleEvent.BEFORE_INSTALL, "test-plugin")
        assert len(hooks) == 1

    def test_unregister_hooks(self):
        """测试注销钩子"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager, LifecycleEvent, LifecycleHook

        manager = PluginLifecycleManager()

        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=lambda: None,
            priority=10,
            plugin_name="test-plugin",
        )

        manager.register_hook(hook)
        manager.unregister_hooks("test-plugin")

        hooks = manager._collect_hooks(LifecycleEvent.BEFORE_INSTALL, "test-plugin")
        assert len(hooks) == 0

    def test_execute_lifecycle(self):
        """测试执行生命周期"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager, LifecycleEvent, LifecycleHook

        manager = PluginLifecycleManager()

        callback_called = False

        def test_callback():
            nonlocal callback_called
            callback_called = True

        hook = LifecycleHook(
            event=LifecycleEvent.BEFORE_INSTALL,
            callback=test_callback,
            priority=10,
            plugin_name="test-plugin",
        )

        manager.register_hook(hook)
        manager.execute_lifecycle(LifecycleEvent.BEFORE_INSTALL, "test-plugin")

        assert callback_called is True

    def test_set_plugin_state(self):
        """测试设置插件状态"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager

        manager = PluginLifecycleManager()

        manager.set_plugin_state("test-plugin", "installed")

        assert manager.get_plugin_state("test-plugin") == "installed"

    def test_get_all_states(self):
        """测试获取所有状态"""
        from neurova.plugins.plugin_lifecycle import PluginLifecycleManager

        manager = PluginLifecycleManager()

        manager.set_plugin_state("plugin1", "installed")
        manager.set_plugin_state("plugin2", "enabled")

        states = manager.get_all_states()
        assert isinstance(states, dict)
        assert states["plugin1"] == "installed"
        assert states["plugin2"] == "enabled"


class TestGetPluginManager:
    """测试 get_plugin_manager 函数"""

    def test_get_plugin_manager(self):
        """测试获取全局插件管理器"""
        reset_plugin_manager()

        manager1 = get_plugin_manager()
        manager2 = get_plugin_manager()

        assert manager1 is manager2
        assert isinstance(manager1, PluginManager)

    def test_reset_plugin_manager(self):
        """测试重置全局插件管理器"""
        manager1 = get_plugin_manager()

        reset_plugin_manager()

        manager2 = get_plugin_manager()

        assert manager1 is not manager2
