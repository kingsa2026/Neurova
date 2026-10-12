# -*- coding: utf-8 -*-
"""插件的「装过什么、启没启用」跨重启（用户 2026-10-12 裁「落盘状态 + 只发现不装载」，台账 §6-164）。

## 缺口实测（三处，逐条核过，不沿用台账旧描述）

1. `PluginManager.__init__` 只做 `mkdir`，`self._plugins` 是空字典；登记与 `enabled`
   全都只在内存里（`install_plugin:287`、`enable_plugin:717`）。
2. 于是**重启后列表是空的**——面板会说"这台机器从没装过插件"，而
   `<数据根>/plugins/permissions.json` 里那个插件的授予记录与挂载许可**还在**：
   一份说"没装过"，另一份还替它保留着授权。这两个读数不同源，比"没落盘"更值得修。
3. `discover_plugins()` 不是死代码——`POST /plugins/discover`（`endpoints/plugin.py:237`）
   在调它，且它"列出但不安装"，这条边界是对的。所以本批**不把发现变成安装**，
   只把"已登记的记录 + 人给的 enabled"接上持久层。

## 这条裁定里刻意没做的事

**不自动装载、不自动挂路由**。`load_plugin` 是执行第三方代码，挂载是 P2 立的第二次授权
（§6-155），而 P3（来源白名单 + 构件完整性校验）至今未做——开机自启未校验代码不是便利，是风险。
所以：`loaded` **绝不**从盘上复活；启动那遍重挂（`startupMountPass`）此后每开机都会
点名 `entry_not_loaded` 的拒挂，那是**如实读数**而不是 bug（它原来"通常无事可做"的注释随之改掉）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from neurova.plugins.plugin_errors import PluginError

_MANIFEST = {
    "name": "probe",
    "version": "1.0.0",
    "description": "state probe",
    "entry_point": "main.py",
    "module_class": "ProbePlugin",
    "permissions": {},
    "framework_surfaces": [],
    "api_endpoints": [],
}

_SOURCE = '''
from neurova.plugins.base_plugin import BasePlugin


class ProbePlugin(BasePlugin):
    async def on_initialize(self):
        pass

    async def on_start(self):
        pass

    async def on_stop(self):
        pass

    async def on_destroy(self):
        pass
'''


def _pluginDir(root: Path, name: str = "probe") -> Path:
    directory = root / name
    directory.mkdir(parents=True, exist_ok=True)
    manifest = dict(_MANIFEST, name=name)
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (directory / "main.py").write_text(_SOURCE, encoding="utf-8")
    return directory


@pytest.fixture()
def root(tmp_path):
    pluginRoot = tmp_path / "plugins"
    pluginRoot.mkdir()
    return pluginRoot


def _managerAt(pluginRoot):
    from neurova.plugins.plugin_manager import PluginManager

    return PluginManager(plugin_dir=str(pluginRoot))


class TestInstalledStateSurvives:
    def test_installIsWrittenToAFileInThePluginRoot(self, root):
        manager = _managerAt(root)

        manager.install_plugin(_pluginDir(root))

        assert (root / "state.json").is_file(), (
            "登记只写在内存字典里——重启即抹掉，而 permissions.json 里的授权还留着，"
            "两个读数从此各说各话")

    def testASecondManagerSeesTheInstalledPlugin(self, root):
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))

        reopened = _managerAt(root)

        assert reopened.has_plugin("probe"), "换实例（＝重启）后列表空了"
        assert reopened.get_plugin("probe").path == str(_pluginDir(root))

    def testEnabledFlagSurvivesButLoadedDoesNot(self, root):
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))
        assert manager.enable_plugin("probe") is True
        manager.load_plugin("probe")
        assert manager.get_plugin("probe").loaded is True

        reopened = _managerAt(root)
        record = reopened.get_plugin("probe")

        assert record.enabled is True, (
            "enabled 是人给的决定，不落盘就得每次开机重点一遍——人于是闭眼点")
        assert record.loaded is False, (
            "`loaded` 从盘上复活＝开机自动执行第三方代码；P3（构件完整性）没做之前这是禁区")

    def testDisableAlsoSurvives(self, root):
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))
        manager.enable_plugin("probe")
        assert manager.disable_plugin("probe") is True

        assert _managerAt(root).get_plugin("probe").enabled is False, (
            "禁用没落盘：重启后它又变成启用状态，等于把用户的收回动作吃掉")

    def testUninstallRemovesTheRecordButKeepsTheFiles(self, root):
        manager = _managerAt(root)
        directory = _pluginDir(root)
        manager.install_plugin(directory)

        assert manager.uninstall_plugin("probe") is not False
        reopened = _managerAt(root)

        assert not reopened.has_plugin("probe")
        assert (directory / "manifest.json").is_file(), (
            "卸载删记录不删盘上文件是 §6-150 立的既有契约（销毁用户文件要另一次授权）")

    def testTheFileIsTheOnlySourceReadAtConstruction(self, root):
        """反空转：直接改文件，新实例必须跟着改口——否则上面五格可能都在读别的地方。"""
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))

        statePath = root / "state.json"
        payload = json.loads(statePath.read_text(encoding="utf-8"))
        payload["plugins"]["probe"]["enabled"] = False
        statePath.write_text(json.dumps(payload), encoding="utf-8")

        assert _managerAt(root).get_plugin("probe").enabled is False


class TestFailureShapes:
    def testWriteFailureRollsBackBothDirectionsAndReportsFalse(self, root, monkeypatch):
        """盘上没写成 ⇒ 内存也得回到旧值并回 False（与 §6-160 语言偏好、
        §6-155 授权存储同一条纪律；两个方向各验一次，只验一边会漏掉回滚写反的那一半）。"""
        from neurova.plugins import plugin_manager as managerModule

        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))
        assert manager.get_plugin("probe").enabled is False

        def boom(*a, **k):
            raise OSError("disk full")

        # 启用失败：不该留下"已启用"
        monkeypatch.setattr(managerModule, "atomic_write_text", boom)
        assert manager.enable_plugin("probe") is False, "写盘失败仍回 True——管理员以为生效了"
        assert manager.get_plugin("probe").enabled is False

        # 真启用一次，再让禁用失败：不该留下"已禁用"
        monkeypatch.undo()
        assert manager.enable_plugin("probe") is True
        monkeypatch.setattr(managerModule, "atomic_write_text", boom)
        assert manager.disable_plugin("probe") is False
        assert manager.get_plugin("probe").enabled is True, (
            "禁用没写成却翻布尔——HTTP 面已被 _teardownRoutes 关掉而状态说还启用，"
            "下一次挂载会拿着一个两边都不认的状态跑")

    def testCorruptStateFileIsQuarantinedNotOverwritten(self, root):
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))
        statePath = root / "state.json"
        statePath.write_text('{"version": 1, "plugins": {"pro', encoding="utf-8")  # 半截

        reopened = _managerAt(root)

        assert list(root.glob("state.json.corrupt-*")), (
            "半截文件留在原路径＝下一次成功写入会把真数据覆盖成内存空态")
        assert not reopened.has_plugin("probe")

    def testUnknownStoreVersionIsRefusedNotMigrated(self, root):
        _pluginDir(root)
        (root / "state.json").write_text(
            json.dumps({"version": 99, "plugins": {}}), encoding="utf-8")

        with pytest.raises(PluginError) as raised:
            _managerAt(root).loadStateOrRaise()

        assert raised.value.reason == "state_store_version", raised.value.reason


class TestDiscoveryStaysADifferentThing:
    def testUnregisteredDirectoryIsNotInstalled(self, root):
        """发现 ≠ 登记：盘上有目录不代表它过了安装门（清单校验、能力声明合法性）。"""
        _pluginDir(root, "sneaky")

        manager = _managerAt(root)

        assert not manager.has_plugin("sneaky"), (
            "启动时把发现的目录直接当已安装——那等于绕过 install_plugin 的两道门")
        assert "sneaky" in manager.unregisteredPluginDirs(), (
            "但这条读数要看得见：磁盘上有个没登记过的目录，管理员应该知道")

    def testStateEntryWhoseDirectoryVanishedIsSkippedAndNamed(self, root, caplog):
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root, "gone"))
        assert manager.has_plugin("gone")

        import shutil

        shutil.rmtree(root / "gone")
        reopened = _managerAt(root)

        assert not reopened.has_plugin("gone"), "记录指向已不存在的目录还留在列表里＝幽灵行"
        assert "gone" in " ".join(caplog.messages), "跳过却没点名：管理员永远不知道为什么少了一个插件"

    def testListEndpointSeparatesEmptyBecauseUnreadableFromEmptyBecauseNothingInstalled(self, root):
        """空列表必须能区分"真没装过"与"状态文件读不出"——后者被读成前者就是一次静默的 uninstall-all。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api.endpoints import plugin as pluginEndpoint
        from neurova.plugins import plugin_manager as managerModule

        _managerAt(root).install_plugin(_pluginDir(root))
        (root / "state.json").write_text("not json at all", encoding="utf-8")

        manager = managerModule.PluginManager(plugin_dir=str(root))
        managerModule._global_plugin_manager = manager
        try:
            app = FastAPI()
            app.include_router(pluginEndpoint.router, prefix="/api/v1/plugins")
            # `plugin.py:59` 是**路由级**门（整个 router 挂 Depends），不覆盖就只会拿到 401；
            # 覆盖的对象必须是端点模块 import 的那一个（`neurova.api.auth.get_current_user`），
            # 打错对象会静默不生效（本仓记过两次的那族）。
            from neurova.api import auth as authModule

            app.dependency_overrides[authModule.get_current_user] = lambda: {
                "user_id": "tester", "username": "tester", "role": "admin"}
            with TestClient(app) as client:
                response = client.get("/api/v1/plugins/")
                assert response.status_code == 200, response.text
                listed = response.json()["data"]
        finally:
            managerModule.reset_plugin_manager()

        assert listed["items"] == []
        assert listed["state_load_error"] == "state_store_corrupt", (
            "状态读不出却回了一个干净的空列表：%r" % listed)
        assert list(root.glob("state.json.corrupt-*")), "损坏现场没被隔离"
        assert "probe" in listed["discovered_not_installed"] or \
            listed["discovered_not_installed"] == [], listed["discovered_not_installed"]


