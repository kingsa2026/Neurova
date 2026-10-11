# -*- coding: utf-8 -*-
"""插件面必须真的装载代码，而且装载源只能落在受控插件根内（用户 2026-10-11 改裁「做插件体系并接线」，台账 §6-150）。

这批与同日早先那笔退役（`e95d3a76`，−2206 行）方向相反，所以本文件同时钉两件事：
① **装载是真的**——`load` 之后插件文件被 import 并执行，不是把布尔翻一下；
② **边界也是真的**——只有位于插件根（数据根下的 `plugins/`）内的目录能被装载，
   远程 URL 源在 P1 明确回 501（不静默 False、也不谎报"已安装"）。
没有 ② 的 ① 就是"请求方指定任意路径执行代码"，那才是这条裁定最容易被做坏的方式。

⚠ 取回历史包体后先实测了一次"装一个真插件再加载"，结论是**走不通**：`plugin_manager.py` 里
`plugin_class()` 无参构造，而作者基类 `BasePlugin.__init__(self, manifest)` 要求 manifest ⇒
TypeError（真子类还额外带出四个未实现的抽象方法）。而它自带的 84 例全绿——因为 `load` 那几格
把 `_load_plugin_module` 整个 mock 掉了（幽灵替身形态）。本文件的 ④⑤ 两格就是来堵这条
"测试全绿而真链不通"的。
"""

from __future__ import annotations

import json
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import plugin as plugin_api
from neurova.core.data_root import dataPath
from neurova.plugins.plugin_manager import get_plugin_manager, reset_plugin_manager

USER = {"user_id": "1", "username": "tester", "role": "admin"}

#: 模块级副作用＝"exec 真发生过"的自证；类体是作者基类的最小合法实现（四个抽象方法齐备）。
_BASE_SUBCLASS = (
    "import os, pathlib\n"
    "from neurova.plugins.base_plugin import BasePlugin\n"
    "pathlib.Path(os.environ['PLUGIN_EXEC_MARK']).write_text('ran')\n"
    "class ProbePlugin(BasePlugin):\n"
    "    def on_initialize(self):\n        self.initialized = True\n"
    "    def on_start(self):\n        self.started = True\n"
    "    def on_stop(self):\n        self.started = False\n"
    "    def on_destroy(self):\n        self.destroyed = True\n"
)


def _writePlugin(root, name, *, body=None, manifest_extra=None):
    """在插件根内造一个真插件目录（manifest + 入口文件）。"""
    pdir = root / name
    pdir.mkdir(parents=True, exist_ok=True)
    manifest = {"name": name, "version": "1.0.0", "description": "probe", "author": "qa",
                "entry_point": "main.py", "dependencies": [], "permissions": []}
    manifest.update(manifest_extra or {})
    (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pdir / "main.py").write_text(body or "MARKER = 1\n", encoding="utf-8")
    return pdir


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """插件根指到 tmp；跑完清掉全局管理器，否则下一档拿到别人的实例（跨用例串状态）。"""
    root = tmp_path / "plugins"
    root.mkdir()
    reset_plugin_manager()
    mark = tmp_path / "exec.mark"
    monkeypatch.setenv("PLUGIN_EXEC_MARK", str(mark))

    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/v1/plugins")
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        test_client.root = root
        test_client.manager = get_plugin_manager(str(root))
        test_client.mark = mark
        yield test_client
    reset_plugin_manager()


def _install(client, name, **kw):
    pdir = _writePlugin(client.root, name, **kw)
    return client.post("/api/v1/plugins/%s/install" % name, json={"source": str(pdir)})


