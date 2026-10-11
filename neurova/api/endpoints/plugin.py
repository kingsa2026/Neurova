"""
插件管理 API 端点 - Plugin Management API Endpoints

实况（用户 2026-10-11 改裁「做插件体系并接线」，台账 §6-150；此前 `e95d3a76` 的退役已按裁定回滚）：
本模块是 `PluginManager` 的 HTTP 门面，**不再有第二份进程内账本**——原先那份
`_PLUGINS: dict` 让 install/load/enable 只翻布尔、`/{id}/modules` 恒回空列表，
读数看起来"插件生效了"而从未 import 过任何插件代码。教义第 6 条不允许同一个事实有两处定义，
所以列表、状态、模块面一律读 `get_plugin_manager()`。

P1 接通的是**装载**，边界写死在这里：

- 装载源必须在**插件根**（数据根下的 `plugins/`）内。请求方能指定的只有"根里哪个目录"，
  不能指定任意磁盘路径——那等于开放任意代码执行（`PluginManager.resolveInstallSource`）。
- 远程下载/安装（`https://…`）**未实装**，直接 501 点名，不再像原实现那样落进一条
  不可达分支后假装失败。供应链校验（源、哈希/签名、权限确认、回滚）属后续批次。
- 插件在 manifest 里声明的 API 端点**不挂进运行中的 app**：`routes_mounted` 恒为
  `false` 并带成因。装载与"插件可注册路由"是两次授权，后者要 P2 的权限门与审计先把。

`plugin_id` 就是 manifest 里的 `name`（`PluginManager` 的键）；两者不一致时报 400 而不是静默改名。
"""

import typing

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.plugins.plugin_manager import PluginError, PluginManager, get_plugin_manager

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)],)

#: 拒因 → HTTP 语义的单点映射。`reason` 是 `PluginError` 的封闭集合；
#: 新增成因必须在这里补一行，否则端点会把它画成 500（漏映射比错映射更难发现，故当场红）。
_REASON_TO_STATUS = {
    "remote_source": 501,          # 未实装（供应链控制属后续批次）——响亮地说，不静默
    "outside_root": 400,           # 装载边界：源不在插件根内
    "not_a_directory": 400,
    "no_manifest": 400,
    "empty_source": 400,
    "unmet_dependencies": 409,
    "not_installed": 404,
    "not_enabled": 409,            # 未启用就装载：约束在 manager，端点不替它兜底
    "entry_not_loaded": 500,       # 插件自身缺陷（入口缺失/执行报错）
    "no_plugin_class": 500,
    "instantiate_failed": 500,
}


def _statusFor(exc: PluginError) -> int:
    reason = exc.reason
    if reason in _REASON_TO_STATUS:
        return _REASON_TO_STATUS[reason]
    logger.warning("未登记的插件拒因 %r 被画成 500——去 _REASON_TO_STATUS 补一行", reason)
    return 500


# ── Models ─────────────────────────────────────────────


class DiscoverPluginsRequest(BaseModel):
    directory: typing.Optional[str] = None
    recursive: bool = True


class InstallPluginRequest(BaseModel):
    source: str  # 必须是插件根内的目录；远程 URL 回 501
    config: typing.Optional[dict] = None


class PluginConfigUpdateRequest(BaseModel):
    config: dict


def _pluginView(name: str) -> dict:
    """把一个插件拼成端点读数（唯一形态，供列表/详情/状态复用）。

    `status` 由 `enabled` 派生而不是另存一份布尔——原实现两处各写各的，
    `enabled` 与 `status` 会分叉。
    """
    manager = get_plugin_manager()
    record = manager.get_plugin(name)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Plugin '{name}' not found")

    view = record.to_dict()
    view["id"] = record.name
    view["status"] = "enabled" if record.enabled else "disabled"
    raw = manager.manifestDict(name)
    view["type"] = raw.get("plugin_type", "custom")
    mounted, reason = PluginManager.routesMounted()
    view["routes_mounted"] = mounted
    view["routes_reason"] = reason
    view["declared_endpoints"] = manager.declaredEndpoints(name)
    return view