class TestNoSecondPersistencePath:
    def testStateManagerWritesThroughTheSingleAtomicWriter(self, root, monkeypatch):
        """落盘必须经 `atomic_write_text` 单点（裸 open 会留半截文件，见上两格）。"""
        from neurova.plugins import plugin_manager as managerModule

        calls = []
        real = managerModule.atomic_write_text

        def spy(path, text, **kw):
            calls.append(str(path))
            return real(path, text, **kw)

        monkeypatch.setattr(managerModule, "atomic_write_text", spy)
        manager = _managerAt(root)
        manager.install_plugin(_pluginDir(root))
        manager.enable_plugin("probe")

        assert calls and all(c.endswith("state.json") for c in calls), calls

    def testProductionCodeHasNoLegacyHomeFallbackPath(self):
        """`Path.home()/.neurova/plugins` 是那条已被注销的第二根（§6-150 复算过），别回来。

        按 **AST 调用形态**判而不是搜文本：`__init__` 的 docstring 里正写着"原实现默认
        `Path.home()/.neurova/plugins`"作为来历说明——文本包含检查会把这句证词当成违规
        （§6-162 刚记过的那枚自我指涉坑，这次是我自己写完立刻踩到）。
        """
        import ast

        source = Path(__file__).resolve().parents[3] / "neurova" / "plugins" / "plugin_manager.py"
        tree = ast.parse(source.read_text(encoding="utf-8"))

        offenders = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Attribute) and func.attr == "home"
                        and isinstance(func.value, ast.Name) and func.value.id == "Path"):
                    offenders.append(node.lineno)
        assert not offenders, "生产落点又长回用户主目录了（行 %s）" % offenders

        import neurova.plugins.plugin_manager as managerModule

        assert managerModule.STATE_FILE_NAME == "state.json", (
            "状态文件名没有单点常量，说明落点散在别处")
