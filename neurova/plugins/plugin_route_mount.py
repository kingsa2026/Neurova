from __future__ import annotations

"""插件声明路由的挂载与摘除——HTTP 面的唯一权限执行点（台账 §6-155，P2）。

P1 把动态装载接通了，并留下一句读数恒 `false` 的诚实声明：**装载与「插件可注册 HTTP 路由」
是两次授权**。本模块就是第二次授权那一道，规则四条，全部在这里判（别处不另判一套）：

1. **聚合权限门**：`声明 ⊆ 已确认` 才挂；声明里有 `execute:commands` / `admin`
   （§6-157 收口后没有"不可授予档"——高危能力可授，但授予后由调用面真拦）。逐项确认在
   `plugin_permissions.py`，档位口径也在那一份里，本模块只**执行**。
2. **命名空间**：插件声明的 `path` 是它自己空间里的**相对路径**，最终形态固定为
   `PLUGIN_ROUTE_PREFIX/{plugin_id}/{path}`。绝对路径、`..`、`?`/`#`、越出该前缀一律拒——
   没有这一条，「装个插件」就等于「在 `/api/v1/*` 上任挑一个位置插 handler」。
3. **认证不放宽**：挂上去的路由一律带 `Depends(get_current_user)`。插件声明
   `auth_required: false` **不被采信**，且这条拒绝要在读数里看得见
   （静默放宽安全面是本仓反复点名的那一类）。
4. **全有或全无**：一条声明里的任何一个端点不合格 ⇒ 整批不挂。审的是「这个插件的这批端点」，
   挂上一半比挂不上更让人误判。

数据流：装载（`PluginManager.load_plugin`）把清单声明连同解析出的 handler 喂进
`PluginAPIRegistry`（唯一存储），挂载侧只从注册器取（唯一消费）——声明与实体绑在一处一次，
不存在「清单一份、路由表另一份」的双源。摘除（显式 unmount / 禁用 / 卸载）从**活 app 的
路由表**按归属取回并 remove，然后回读确认（只 pop 自己的缓存不算摘干净）。

⚠ 这条链今天仍然不构成沙箱：能装载即能在进程内执行任意代码（见
`plugin_permissions` 的三档说明）。本模块给的是**框架面的准入控制与留痕**，不是隔离。
"""

import re
import threading
import typing

from fastapi import Depends

from neurova.core.logger import get_logger
from neurova.plugins import plugin_permissions
from neurova.plugins.plugin_api_registry import get_plugin_api_registry
from neurova.plugins.plugin_errors import PluginError
from neurova.plugins.plugin_permissions import capabilityKeys, frameworkSurfaces, permissionValue
from neurova.security.audit_logger import AuditEventType, AuditSeverity, log_audit

logger = get_logger(__name__)


def getPermissionStore():
    """授予存储经**模块属性**取（同 `api/endpoints/plugin.py` 那一扇的理由）。"""
    return plugin_permissions.getPermissionStore()


#: 插件 HTTP 面的唯一前缀。刻意与管理面 `/api/v1/plugins` 分开：
#: 一眼能看出这条流量是谁的，插件也永远压不到管理面自己身上。
PLUGIN_ROUTE_PREFIX = "/api/v1/plugin-api"

#: 允许的方法闭集。HEAD/OPTIONS/TRACE 不放：前者会被 CORS preflight 与缓存语义放大，
#: 后者在本仓没有对应能力面，放开只是多一条攻击面。
ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE"})

#: 相对路径允许的字符集：不认 `..`、`?`、`#`、`\`、空格与任何 scheme。
_RELATIVE_PATH = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-/{}:.]*$")

_app: typing.Optional[object] = None
_mounted: typing.Dict[str, typing.List[object]] = {}
_declinedAuth: typing.Dict[str, typing.List[str]] = {}
_lock = threading.RLock()


def setPluginApp(app: typing.Optional[object]) -> None:
    """注入运行中的 app（`api/app.py` 的挂载尾步与测试装配点都走这一扇）。"""
    global _app
    with _lock:
        _app = app
        if app is None:
            _mounted.clear()
            _declinedAuth.clear()


def getPluginApp() -> typing.Optional[object]:
    return _app


def _requireApp():
    if _app is None:
        raise PluginError("no_app_context",
                          "没有运行中的 app 可挂（`setPluginApp()` 未被调用）——"
                          "进程内起 HTTP 栈才有这一条路，测试装配或 create_app 都要先注入")
    return _app