def _manifestName(manager, path) -> str:
    """装哪个插件由 manifest 里的 `name` 定——它是 manager 的键，不是请求方能编的。"""
    raw = manager.readManifestAt(path) or {}
    return raw.get("name", path.name)


# ── Endpoints ──────────────────────────────────────────


@router.get("/")
async def list_plugins(
    request: Request,  # 残留处理 2026-09-13 真 bug：request 无标注曾被 FastAPI
    # 当作必填 query 参数 → GET /plugins/ 实测 422（插件列表页接口面失效面）
    status: typing.Optional[str] = None,
    plugin_type: typing.Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """获取插件列表（读 manager 的真实状态，不是进程内账本）。"""
    manager = get_plugin_manager()
    results = [_pluginView(record.name) for record in manager.list_plugins()]
    if status:
        results = [p for p in results if p.get("status") == status]
    if plugin_type:
        results = [p for p in results if p.get("type") == plugin_type]

    total = len(results)
    start = (page - 1) * size
    items = results[start : start + size]
    return {"code": 0, "message": "success",
            "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/status")
async def get_plugin_status():
    """获取插件管理器状态"""
    manager = get_plugin_manager()
    total = len(manager.list_plugins())
    enabled = sum(1 for r in manager.list_plugins() if r.enabled)
    loaded = sum(1 for r in manager.list_plugins() if r.loaded)
    return {
        "code": 0,
        "message": "success",
        "data": {"total": total, "enabled": enabled, "loaded": loaded,
                 "disabled": total - enabled},
    }


@router.get("/market")
async def list_market_plugins(page: int = 1, size: int = 20):
    """[预留] 获取插件市场应用列表"""
    return {
        "code": 0,
        "message": "Plugin marketplace coming soon",
        "data": {"items": [], "total": 0, "page": page, "size": size},
    }


@router.post("/market/submit")
async def submit_plugin_to_market(body: dict):
    """[预留] 用户插件提交入口"""
    return {"code": 0, "message": "Plugin submission not yet available", "data": None}


@router.post("/market/install")
async def install_from_market(body: dict):
    """[预留] 插件市场下载安装"""
    return {"code": 0, "message": "Marketplace install not yet available", "data": None}


@router.get("/{plugin_id}")
async def get_plugin(plugin_id: str):
    """获取插件详情"""
    return {"code": 0, "message": "success", "data": _pluginView(plugin_id)}


@router.post("/discover")
async def discover_plugins(body: DiscoverPluginsRequest):
    """扫描插件根，列出带 manifest 的目录（不安装）。

    `directory` 只用来筛选根内子目录名；给根外路径一律 400——扫描面本身不该成为
    "让服务端去读任意目录"的入口。
    """
    from pathlib import Path

    manager = get_plugin_manager()
    root = Path(manager.plugin_dir).resolve()
    directory = (body.directory or "").strip()
    target = root
    if directory:
        candidate = Path(directory).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=400,
                                detail="扫描目录必须在插件根 %s 内" % root)
        target = candidate

    discovered = []
    for record in manager.discover_plugins():
        if Path(record.path).resolve().is_relative_to(target):
            discovered.append({"name": record.name, "path": record.path,
                               "version": record.version, "description": record.description})
    return {
        "code": 0,
        "message": f"Discovered {len(discovered)} plugins",
        "data": {"plugins": discovered, "directory": str(target)},
    }


@router.post("/{plugin_id}/install")
async def install_plugin(plugin_id: str, body: InstallPluginRequest):
    """把插件根内的一个目录登记为已安装。

    失败按成因映射 HTTP（见 `_REASON_TO_STATUS`），不再一律"code:0 + 消息"或一律 False。
    """
    manager = get_plugin_manager()
    try:
        source = manager.resolveInstallSource(body.source)
    except PluginError as e:
        raise HTTPException(status_code=_statusFor(e), detail=str(e))

    name = _manifestName(manager, source)
    if name != plugin_id:
        raise HTTPException(
            status_code=400,
            detail="路径里的插件名 %r 与 manifest 声明的 name=%r 不一致——"
                   "静默改名会让后续 load/uninstall 打在另一个键上" % (plugin_id, name))

    try:
        manager.install_plugin(source)
    except PluginError as e:
        raise HTTPException(status_code=_statusFor(e), detail=str(e))

    logger.info("Plugin installed: %s", plugin_id)
    return {"code": 0, "message": "Plugin installed", "data": _pluginView(plugin_id)}


