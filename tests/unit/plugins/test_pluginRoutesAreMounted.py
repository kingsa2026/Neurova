# -*- coding: utf-8 -*-
"""插件声明的 HTTP 路由必须真挂进运行中的 app，而且只经「第二次授权」才挂得上（台账 §6-155，P2）。

P1 留下一句诚实声明并把读数钉成恒 `false`：装载与「插件可注册路由」是两次授权。
本文件把那两次授权都做成真的，且钉三件事——

1. **门是真的**：未确认全部声明权限 ⇒ 挂不上；声明了 `execute:commands`/`admin` ⇒ 永远挂不上
   （聚合规则：清单必须显式声明过 `permissions`，且声明 ⊆ 已确认；§6-159 收口）。
2. **挂载是真的**：挂上之后请求真的落到插件类的方法上并执行了插件文件里的代码
   （不是把 `_PLUGINS` 字典里的布尔翻一下——那正是 P1 之前那副样子）。
3. **边界是真的**：插件只能在自己的命名空间 `/api/v1/plugin-api/{plugin_id}/` 里出现，
   `auth_required: false` 不被采信，路径不能遮蔽核心路由；摘除（禁用/卸载/显式 unmount）
   之后活 app 里那条路由必须真的 404。

没有 3 的 1、2 就是「任何人装个插件就能在 /api/v1/* 上任挑一个位置插 handler」，
那比记账面危险得多。判据形态按真产物取：状态码读数（401/404/200）＋插件自己写的标记值，
不读 FastAPI 路由表形状（`_IncludedRouter` 的 `.path` 读不到，见台账踩坑记录）。
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]

import pytest
from tests import ast_scan
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user
from neurova.api.endpoints import plugin as plugin_api
from neurova.plugins.plugin_api_registry import get_plugin_api_registry, reset_plugin_api_registry
from neurova.plugins.plugin_manager import get_plugin_manager, reset_plugin_manager
from neurova.plugins.plugin_permissions import (
    PluginPermissionStore,
    resetPermissionStore,
)


def _mount():
    """挂载模块。缺失即红灯（红在断言上，不是 collection error——
    整套件因 import 失败会以「0 用例」混进通过数里，见台账踩坑记录）。"""
    try:
        return importlib.import_module("neurova.plugins.plugin_route_mount")
    except ModuleNotFoundError as exc:
        pytest.fail("插件路由挂载单点模块不存在，第二次授权没有执行点：%s" % exc)

USER = {"user_id": "1", "username": "tester", "role": "admin"}

#: 插件代码：模块级写标记（证明 exec 真发生过），类是最小合法 `BasePlugin` 实现，
#: `status()` 返回一个只能由真执行才拿得出的值。
_PLUGIN_SOURCE = '''
import os, pathlib
pathlib.Path(os.environ["PLUGIN_MOUNT_MARK"]).write_text("executed")
from neurova.plugins.base_plugin import BasePlugin

class MountProbe(BasePlugin):
    async def on_initialize(self):
        pass

    async def on_start(self):
        self.started = True

    async def on_stop(self):
        self.started = False

    async def on_destroy(self):
        pass

    def status(self):
        # 回读**调用面**看到的声明作用域：收口后拦不拦不由本包判断，
        # 由 skills 那份 `check_tool_permission` 在工具执行咽喉处裁。
        from neurova.skills.permissions import check_tool_permission, current_skill_permissions

        perms = current_skill_permissions()
        return {"marker": "from-plugin-code", "plugin": self.plugin_id,
                "scope_present": perms is not None,
                "network_allowed": bool(perms is not None and perms.network),
                "undeclared_tool_denial": check_tool_permission(perms, "browser_navigate")}

    def extra(self):
        return {"marker": "extra"}
'''


_UNSET = object()


def _writePlugin(root, name, *, endpoints=None, permissions=_UNSET, surfaces=None,
                 source=_PLUGIN_SOURCE):
    """`permissions=None` 与 `permissions={}` 是**两件事**：前者整节缺失（§6-159 之后挂不上），
    后者是显式声明"我什么都不要"（可以挂，且调用面 fail-closed）。"""
    pdir = root / name
    pdir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "version": "1.0.0",
        "description": "mount probe",
        "entry_point": "main.py",
        "module_class": "MountProbe",
        "api_endpoints": list(endpoints if endpoints is not None else
                              [{"method": "GET", "path": "status", "handler_name": "status"}]),
    }
    if permissions is _UNSET:
        manifest["permissions"] = {}          # 默认给一个显式空声明
    elif permissions is not None:
        manifest["permissions"] = dict(permissions)
    # permissions=None ⇒ 整节缺失（`testManifestWithoutPermissionsSectionIsRefused` 用）
    if surfaces is not None:
        manifest["framework_surfaces"] = list(surfaces)
    (pdir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (pdir / "main.py").write_text(source, encoding="utf-8")
    return pdir


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """真 app + 真 TestClient + 插件根与授予文件都指到 tmp（跨用例不串状态）。"""
    root = tmp_path / "plugins"
    root.mkdir()
    monkeypatch.setenv("PLUGIN_MOUNT_MARK", str(tmp_path / "mount.mark"))

    resetPermissionStore()
    reset_plugin_api_registry()
    reset_plugin_manager()

    app = FastAPI()
    app.include_router(plugin_api.router, prefix="/api/v1/plugins")
    app.dependency_overrides[get_current_user] = lambda: dict(USER)
    _mount().setPluginApp(app)

    manager = get_plugin_manager(str(root))
    store = PluginPermissionStore(path=str(tmp_path / "permissions.json"),
                                  declaredProvider=manager.declaredPermissionsOf)
    monkeypatch.setattr("neurova.plugins.plugin_permissions.getPermissionStore",
                        lambda *a, **k: store)

    with TestClient(app) as client:
        client.root = root
        client.manager = manager
        client.store = store
        client.app = app
        client.auditLogger = _redirectAudit(monkeypatch, tmp_path / "audit.db")
        yield client

    mount = _mount()
    mount.resetPluginMounts()
    mount.setPluginApp(None)
    reset_plugin_api_registry()
    reset_plugin_manager()
    resetPermissionStore()


def _redirectAudit(monkeypatch, dbPath):
    """审计写进 tmp 并返回那条 logger（`log_audit` 绑进程级单例，默认落点在数据根之外——
    本批只登记不搬，测试不许往家目录写）。"""
    from neurova.security.audit_logger import AuditLogEntry, AuditLogger

    logger = AuditLogger(db_path=str(dbPath))
    saved = logger._db_path
    logger._db_path = str(dbPath)
    if saved != str(dbPath):
        # 复用中的单例不会重新建表（`_initialized` 已 True），新落点必须先建表，
        # 否则 INSERT 失败会被「审计写不进去 ⇒ 变更回滚」那条规则读成红。
        logger._init_db()

    def _write(event_type, severity, **kwargs):
        return logger.log(AuditLogEntry(event_type=event_type, severity=severity, **kwargs))

    import neurova.plugins.plugin_permissions as permissions

    monkeypatch.setattr(permissions, "log_audit", _write)
    monkeypatch.setattr(_mount(), "log_audit", _write)
    return logger


def _install(client, name, **kw):
    pdir = _writePlugin(client.root, name, **kw)
    return client.post("/api/v1/plugins/%s/install" % name, json={"source": str(pdir)})


def _grantAll(client, name):
    for value in client.manager.declaredPermissionsOf(name):
        client.store.grant(name, value, grantedBy="admin-1")


def _load(client, name):
    assert client.post(f"/api/v1/plugins/{name}/enable").status_code == 200
    loaded = client.post(f"/api/v1/plugins/{name}/load")
    assert loaded.status_code == 200, loaded.text
    return loaded


class TestMountNeedsASecondAuthorization:
    def testEnabledAndLoadedAloneDoesNotMount(self, client):
        _install(client, "quiet")
        _load(client, "quiet")

        resp = client.get("/api/v1/plugin-api/quiet/status")

        assert resp.status_code == 404, (
            "装载即挂路由＝第二次授权不存在，P1 那句『两次授权』就成了空话")
        view = client.get("/api/v1/plugins/quiet").json()["data"]
        assert view["routes_mounted"] is False
        assert "授权" in view["routes_reason"], view["routes_reason"]

    def testPartialConfirmationKeepsRoutesOff(self, client):
        _install(client, "half", permissions={"network": True, "file": True},
                 surfaces=["read:events"])
        _load(client, "half")
        client.store.grant("half", "network", grantedBy="admin-1")
        client.store.grant("half", "read:events", grantedBy="admin-1")

        resp = client.post("/api/v1/plugins/half/routes/mount")

        assert resp.status_code == 409, resp.text
        assert "file" in resp.text, "拒了不点名还差哪一项——人无法据此补确认：%s" % resp.text
        assert client.get("/api/v1/plugin-api/half/status").status_code == 404

    def testManifestWithoutPermissionsSectionIsRefused(self, client):
        """§6-155 的空真通过在这里修掉：只判"声明 ⊆ 已确认"时，
        不写 `permissions` 的清单会**空真过门**，而它一被请求就拥有整个进程的能力。"""
        _install(client, "silent", permissions=None)   # 显式：整节缺失
        _load(client, "silent")

        resp = client.post("/api/v1/plugins/silent/routes/mount")

        assert resp.status_code == 409, resp.text
        assert "permissions" in resp.text, resp.text
        assert client.store.mountAuthorized("silent") is False, (
            "拒挂却把挂载授权记下来了：下一次启动重放会再试一遍")
        assert client.get("/api/v1/plugin-api/silent/status").status_code == 404

    def testExplicitEmptyDeclarationMountsAndFailsClosed(self, client):
        """显式 `permissions: {}` 是合法的"我什么都不要"：可以挂，但调用面一律拒。"""
        _install(client, "plain", permissions={})
        _load(client, "plain")
        assert client.post("/api/v1/plugins/plain/routes/mount").status_code == 200

        body = client.get("/api/v1/plugin-api/plain/status").json()

        assert body["scope_present"] is True, "没把声明装进作用域＝收口没接上，拦的是空气"
        assert body["network_allowed"] is False
        assert body["undeclared_tool_denial"], (
            "未声明的工具没被调用面拒——那『可授予 + 真拦』就是句空话")

    def testAuthorizationIsPersistedAndReadable(self, client):
        _install(client, "signed")
        _load(client, "signed")
        client.post("/api/v1/plugins/signed/routes/mount")

        assert client.store.mountAuthorized("signed") is True
        reopened = PluginPermissionStore(path=client.store.path,
                                         declaredProvider=client.manager.declaredPermissionsOf)
        assert reopened.mountAuthorized("signed") is True, (
            "挂载授权是人的决定，只留内存＝重启即失，面板却会显示『上次挂过』")


class TestTheGuardsCanFail:
    """反空转：把收口的两处动作桩掉，对应的格子必须翻红。

    收口这类改动最舒服的失效形态是"判据在演自己"——所以每加一条真拦，就配一格
    "把它假做完，判据必须红"。用 monkeypatch 而不是回退生产件：回退会让 import 断在
    词汇共享上（collection error），那种红什么也没证明。
    """

    def test_droppingTheScopeWrapperIsCaught(self, client, monkeypatch):
        mount = _mount()
        monkeypatch.setattr(mount, "_withSkillPermissionScope",
                            lambda pluginId, handler, manager: handler)
        _install(client, "nostub", permissions={})
        _load(client, "nostub")
        assert client.post("/api/v1/plugins/nostub/routes/mount").status_code == 200

        body = client.get("/api/v1/plugin-api/nostub/status").json()

        assert body["scope_present"] is False, (
            "去掉包装后作用域确实不在——这一格反过来证明 `testExplicitEmptyDeclarationMountsAndFailsClosed` "
            "不是在演空转（它断的是 True）")

    def test_trustingAnAbsentPermissionsSectionIsCaught(self, client, monkeypatch):
        from neurova.plugins import plugin_manager as pm

        monkeypatch.setattr(pm.PluginManager, "permissionsDeclared", lambda self, name: True)
        _install(client, "trustme", permissions=None)
        _load(client, "trustme")

        mounted = client.post("/api/v1/plugins/trustme/routes/mount")

        assert mounted.status_code == 200, (
            "把「整节缺失」当已声明就直接放行——那正是 §6-155 那个空真通过的复活，"
            "而 `testManifestWithoutPermissionsSectionIsRefused` 会因为它红")


class TestCallTimeArbitrationIsTheSkillOne:
    """收口的实质：能力面授予之后，是 skills 那份在裁，不是插件包自己写的一句注释。"""

    def testDeclaredCapabilityReachesTheScope(self, client):
        _install(client, "netted", permissions={"network": True})
        _load(client, "netted")
        client.store.grant("netted", "network", grantedBy="admin-1")
        assert client.post("/api/v1/plugins/netted/routes/mount").status_code == 200

        body = client.get("/api/v1/plugin-api/netted/status").json()

        assert body["network_allowed"] is True
        assert body["undeclared_tool_denial"] is None, (
            "声明并确认了 network 还被拒——那道门会把插件做成废件")

    def testScopeDoesNotLeakOutsideTheRequest(self, client):
        from neurova.skills.permissions import current_skill_permissions

        _install(client, "leaky", permissions={"network": True})
        _load(client, "leaky")
        client.store.grant("leaky", "network", grantedBy="admin-1")
        client.post("/api/v1/plugins/leaky/routes/mount")
        client.get("/api/v1/plugin-api/leaky/status")

        assert current_skill_permissions() is None, (
            "作用域泄到请求外：下一个无关调用会带着这个插件的授权跑")


class TestMountedRouteIsReallyLive:
    def testMountRunsThePluginHandler(self, client):
        _install(client, "live")
        _load(client, "live")
        assert client.post("/api/v1/plugins/live/routes/mount").status_code == 200

        resp = client.get("/api/v1/plugin-api/live/status")

        assert resp.status_code == 200, resp.text
        assert resp.json()["marker"] == "from-plugin-code", (
            "挂上了却不经插件方法——那是记账面换了个位置")

    def testViewReportsMountedStateAndPaths(self, client):
        _install(client, "view")
        _load(client, "view")
        client.post("/api/v1/plugins/view/routes/mount")

        data = client.get("/api/v1/plugins/view").json()["data"]

        assert data["routes_mounted"] is True
        assert "/api/v1/plugin-api/view/status" in json.dumps(data["mounted_routes"])

    def testRegistryIsTheSingleStoreTheMounterReads(self, client):
        """装载把清单声明喂进 `PluginAPIRegistry`，挂载只从注册器取——两处各挂一份即教义第 7 未闭环。"""
        _install(client, "fed",
                 endpoints=[{"method": "GET", "path": "status", "handler_name": "status"},
                            {"method": "POST", "path": "extra", "handler_name": "extra"}])
        _load(client, "fed")

        registered = get_plugin_api_registry().get_plugin_endpoints("fed")

        assert {(e.method, e.path) for e in registered} == {("GET", "status"), ("POST", "extra")}

        client.post("/api/v1/plugins/fed/routes/mount")

        assert client.post("/api/v1/plugin-api/fed/extra", json={}).status_code == 200

    def testMountWritesTheAuditTrail(self, client):
        from neurova.security.audit_logger import AuditEventType

        _install(client, "audited")
        _load(client, "audited")
        client.post("/api/v1/plugins/audited/routes/mount")

        rows = [e for e in _auditRows(client, AuditEventType.SECURITY_EVENT)
                if e.resource_id == "audited"]
        assert rows and rows[0].action == "plugin_routes_mounted", (
            "开 HTTP 面这件事没留痕——事后读不出是谁在哪一刻放出去的")


class TestMountBoundary:
    def testAuthRequiredFalseIsNotHonoured(self, client):
        _install(client, "loose",
                 endpoints=[{"method": "GET", "path": "status", "handler_name": "status",
                             "auth_required": False}])
        _load(client, "loose")
        assert client.post("/api/v1/plugins/loose/routes/mount").status_code == 200

        # 撤掉登录态注入：真实身份门必须还在（插件自己声明「不用认证」不被采信）
        client.app.dependency_overrides = {}
        try:
            gated = client.get("/api/v1/plugin-api/loose/status")
        finally:
            client.app.dependency_overrides = {get_current_user: lambda: dict(USER)}

        assert gated.status_code == 401, gated.text
        report = client.get("/api/v1/plugins/loose").json()["data"]
        assert report["auth_escalation_declined"], (
            "声明『不用认证』被拒且必须**可见**——静默放宽安全面是最坏形态")

    def testDeclaredPathCannotLeaveTheNamespace(self, client):
        for index, sneaky in enumerate(("/api/v1/plugins/status", "../../agents/delete",
                                        "..%2f..%2fmedia", "/plugin-api/other/x")):
            name = "evil-%d" % index
            _install(client, name,
                     endpoints=[{"method": "GET", "path": sneaky, "handler_name": "status"}])
            _load(client, name)

            resp = client.post("/api/v1/plugins/%s/routes/mount" % name)

            assert resp.status_code == 400, "%s 竟然被受理：%s" % (sneaky, resp.text)
            assert "命名空间" in resp.text or "namespace" in resp.text.lower()
            assert client.get("/api/v1/plugin-api/%s/x" % name).status_code == 404
        core = client.get("/api/v1/plugins/status")
        assert core.status_code == 200 and "total" in core.json()["data"], (
            "核心管理面读数被插件声明顶掉：挂载边界不成立")

    def testExistingRouteIsNotShadowed(self, client):
        """命名空间内若已有真路由（核心侧先占了位置），插件必须被拒，而不是叠一条各说各话。"""

        async def _core():
            return {"owner": "core"}

        client.app.add_api_route("/api/v1/plugin-api/shadow/status", _core, methods=["GET"])
        _install(client, "shadow")
        _load(client, "shadow")

        resp = client.post("/api/v1/plugins/shadow/routes/mount")

        assert resp.status_code == 409, resp.text
        assert "冲突" in resp.text or "conflict" in resp.text.lower()
        assert client.get("/api/v1/plugin-api/shadow/status").json()["owner"] == "core", (
            "同一路径两份实现——后挂的那份谁赢取决于遍历顺序（教义第 7 未闭环）")

    def testMountTwiceDoesNotDuplicateTheRoute(self, client):
        _install(client, "twice")
        _load(client, "twice")
        client.post("/api/v1/plugins/twice/routes/mount")

        again = client.post("/api/v1/plugins/twice/routes/mount")

        assert again.status_code == 200, again.text
        paths = [r.path for r in client.app.router.routes
                 if getattr(r, "path", "") == "/api/v1/plugin-api/twice/status"]
        assert len(paths) == 1, "同一路径挂了两条：哪条接流量取决于顺序，而面板只显示一条"

    def testMissingHandlerRefusesTheWholePlugin(self, client):
        """全有或全无：审的是「这个插件的这批端点」，挂上一半比挂不上更让人误判。"""
        _install(client, "broken",
                 endpoints=[{"method": "GET", "path": "status", "handler_name": "status"},
                            {"method": "GET", "path": "ghost", "handler_name": "nope"}])
        _load(client, "broken")

        resp = client.post("/api/v1/plugins/broken/routes/mount")

        assert resp.status_code == 400, resp.text
        assert "nope" in resp.text
        assert client.get("/api/v1/plugin-api/broken/status").status_code == 404, (
            "拒了却把好的那条挂上去了：面板显示未挂载而流量真的进来了")


class TestUnmountIsComplete:
    def testExplicitUnmountRemovesItFromTheLiveApp(self, client):
        _install(client, "off")
        _load(client, "off")
        client.post("/api/v1/plugins/off/routes/mount")
        assert client.get("/api/v1/plugin-api/off/status").status_code == 200

        assert client.post("/api/v1/plugins/off/routes/unmount").status_code == 200

        assert client.get("/api/v1/plugin-api/off/status").status_code == 404
        assert client.store.mountAuthorized("off") is False

        # unmount ≠ unload：声明与 handler 的绑定留着，重挂不该要求再装载一次
        # （要再装载才能重挂，等于把「先关一会儿」变成「必须重启插件」）
        again = client.post("/api/v1/plugins/off/routes/mount")
        assert again.status_code == 200, again.text
        assert client.get("/api/v1/plugin-api/off/status").status_code == 200

    def testUnloadDropsTheHandlerBindings(self, client):
        """卸载装载时登记的那份 handler 绑定：它还指向刚从 `sys.modules` 摘掉的模块，
        留着就可能在下次挂载里被调到死对象上。"""
        _install(client, "unbind")
        _load(client, "unbind")
        assert get_plugin_api_registry().get_plugin_endpoints("unbind")

        client.post("/api/v1/plugins/unbind/unload")

        assert get_plugin_api_registry().get_plugin_endpoints("unbind") == []
        assert client.post("/api/v1/plugins/unbind/routes/mount").status_code == 500,             "未装载却挂上了路由"

    def testDisableUnmountsRoutes(self, client):
        _install(client, "disableme")
        _load(client, "disableme")
        client.post("/api/v1/plugins/disableme/routes/mount")

        assert client.post("/api/v1/plugins/disableme/disable").status_code == 200

        assert client.get("/api/v1/plugin-api/disableme/status").status_code == 404, (
            "禁用了还在接流量——禁用不是读数，是可执行的动作")

    def testUninstallLeavesNoGrantNoRoute(self, client):
        _install(client, "gone", permissions={"file": True}, surfaces=["read:events"])
        _load(client, "gone")
        client.store.grant("gone", "file", grantedBy="admin-1")
        client.store.grant("gone", "read:events", grantedBy="admin-1")
        client.post("/api/v1/plugins/gone/routes/mount")

        assert client.delete("/api/v1/plugins/gone/uninstall").status_code == 200

        assert client.get("/api/v1/plugin-api/gone/status").status_code == 404
        assert client.store.grantedFor("gone") == [], (
            "孤儿授予：同名插件重装即白捡上次的能力")
        assert client.store.mountAuthorized("gone") is False


class TestEveryRefusalHasHttpSemantics:
    """每一条 `PluginError` 成因都必须在端点那张映射表里有语义（本次实测就漏了一条：
    聚合门的 `permissions_unconfirmed` 没登记 ⇒ 409 被画成 500，而端点只 warning 不红）。

    扫 AST 而不是扫文本：`raise PluginError("x", ...)` 的字面首参才是成因集合，
    注释里提到的名字不算。
    """

    def _reasons(self):
        import ast

        found = set()
        # 按目录扫，不手抄文件清单：包里没有 `PluginError` 抛点＝没人能授予也没人能挂，
        # 那种「扫不到东西」的绿是本判据最危险的失效形态（成因集合为空时下面的格子会红）。
        # 枚举与解析走共享预算（含 `__pycache__` 剪枝；只扫一遍）。
        for path in sorted(ast_scan.filesUnder(PROJECT_ROOT / "neurova" / "plugins")):
            tree = ast_scan.transientTree(path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name != "PluginError" or not node.args:
                    continue
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    found.add(first.value)
        return found

    def test_everyRaisedReasonIsMappedAndNothingMappedIsStale(self):
        from neurova.api.endpoints import plugin as plugin_endpoint

        raised = self._reasons()
        mapped = set(plugin_endpoint._REASON_TO_STATUS)

        assert raised and len(raised) >= 20, "扫不到成因集合（判据自己空转了）"
        missing = raised - mapped
        assert not missing, "这些成因会被画成 500，调用方读不出语义：%s" % sorted(missing)
        stale = mapped - raised
        assert not stale, "映射表里留着从未被抛出的成因：%s（要么还在别处抛，要么删掉）" % sorted(stale)

    def test_guardDetectsAnUnmappedReason(self):
        """反向对照：临时塞一条没登记的成因，本判据必须能咬住。"""
        from neurova.api.endpoints import plugin as plugin_endpoint

        raised = self._reasons()
        sample = sorted(raised)[0]
        with patch.object(plugin_endpoint, "_REASON_TO_STATUS",
                          {k: v for k, v in plugin_endpoint._REASON_TO_STATUS.items()
                           if k != sample}):
            assert sample not in plugin_endpoint._REASON_TO_STATUS
            assert {sample} - set(plugin_endpoint._REASON_TO_STATUS),                 "探测器自己失效：它连一条被抽掉的成因都看不见"


def _auditRows(client, event_type):
    """读数从夹具那条 tmp 审计面取（不用全局 getter——它可能指向别人那条）。"""
    return client.auditLogger.query(event_type=event_type, limit=500)