def resolveMountedPath(pluginId: str, declaredPath: str) -> str:
    """把清单里的相对路径收成最终全路径；不合规即 `path_out_of_namespace`。

    绝对声明（`/api/v1/...`）**拒**而不是剥掉前导斜杠：剥了就等于替插件改写了它自己
    声明的意图，人审的是清单里那一串，挂上去的却是另一串。命名空间由框架定，不由声明选。
    """
    raw = str(declaredPath or "").strip()
    if raw.startswith("/"):
        raise PluginError(
            "path_out_of_namespace",
            "插件 %s 声明的 path=%r 是绝对路径——只接受 %s/%s/ 下的相对路径，"
            "前缀由框架定（`docs/01-architecture/06-plugin-cli-system.md` 的示例已按此改）"
            % (pluginId, declaredPath, PLUGIN_ROUTE_PREFIX, pluginId))
    text = raw
    if not text or ".." in text or not _RELATIVE_PATH.match(text):
        raise PluginError(
            "path_out_of_namespace",
            "插件 %s 声明的 path=%r 不是 %s/%s/ 下可用的相对路径——插件只能出现在自己的命名空间里"
            % (pluginId, declaredPath, PLUGIN_ROUTE_PREFIX, pluginId))
    full = "%s/%s/%s" % (PLUGIN_ROUTE_PREFIX, pluginId, text)
    # 收完尾斜杠再比，避免 `status/` 与 `status` 各挂一条
    return full.rstrip("/") if full != PLUGIN_ROUTE_PREFIX else full


def _routeOwner(route) -> str:
    """从路由名回读插件归属（`plugin_{id}_{METHOD}_{slug}`）。"""
    name = getattr(route, "name", "") or ""
    if not name.startswith("plugin_"):
        return ""
    parts = name.split("_", 2)
    return parts[1] if len(parts) > 1 else ""


def _pathTaken(app, full: str, method: str, pluginId: str) -> str:
    """全路径冲突判据：活 app 路由表里已有同 path（方法相交）且**不是本插件自己挂的** ⇒ 已被占。
    按 `getattr(route, "path", None)` 取——`_IncludedRouter` 没有 `.path`，
    按名字读会漏判（台账踩坑记录），所以漏掉的条目另行按 404/401 行为面复核。
    """
    for route in getattr(app, "routes", []) or []:
        path = getattr(route, "path", None)
        if path != full:
            continue
        if _routeOwner(route) == pluginId:
            continue
        methods = getattr(route, "methods", None) or set()
        if method in methods or not methods:
            return str(getattr(route, "name", "") or path)
    return ""


def mountPluginRoutes(pluginId: str, actor: str = "") -> typing.Dict[str, typing.Any]:
    """把一个插件声明的全部端点挂进活 app。失败一律 `PluginError`（点名成因）。"""
    app = _requireApp()
    from neurova.plugins.plugin_manager import get_plugin_manager

    manager = get_plugin_manager()
    record = manager.get_plugin(pluginId)
    if record is None:
        raise PluginError("not_installed", "插件未安装：%s" % pluginId)
    if not record.enabled:
        raise PluginError("not_enabled", "插件未启用，谈不上对外开面：%s" % pluginId)
    if not record.loaded:
        raise PluginError("entry_not_loaded",
                          "插件未装载，声明的端点还没有可调用实体：%s" % pluginId)

    store = getPermissionStore()
    _permissionGate(pluginId, manager, store)

    already = mountedPaths(pluginId)
    if already:
        # 幂等重放：门还是过了（撤销的分支见 `reevaluateMount`），不叠第二条同路径路由——
        # 谁接流量取决于遍历顺序，而面板只会显示一条
        return {"mounted": already,
                "auth_escalation_declined": authEscalationDeclined(pluginId),
                "already_mounted": True}

    endpoints = get_plugin_api_registry().get_plugin_endpoints(pluginId)
    if not endpoints:
        raise PluginError("no_declared_endpoints",
                          "插件 %s 的清单没有 api_endpoints 声明，或声明尚未随装载登记进注册器"
                          % pluginId)

    plan = _plan(pluginId, app, endpoints)

    with _lock:
        routes = _addRoutes(app, pluginId, plan, manager)
        declined = [full for ep, full in plan if ep.auth_required is False]
        _declinedAuth[pluginId] = declined
    try:
        store.authorizeMount(pluginId, grantedBy=actor,
                             routes=[full for _ep, full in plan])
    except PluginError:
        # 授权留不下痕就把路由也撤了：读数显示「未授权」而流量真能进来是最坏的双源
        _removeRoutes(app, pluginId)
        raise

    _auditSecurity(actor, "plugin_routes_mounted", pluginId,
                   {"routes": sorted(full for _ep, full in plan),
                    "auth_escalation_declined": sorted(declined)})
    logger.info("Mounted %s plugin route(s) for '%s'", len(plan), pluginId)
    return {"mounted": sorted(full for _ep, full in plan),
            "auth_escalation_declined": sorted(declined)}