class TestOnlyThePluginRootMayBeLoaded:
    def test_installRejectsSourceOutsideTheRoot(self, client):
        outside = client.root.parent / "somewhere_else"
        _writePlugin(outside, "evil")

        resp = client.post("/api/v1/plugins/evil/install", json={"source": str(outside)})

        assert resp.status_code == 400, (
            "根外目录被收下了——那等于允许请求方指定任意路径执行代码：%s %s"
            % (resp.status_code, resp.text))
        assert "插件根" in resp.text or "plugin root" in resp.text.lower(), (
            "拒了却没点名成因（调用方无从知道是边界问题）：%s" % resp.text)
        assert not client.manager.has_plugin("evil"), "拒收却仍留下记录：读数与事实不符"

    def test_installRejectsTraversalInsideRootString(self, client):
        sneaky = str(client.root / ".." / ".." / "somewhere_else")

        resp = client.post("/api/v1/plugins/evil2/install", json={"source": sneaky})

        assert resp.status_code == 400, "路径穿越没先 resolve 就判边界：%s" % resp.text
        assert not client.manager.has_plugin("evil2")

    def test_remoteUrlSourceIsNamedNotSupported(self, client):
        """「含下载与安装面」是后续批次（要带供应链校验）；今天必须响亮地回 501。"""
        resp = client.post("/api/v1/plugins/remote/install",
                           json={"source": "https://example.test/x.zip"})

        assert resp.status_code == 501, (
            "远程源既没实现也不该静默成功（501＝诚实的 not_supported）：%s %s"
            % (resp.status_code, resp.text))
        assert not client.manager.has_plugin("remote")


class TestLoadingReallyExecutesThePluginFile:
    def test_loadRunsTheEntryPointFile(self, client):
        assert _install(client, "runner", body=_BASE_SUBCLASS).status_code == 200

        assert client.post("/api/v1/plugins/runner/enable").status_code == 200
        loaded = client.post("/api/v1/plugins/runner/load")
        assert loaded.status_code == 200, loaded.text

        assert client.mark.exists() and client.mark.read_text() == "ran", (
            "load 回 200 但插件文件里的代码从未执行——这又是「只翻布尔」的老形态")

    def test_basePluginSubclassIsInstantiable(self, client):
        """钉历史 defect：`plugin_class()` 无参构造，而作者基类要 manifest ⇒ 必 TypeError。"""
        _install(client, "author", body=_BASE_SUBCLASS)
        client.post("/api/v1/plugins/author/enable")

        assert client.post("/api/v1/plugins/author/load").status_code == 200

        instance = client.manager.get_module("author")
        assert instance is not None, "load 成功却拿不到实例"
        assert instance.manifest.plugin_id == "author", (
            "实例不是按清单构造的（manifest 缺失或错插件）：%r" % (instance.manifest,))

    def testModulesSurfaceReportsTheRealModuleAndClass(self, client):
        _install(client, "listed", body=_BASE_SUBCLASS)
        client.post("/api/v1/plugins/listed/enable")
        client.post("/api/v1/plugins/listed/load")

        data = client.get("/api/v1/plugins/listed/modules").json()["data"]

        assert data["modules"], "装了真插件而模块面还是空列表（退役期的恒空读数没改掉）"
        assert any("ProbePlugin" in str(m) for m in data["modules"]), data

    def testUnloadDropsTheImportedModuleFromTheProcess(self, client):
        """卸载必须真把 `sys.modules` 里那条摘掉——否则代码仍留在进程里，「卸载」是假的。"""
        _install(client, "leaky", body=_BASE_SUBCLASS)
        client.post("/api/v1/plugins/leaky/enable")
        client.post("/api/v1/plugins/leaky/load")
        modName = "neurova_plugin_leaky"
        assert modName in sys.modules, "装载期没按这个名字注册模块，判据抓不到东西"

        assert client.post("/api/v1/plugins/leaky/unload").status_code == 200

        assert modName not in sys.modules, (
            "unload 之后插件模块仍在进程内（再 load 会拿到旧实例）：%s" % modName)


class TestTheAccountingDictIsGone:
    def testEndpointNoLongerKeepsAPrivatePluginDict(self, client):
        """`_PLUGINS` 那份内存字典是第二份事实源，必须没有（教义第 6 条）。"""
        assert not hasattr(plugin_api, "_PLUGINS"), (
            "记账面又长回内存字典了——列表读数将与 manager 的真实状态分叉")

    def testListAndStatusReadFromTheManager(self, client):
        _install(client, "one")
        _install(client, "two")
        client.post("/api/v1/plugins/one/enable")

        listed = client.get("/api/v1/plugins/").json()["data"]
        status = client.get("/api/v1/plugins/status").json()["data"]

        assert sorted(p["name"] for p in listed["items"]) == ["one", "two"], listed
        assert status["total"] == 2 and status["enabled"] == 1, status


