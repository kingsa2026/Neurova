"""
测试 plugins 模块（对齐 neurova/plugins/plugin_manager.py 真实契约）
实现直接查 _plugins 字典，不经过 get_plugin/list_plugins 包装。
"""

import sys

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


_PLUGIN_SOURCE_LINES = [
    "class {className}:",
    "    def on_initialize(self):",
    "        self.started = False",
    "    def on_enable(self):",
    "        self.started = True",
]


def _writePluginInto(root: Path, name: str) -> Path:
    """在**插件根内**造一个真插件目录（manifest + 入口文件），返回该目录。

    刻意不用替身：这批格子原先把 `_load_manifest` / `_load_plugin_module` 整个 mock 掉，
    于是"安装/加载成功"从不要求真文件、真 import——84 例全绿的同时，真实 `load_plugin`
    对任何按作者基类写的插件都必抛 TypeError（无参构造 vs 要求 manifest）。
    幽灵替身形态见台账 §6-150。
    """
    import json

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "description": "d", "author": "qa",
                    "entry_point": "main.py", "dependencies": []}),
        encoding="utf-8",
    )
    className = "".join(word.capitalize() for word in name.replace("-", " ").split())
    (directory / "main.py").write_text(
        "\n".join(line.format(className=className) for line in _PLUGIN_SOURCE_LINES) + "\n",
        encoding="utf-8",
    )
    return directory