def _permissionGate(pluginId, manager, store) -> None:
    """聚合门（§6-157 收口后）：清单必须**显式声明过**能力面，且声明 ⊆ 已确认。

    两条判据各挡一种形态：
    - 整节缺失 ⇒ `permissions_undeclared`。§6-155 只判"声明 ⊆ 已确认"，于是
      `permissions` 写空或干脆不写都**空真通过**——而插件 handler 一旦被请求，
      它拥有的是整个进程的能力。显式空 dict 是合法的（"我什么都不要"），
      没想过这件事不合法。
    - 认不出的声明留在 pending 里（没人能确认它），因此必然挡挂——安全侧。
    """
    if not manager.permissionsDeclared(pluginId):
        raise PluginError(
            "permissions_undeclared",
            "插件 %s 的清单没有 permissions 一节：能力面词汇单点在 "
            "neurova/skills/permissions.py（可用键：%s；框架中介面：%s）。"
            "没声明过就不要对外开 HTTP 面——显式写 permissions: {} 表示「什么都不要」也可以挂"
            % (pluginId, ", ".join(capabilityKeys()), ", ".join(frameworkSurfaces())))

    declared = manager.declaredPermissionsOf(pluginId)
    pending = [value for value in declared if not store.isGranted(pluginId, value)]
    if pending:
        raise PluginError(
            "permissions_unconfirmed",
            "插件 %s 还有未逐项确认的声明：%s（POST /{id}/permissions/{permission}/grant）"
            % (pluginId, ", ".join(sorted(pending))))


def _plan(pluginId, app, endpoints):
    """逐条校形状、归属、handler、冲突——全过才返回（第 4 条：全有或全无）。"""
    plan = []
    for endpoint in endpoints:
        method = endpoint.method.upper()
        if method not in ALLOWED_METHODS:
            raise PluginError("endpoint_method_invalid",
                              "插件 %s 声明了 %s %s；允许的方法：%s"
                              % (pluginId, method, endpoint.path,
                                 ", ".join(sorted(ALLOWED_METHODS))))
        if not callable(endpoint.handler):
            raise PluginError("handler_missing",
                              "插件 %s 的端点 %s 声明 handler=%r，插件类上取不到可调用实体"
                              % (pluginId, endpoint.path, endpoint.handler_name))
        if not isinstance(endpoint.auth_required, bool):
            # 不做强弱转换：`"false"`/`0` 被 bool() 折成 True/False 是拿类型猜安全语义
            raise PluginError("endpoint_auth_invalid",
                              "插件 %s 的端点 %s 的 auth_required=%r 不是布尔"
                              % (pluginId, endpoint.path, endpoint.auth_required))
        full = resolveMountedPath(pluginId, endpoint.path)
        taken = _pathTaken(app, full, method, pluginId)
        if taken:
            raise PluginError("path_conflict",
                              "插件 %s 要挂的 %s %s 已被「%s」占用——不叠第二条同名路径，"
                              "谁接流量取决于遍历顺序" % (pluginId, method, full, taken))
        plan.append((endpoint, full))
    return plan


def _withSkillPermissionScope(pluginId, handler, manager):
    """把插件声明的能力面装进 skills 那份作用域，让调用面仲裁真的生效（§6-157 收口的落点）。

    拦不拦**不由本包判断**：进入 `skill_permission_scope` 后，插件 handler 经框架调工具时，
    `tool_executor._check_skill_declaration` 按 `permissions.py` 那份声明 fail-closed。
    `functools.wraps` 是为了让 FastAPI 仍然按原签名解析参数依赖——不加它，
    路由会看见 `(*args, **kwargs)` 而把插件 handler 的入参全丢掉（假挂载）。
    """
    import functools
    import inspect

    from neurova.skills.permissions import parse_permissions, skill_permission_scope

    declarations = manager.capabilityDeclarations(pluginId)

    @functools.wraps(handler)
    async def _scoped(*args, **kwargs):
        with skill_permission_scope(parse_permissions(declarations)):
            outcome = handler(*args, **kwargs)
            if inspect.isawaitable(outcome):
                outcome = await outcome
            return outcome

    return _scoped