class TestFailuresAreNamedNotFolded:
    @pytest.mark.parametrize("verb,path", [
        ("get", "/api/v1/plugins/ghost"),
        ("get", "/api/v1/plugins/ghost/modules"),
        ("post", "/api/v1/plugins/ghost/load"),
        ("post", "/api/v1/plugins/ghost/unload"),
        ("post", "/api/v1/plugins/ghost/enable"),
        ("post", "/api/v1/plugins/ghost/disable"),
        ("delete", "/api/v1/plugins/ghost/uninstall"),
    ])
    def testUnknownPluginIdIsFourOhFour(self, client, verb, path):
        resp = getattr(client, verb)(path)

        assert resp.status_code == 404, "%s %s 应 404，实际 %s：%s" % (
            verb, path, resp.status_code, resp.text)

    def testLoadBeforeEnableIsRefusedWithReason(self, client):
        """「未启用就加载」是 manager 的既有约束，端点不许替它兜底做成成功或折成 404。"""
        _install(client, "quiet", body=_BASE_SUBCLASS)

        resp = client.post("/api/v1/plugins/quiet/load")

        assert resp.status_code == 409, (
            "未启用的插件被 load 成成功，或折成「不存在」：%s %s" % (resp.status_code, resp.text))
        assert "启用" in resp.text or "enable" in resp.text.lower(), resp.text

    def testUninstallKeepsTheFilesButForgetsTheRecord(self, client):
        """P1 的 uninstall 只该忘掉记录；**删用户文件**需要另一次确认，不混在这批里。"""
        pdir = _writePlugin(client.root, "keep")
        client.post("/api/v1/plugins/keep/install", json={"source": str(pdir)})

        resp = client.delete("/api/v1/plugins/keep/uninstall")

        assert resp.status_code == 200, resp.text
        assert not client.manager.has_plugin("keep")
        assert pdir.is_dir(), (
            "uninstall 把插件目录也删了——销毁用户文件不在 P1 的授权面里")


class TestP1BoundaryIsHonest:
    def testDeclaredEndpointsAreReportedAsNotMounted(self, client):
        """P1 只做装载，不挂路由；读数必须自己说清，别让人以为插件路由已生效。"""
        _install(client, "routes", body=_BASE_SUBCLASS,
                 manifest_extra={"api_endpoints": [{"method": "GET", "path": "/probe"}]})
        client.post("/api/v1/plugins/routes/enable")
        client.post("/api/v1/plugins/routes/load")

        data = client.get("/api/v1/plugins/routes/modules").json()["data"]

        assert data["routes_mounted"] is False, (
            "读数里没这条边界声明，就等于宣称插件路由已挂进活 app：%r" % (data,))
        assert data.get("routes_reason"), "只给 False 不给成因：%r" % (data,)

    def testDefaultPluginDirIsUnderDataRootNotHome(self):
        """取回的历史代码不能把 `Path.home()/.neurova/plugins` 那套落点带回来（§3 与数据根收口批）。"""
        reset_plugin_manager()
        try:
            manager = get_plugin_manager()
            assert str(manager.plugin_dir) == str(dataPath("plugins")), manager.plugin_dir
        finally:
            reset_plugin_manager()


class TestGuardsCanFail:
    def test_aBooleanFlippingStubWouldBeCaught(self, client, monkeypatch):
        """反空转：把装载换成「只翻布尔」的桩，第 ④ 格必须红——否则那些格在演空转。"""
        _install(client, "stub", body=_BASE_SUBCLASS)
        client.post("/api/v1/plugins/stub/enable")
        client.mark.unlink(missing_ok=True)
        monkeypatch.setattr(client.manager, "_load_plugin_module",
                            lambda record: __import__("types").ModuleType("fake"))

        client.post("/api/v1/plugins/stub/load")

        assert not client.mark.exists(), "本反证格的前提破了：桩替身竟然也写了标记"
        # 上面只证了"桩不会写标记"；真判据是第 ④ 格那条断言——这里把它当表达式再跑一次
        assert client.mark.exists() is False