def _writePluginInto(root: Path, name: str) -> Path:
    """在**插件根内**造一个真插件目录（manifest + 入口文件），返回该目录。

    刻意不用替身：这批格子原先把 `_load_manifest` / `_load_plugin_module` 整个 mock 掉，
    于是"安装/加载成功"从不要求真文件、真 import——84 例全绿的同时，真实 `load_plugin`
    对任何按作者基类写的插件都必抛 TypeError（无参构造 vs 要求 manifest）。
    幽灵替身形态见台账 §6-150。
    """
    import json

    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(
        json.dumps({"name": name, "version": "1.0.0", "description": "d", "author": "qa",
                    "entry_point": "main.py", "dependencies": []}),
        encoding="utf-8",
    )
    className = "".join(word.capitalize() for word in name.replace("-", " ").split())
    (directory / "main.py").write_text(
        "class {}:\n"
        "    def on_initialize(self):\n"
        "        self.started = False\n"
        "    def on_enable(self):\n"
        "        self.started = True\n".format(className),
        encoding="utf-8",
    )
    return directory


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

    def test_installPluginRegistersTheRecordFromItsOwnManifest(self, tmp_path):
        """安装返回记录本身；插件名来自 manifest，不来自调用方给的路径名。"""
        manager = _make_manager(tmp_path)
        plugin_path = _writePluginInto(Path(manager.plugin_dir), "test-plugin")

        record = manager.install_plugin(str(plugin_path))

        assert record.name == "test-plugin"
        assert "test-plugin" in manager._plugins
        assert manager.manifestDict("test-plugin").get("version") == "1.0.0", (
            "清单没留在 manager 里——load 时无从构造 PluginManifest")

    def test_installRejectsSourcesThatAreNotInsideTheRoot(self, tmp_path):
        """装载边界（P1 的授权面）：根外的源必须被拒，且**点名成因**。

        旧格断的是 `install_plugin("...ghost") is False`——把"路径不存在""越界""缺 manifest"
        折成同一个 False；端点那侧就只能把所有 False 画成同一句失败（§6-126 那一族）。
        新契约下成因是结构化字段 `reason`。
        """
        from neurova.plugins.plugin_manager import PluginError

        manager = _make_manager(tmp_path)

        with pytest.raises(PluginError) as ghost:
            manager.install_plugin(str(tmp_path / "ghost"))
        assert ghost.value.reason == "not_a_directory", ghost.value.reason

        outside = tmp_path / "somewhere_else"
        _writePluginInto(outside, "evil")
        with pytest.raises(PluginError) as escaped:
            manager.install_plugin(str(outside / "evil"))
        assert escaped.value.reason == "outside_root", escaped.value.reason

    def test_uninstall_plugin(self, tmp_path):
        """卸载清记录，也清掉清单缓存（否则"重装"会读到旧声明）。"""
        manager = _make_manager(tmp_path)
        plugin_path = _writePluginInto(Path(manager.plugin_dir), "test-plugin")
        manager.install_plugin(str(plugin_path))

        assert manager.uninstall_plugin("test-plugin") is True
        assert "test-plugin" not in manager._plugins
        assert manager.manifestDict("test-plugin") == {}, "清单缓存残留"

    def test_loadPluginInstantiatesTheRealClass(self, tmp_path):
        """真装载：import 并 exec 根内的入口文件，返回实例。

        旧格把 `_load_plugin_module` 换成 MagicMock 再断 `is True`——那证不了任何
        import/exec 发生过（幽灵替身，§6-150）。这里用真目录真文件。
        """
        manager = _make_manager(tmp_path)
        plugin_path = _writePluginInto(Path(manager.plugin_dir), "test-plugin")
        manager.install_plugin(str(plugin_path))
        manager.enable_plugin("test-plugin")

        instance = manager.load_plugin("test-plugin")

        assert type(instance).__name__ == "TestPlugin", instance
        assert manager.get_plugin("test-plugin").loaded is True
        assert manager.moduleInfo("test-plugin") is not None

    def test_load_before_enable_is_refused_with_reason(self, tmp_path):
        """未启用就装载：报成因，不再回一个无从分辨的 False。"""
        from neurova.plugins.plugin_manager import PluginError

        manager = _make_manager(tmp_path)
        manager._plugins["test-plugin"] = _record(enabled=False)

        with pytest.raises(PluginError) as raised:
            manager.load_plugin("test-plugin")
        assert raised.value.reason == "not_enabled"

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

    def test_load_all_countsOnlyRealLoads(self, tmp_path):
        """批量装载：只装已启用未加载的，而且**真装**。

        旧格用 `patch.object(manager, "_load_plugin_module", side_effect=_fake_module)`
        造出一个"永远成功的假模块"来断 `load_all() == 2`——那 2 是替身给的，不是插件被装载了。
        """
        manager = _make_manager(tmp_path)
        for name in ("plugin1", "plugin2", "plugin3"):
            manager.install_plugin(str(_writePluginInto(Path(manager.plugin_dir), name)))
        manager.enable_plugin("plugin1")
        manager.enable_plugin("plugin2")

        assert manager.load_all() == 2
        assert manager.get_plugin("plugin3").loaded is False, "未启用的被装了"

    def test_unload_dropsTheModuleFromTheProcess(self, tmp_path):
        """卸载要真把 `sys.modules` 里那条摘掉——否则旧代码与旧实例还活在进程里。"""
        manager = _make_manager(tmp_path)
        manager.install_plugin(str(_writePluginInto(Path(manager.plugin_dir), "leaky")))
        manager.enable_plugin("leaky")
        manager.load_plugin("leaky")

        assert "neurova_plugin_leaky" in sys.modules
        manager.unload_plugin("leaky")
        assert "neurova_plugin_leaky" not in sys.modules

    def test_basePluginSubclassIsBuiltWithItsManifest(self, tmp_path):
        """作者基类要 manifest：无参构造那条路必须已经修掉（§6-150 的实测 defect）。"""
        manager = _make_manager(tmp_path)
        directory = _writePluginInto(Path(manager.plugin_dir), "author")
        (directory / "main.py").write_text(
            "from neurova.plugins.base_plugin import BasePlugin\n"
            "class AuthorPlugin(BasePlugin):\n"
            "    def on_initialize(self):\n        pass\n"
            "    def on_start(self):\n        pass\n"
            "    def on_stop(self):\n        pass\n"
            "    def on_destroy(self):\n        pass\n",
            encoding="utf-8",
        )
        manager.install_plugin(str(directory))
        manager.enable_plugin("author")

        instance = manager.load_plugin("author")

        assert instance.manifest.plugin_id == "author", instance.manifest

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