@router.delete("/{plugin_id}/uninstall")
async def uninstall_plugin(plugin_id: str):
    """忘掉这个插件的记录（**不删磁盘文件**——销毁用户文件要另一次授权）。"""
    manager = get_plugin_manager()
    if not manager.has_plugin(plugin_id):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    manager.uninstall_plugin(plugin_id)
    logger.info("Plugin uninstalled: %s", plugin_id)
    return {"code": 0, "message": "Plugin uninstalled",
            "data": {"removed_record": plugin_id, "files_kept": True}}


@router.post("/{plugin_id}/load")
async def load_plugin(plugin_id: str):
    """真动态装载：import 并 exec 插件入口文件，构造插件实例。"""
    manager = get_plugin_manager()
    try:
        manager.load_plugin(plugin_id)
    except PluginError as e:
        raise HTTPException(status_code=_statusFor(e), detail=str(e))

    return {"code": 0, "message": "Plugin loaded", "data": _pluginView(plugin_id)}


@router.post("/{plugin_id}/unload")
async def unload_plugin(plugin_id: str):
    """卸载（保留安装记录），并把 `sys.modules` 里那条一起摘掉。"""
    manager = get_plugin_manager()
    if not manager.has_plugin(plugin_id):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    manager.unload_plugin(plugin_id)
    return {"code": 0, "message": "Plugin unloaded", "data": _pluginView(plugin_id)}


@router.post("/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    """启用插件（装载的前置门；启用本身不执行插件代码）"""
    manager = get_plugin_manager()
    if not manager.has_plugin(plugin_id):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    if not manager.enable_plugin(plugin_id):
        raise HTTPException(status_code=409,
                            detail="启用失败：插件 %s 的依赖不满足（详见服务端日志）" % plugin_id)

    logger.info("Plugin enabled: %s", plugin_id)
    return {"code": 0, "message": "Plugin enabled", "data": _pluginView(plugin_id)}


@router.post("/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    """禁用插件（有其它插件依赖它时拒绝，不静默断开）"""
    manager = get_plugin_manager()
    if not manager.has_plugin(plugin_id):
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")

    if not manager.disable_plugin(plugin_id):
        dependents = manager.dependentsOf(plugin_id)
        raise HTTPException(status_code=409,
                            detail="插件 %s 被这些插件依赖，不能禁用：%s" % (plugin_id, dependents))

    logger.info("Plugin disabled: %s", plugin_id)
    return {"code": 0, "message": "Plugin disabled", "data": _pluginView(plugin_id)}


@router.get("/market/{market_plugin_id}")
async def get_market_plugin_detail(market_plugin_id: str):
    """[预留] 获取插件市场应用详情"""
    return {"code": 0, "message": "Marketplace not yet available", "data": None}


@router.get("/{plugin_id}/modules")
async def get_plugin_modules(plugin_id: str):
    """模块面：真装载后给出模块名与插件类名，并**如实声明路由未挂载**。

    `modules` 在 P1 之前恒回空列表；那不是一个"暂时没数据"，而是一条会让人
    误判插件已生效的读数（台账 §6-150）。
    """
    manager = get_plugin_manager()
    view = _pluginView(plugin_id)
    info = manager.moduleInfo(plugin_id)

    modules = []
    if info:
        module = info.get("module")
        plugin_class = info.get("class")
        modules.append({
            "module_name": getattr(module, "__name__", None),
            "file": getattr(module, "__file__", None),
            "class_name": getattr(plugin_class, "__name__", None),
        })

    return {
        "code": 0,
        "message": "success",
        "data": {
            "plugin_id": plugin_id,
            "modules": modules,
            "loaded": view["loaded"],
            "routes_mounted": view["routes_mounted"],
            "routes_reason": view["routes_reason"],
            "declared_endpoints": view["declared_endpoints"],
        },
    }