def _addRoutes(app, pluginId, plan, manager=None):
    routes = []
    for endpoint, full in plan:
        handler = endpoint.handler
        if manager is not None:
            handler = _withSkillPermissionScope(pluginId, handler, manager)
        app.add_api_route(
            full,
            handler,
            methods=[endpoint.method],
            name="plugin_%s_%s_%s" % (pluginId, endpoint.method, _slug(full)),
            tags=["plugin", pluginId] + list(endpoint.tags or []),
            description=endpoint.description or "插件 %s 声明的端点" % pluginId,
            # 一律带身份门：`auth_required: false` 不采信，拒绝结果写进 _declinedAuth 供读数
            dependencies=[Depends(_identityGate())],
        )
        created = [r for r in getattr(app, "routes", []) or []
                   if getattr(r, "path", None) == full and _routeOwner(r) == pluginId]
        routes.extend(created[-1:])
    _mounted[pluginId] = routes
    return routes


def _identityGate():
    from neurova.api.auth import get_current_user

    return get_current_user


def _slug(full: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", full).strip("_")


def unmountPluginRoutes(pluginId: str, actor: str = "", note: str = "") -> int:
    """摘除路由并撤销授权。**声明登记（注册器）不在这里清**——unmount ≠ unload，
    重新挂不该要求再装载一次；登记由 `unload_plugin` / `uninstall_plugin` 清。"""
    app = _app
    with _lock:
        removed = _removeRoutes(app, pluginId) if app is not None else 0
        _declinedAuth.pop(pluginId, None)
    if app is not None:
        try:
            getPermissionStore().revokeMount(pluginId, grantedBy=actor)
        except PluginError as exc:
            logger.error("摘除 %s 的路由后撤销授权失败：%s", pluginId, exc)
            raise
    _auditSecurity(actor, "plugin_routes_unmounted", pluginId,
                   {"removed": removed, "note": note})
    return removed


def _removeRoutes(app, pluginId: str) -> int:
    """按**活路由表**摘（不只 pop 自己的缓存），然后回读确认没剩。"""
    if app is None:
        return 0
    table = getattr(app, "routes", [])
    stale = [r for r in list(table) if _routeOwner(r) == pluginId]
    for route in stale:
        try:
            table.remove(route)
        except ValueError:  # pragma: no cover - remove 与回读之间没有并发面
            pass
    remaining = [r for r in table if _routeOwner(r) == pluginId]
    if remaining:
        raise PluginError("routes_still_live",
                          "插件 %s 摘除后活路由表里仍剩 %s 条——HTTP 面并没有真的关掉"
                          % (pluginId, len(remaining)))
    _mounted.pop(pluginId, None)
    return len(stale)


def mountedPaths(pluginId: str) -> typing.List[str]:
    app = _app
    if app is None:
        return []
    return sorted({getattr(r, "path", "") for r in getattr(app, "routes", []) or []
                   if _routeOwner(r) == pluginId})


def authEscalationDeclined(pluginId: str) -> typing.List[str]:
    return sorted(_declinedAuth.get(pluginId, []))


def reevaluateMount(pluginId: str, actor: str = "") -> typing.Dict[str, typing.Any]:
    """撤销一项确认 / 禁用插件之后**立即**复核：门不再过就当场摘除。

    为什么要有这一扇：授权是聚合判据，复核若只发生在「下一次挂载动作」上，
    撤销之后旧路由会一直活着到进程结束——读数说未授权、流量真的还进得来。
    """
    if not mountedPaths(pluginId):
        return {"reevaluated": pluginId, "mounted": False, "action": "nothing_mounted"}
    from neurova.plugins.plugin_manager import get_plugin_manager

    try:
        _permissionGate(pluginId, get_plugin_manager(), getPermissionStore())
    except PluginError as exc:
        removed = unmountPluginRoutes(pluginId, actor=actor, note="复核不过：%s" % exc.reason)
        return {"reevaluated": pluginId, "mounted": False,
                "action": "unmounted", "reason": exc.reason, "removed": removed}
    return {"reevaluated": pluginId, "mounted": True, "action": "still_qualified"}


def mountState(pluginId: str) -> typing.Tuple[bool, str]:
    """(是否真挂在活 app 上, 没挂时点名卡在哪一步)。

    这条读数的存在意义是**不让 `loaded` 被读成「路由已生效」**——P1 之前那副样子是
    翻布尔，P2 之后仍然不能靠推断。
    """
    if _app is None:
        return False, "未接入运行中的 app（进程内没有 HTTP 栈）"
    paths = mountedPaths(pluginId)
    if paths:
        return True, ""
    try:
        authorized = getPermissionStore().mountAuthorized(pluginId)
    except PluginError as exc:
        return False, "授权状态读不出：%s" % exc
    if authorized:
        return False, ("挂载授权在，但活 app 的路由表里没有这些路由"
                       "（进程重启或已被摘除）——重新走 routes/mount")
    return False, ("插件路由需第二次授权：enabled + loaded + 全部声明逐项确认后，"
                   "POST /api/v1/plugins/{id}/routes/mount")


def startupMountPass() -> typing.Dict[str, typing.Any]:
    """重启后把「已授权且仍合格」的插件重新挂上：授权是人的决定，不该每次开机重做一遍。

    今天的实态限制（已登记台账）：安装/启用状态本身不跨重启（P1 留下的缺口——插件根可以重新
    发现，enabled 却是人给的），所以这一遍在新进程里通常无事可做。仍要在启动尾步真接上：
    不接，这条读数就永远是「没挂」，缺口也就永远不会被发现。
    """
    outcome: typing.Dict[str, typing.Any] = {"mounted": [], "refused": {}}
    if _app is None:
        outcome["refused"]["_app"] = "未接入运行中的 app"
        return outcome
    try:
        snapshot = getPermissionStore().snapshot()
    except PluginError as exc:
        outcome["refused"]["_store"] = exc.reason
        return outcome
    for pluginId in sorted(snapshot.get("mounts", {})):
        try:
            mountPluginRoutes(pluginId, actor=snapshot["mounts"][pluginId].get("authorized_by", ""))
            outcome["mounted"].append(pluginId)
        except PluginError as exc:
            outcome["refused"][pluginId] = "%s: %s" % (exc.reason, exc.detail)
            logger.warning("启动重挂插件 %s 失败（%s）——不静默", pluginId, exc.reason)
    return outcome


def resetPluginMounts() -> None:
    """测试/关停用：清掉本模块的缓存（路由表由 app 自己带走）。"""
    global _app
    with _lock:
        _mounted.clear()
        _declinedAuth.clear()
        _app = None


def pluginRouteMountAudit() -> typing.Dict[str, typing.Any]:
    """活 app 里所有插件路由的读数（`scripts/generate_api_inventory.py` 与守卫用它核名实）。"""
    app = _app
    rows = []
    if app is not None:
        for route in getattr(app, "routes", []) or []:
            owner = _routeOwner(route)
            if not owner:
                continue
            rows.append({"plugin": owner, "path": getattr(route, "path", ""),
                         "methods": sorted(getattr(route, "methods", None) or [])})
    return {"count": len(rows), "routes": sorted(rows, key=lambda r: (r["plugin"], r["path"]))}


def _auditSecurity(actor, action, pluginId, details) -> None:
    try:
        ok = log_audit(AuditEventType.SECURITY_EVENT, AuditSeverity.HIGH,
                       user_id=actor or "", action=action, details=details,
                       resource_type="plugin", resource_id=pluginId)
    except Exception as exc:  # noqa: BLE001
        logger.error("插件挂载审计异常（%s）：%s", action, exc)
        ok = False
    if not ok:
        logger.error("插件挂载审计没能落库（%s / %s）——挂载本身已发生，这条必须人工复核",
                     action, pluginId)


__all__ = [
    "PLUGIN_ROUTE_PREFIX",
    "ALLOWED_METHODS",
    "setPluginApp",
    "getPluginApp",
    "mountPluginRoutes",
    "unmountPluginRoutes",
    "reevaluateMount",
    "mountState",
    "mountedPaths",
    "authEscalationDeclined",
    "resolveMountedPath",
    "startupMountPass",
    "resetPluginMounts",
    "pluginRouteMountAudit",
]
