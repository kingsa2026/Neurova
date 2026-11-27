"""P2-20：插件启停/重装/停机必须以实例、注册表和活路由为准。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI

from neurova.plugins import plugin_manager as manager_module
from neurova.plugins import plugin_permissions, plugin_route_mount
from neurova.plugins.plugin_errors import PluginError
from neurova.plugins.plugin_manager import PluginManager
from neurova.plugins.plugin_permissions import PluginPermissionStore


_SOURCE = '''
import os
from neurova.plugins.base_plugin import BasePlugin

def _mark(value):
    with open(os.environ["PLUGIN_LIFECYCLE_LOG"], "a", encoding="utf-8") as fh:
        fh.write(value + "\\n")

class ProbePlugin(BasePlugin):
    async def on_initialize(self):
        _mark("initialize")
    async def on_start(self):
        _mark("start")
    async def on_stop(self):
        _mark("stop")
        if os.environ.get("PLUGIN_FAIL_STOP") == "1":
            raise RuntimeError("stop failed")
    async def on_destroy(self):
        _mark("destroy")
    def status(self):
        return {"plugin": self.plugin_id}
'''


def _write_plugin(root: Path, name: str) -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "manifest.json").write_text(json.dumps({
        "name": name,
        "version": "1.0.0",
        "entry_point": "main.py",
        "permissions": {},
        "framework_surfaces": [],
        "api_endpoints": [{"method": "GET", "path": "status", "handler_name": "status"}],
    }), encoding="utf-8")
    (directory / "main.py").write_text(_SOURCE, encoding="utf-8")
    return directory


@pytest.fixture()
def assembled(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    root.mkdir()
    log = tmp_path / "lifecycle.log"
    monkeypatch.setenv("PLUGIN_LIFECYCLE_LOG", str(log))
    monkeypatch.delenv("PLUGIN_FAIL_STOP", raising=False)

    manager = PluginManager(plugin_dir=str(root))
    monkeypatch.setattr(manager_module, "_global_plugin_manager", manager)
    store = PluginPermissionStore(path=str(tmp_path / "permissions.json"),
                                  declaredProvider=manager.declaredPermissionsOf)
    monkeypatch.setattr(plugin_permissions, "getPermissionStore", lambda *a, **k: store)
    monkeypatch.setattr(plugin_route_mount, "getPermissionStore", lambda *a, **k: store)
    app = FastAPI()
    plugin_route_mount.setPluginApp(app)
    yield manager, root, log, app
    plugin_route_mount.resetPluginMounts()
    plugin_route_mount.setPluginApp(None)
    monkeypatch.delenv("PLUGIN_LIFECYCLE_LOG", raising=False)
    monkeypatch.delenv("PLUGIN_FAIL_STOP", raising=False)


def _events(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


@pytest.mark.asyncio
async def test_disable_runs_real_stop_destroy_and_removes_live_routes(assembled):
    manager, root, log, _app = assembled
    manager.install_plugin(_write_plugin(root, "probe"))
    assert manager.enable_plugin("probe")
    manager.load_plugin("probe")
    await manager.startPlugin("probe")
    plugin_route_mount.mountPluginRoutes("probe", actor="tester")
    assert manager.routesMounted("probe")[0] is True

    await manager.disablePluginAsync("probe")

    assert _events(log)[-2:] == ["stop", "destroy"]
    assert manager.get_plugin("probe").enabled is False
    assert manager.routesMounted("probe")[0] is False, "禁用后活路由仍在"


@pytest.mark.asyncio
async def test_stop_failure_rolls_back_disable_state(assembled, monkeypatch):
    manager, root, log, _app = assembled
    manager.install_plugin(_write_plugin(root, "probe"))
    assert manager.enable_plugin("probe")
    manager.load_plugin("probe")
    await manager.startPlugin("probe")
    plugin_route_mount.mountPluginRoutes("probe", actor="tester")
    monkeypatch.setenv("PLUGIN_FAIL_STOP", "1")

    with pytest.raises(PluginError):
        await manager.disablePluginAsync("probe")

    assert manager.get_plugin("probe").enabled is True, "stop 失败后禁用状态未回滚"
    assert manager.routesMounted("probe")[0] is True, "stop 失败后活路由被提前拆掉"
    assert "destroy" not in _events(log)


@pytest.mark.asyncio
async def test_same_name_reinstall_rejects_loaded_plugin_without_losing_old_instance(assembled):
    manager, root, _log, _app = assembled
    manager.install_plugin(_write_plugin(root, "probe"))
    assert manager.enable_plugin("probe")
    old = manager.load_plugin("probe")

    with pytest.raises(PluginError) as raised:
        manager.install_plugin(_write_plugin(root, "probe"))

    assert raised.value.reason == "already_installed"
    assert manager.get_module("probe") is old


@pytest.mark.asyncio
async def test_shutdown_stops_and_unloads_every_loaded_plugin(assembled):
    manager, root, log, _app = assembled
    for name in ("one", "two"):
        manager.install_plugin(_write_plugin(root, name))
        assert manager.enable_plugin(name)
        manager.load_plugin(name)
        await manager.startPlugin(name)
        plugin_route_mount.mountPluginRoutes(name, actor="tester")

    await manager.shutdown()

    assert _events(log).count("stop") == 2
    assert _events(log).count("destroy") == 2
    assert manager.moduleInfo("one") is None and manager.moduleInfo("two") is None
    assert manager.routesMounted("one")[0] is False
    assert manager.routesMounted("two")[0] is False
