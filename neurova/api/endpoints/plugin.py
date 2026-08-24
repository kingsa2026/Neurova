"""
插件管理 API 端点 - Plugin Management API Endpoints
"""

import datetime
from neurova.core.logger import get_logger
import typing
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = get_logger(__name__)
router = APIRouter()


# ── Models ─────────────────────────────────────────────


class DiscoverPluginsRequest(BaseModel):
    directory: typing.Optional[str] = None
    recursive: bool = True


class InstallPluginRequest(BaseModel):
    source: str  # path or URL
    config: typing.Optional[dict] = None


class PluginConfigUpdateRequest(BaseModel):
    config: dict


# ── In-memory store ────────────────────────────────────

_PLUGINS: typing.Dict[str, dict] = {}
_MARKET_PLUGINS: typing.List[dict] = []  # Reserved for marketplace


def _init_sample_plugins():
    if _PLUGINS:
        return
    samples = [
        {
            "id": "builtin-tools",
            "name": "Builtin Tools",
            "version": "1.0.0",
            "description": "Core builtin tool set",
            "author": "Neurova",
            "status": "enabled",
            "loaded": True,
            "type": "system",
            "config": {},
        },
        {
            "id": "web-scraper",
            "name": "Web Scraper",
            "version": "0.9.0",
            "description": "Web scraping plugin",
            "author": "Community",
            "status": "disabled",
            "loaded": False,
            "type": "custom",
            "config": {"max_depth": 3},
        },
        {
            "id": "data-viz",
            "name": "Data Visualization",
            "version": "1.2.0",
            "description": "Charts and graphs generation",
            "author": "Neurova",
            "status": "enabled",
            "loaded": True,
            "type": "extension",
            "config": {"theme": "default"},
        },
    ]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for p in samples:
        p["created_at"] = now
        p["updated_at"] = now
        _PLUGINS[p["id"]] = p


_init_sample_plugins()


def _get_request_id(request) -> str:
    return getattr(request.state, "request_id", str(uuid.uuid4())[:8])


# ── Endpoints ──────────────────────────────────────────


@router.get("/")
async def list_plugins(
    request,
    status: typing.Optional[str] = None,
    plugin_type: typing.Optional[str] = None,
    page: int = 1,
    size: int = 20,
):
    """获取插件列表"""
    results = list(_PLUGINS.values())
    if status:
        results = [p for p in results if p.get("status") == status]
    if plugin_type:
        results = [p for p in results if p.get("type") == plugin_type]

    total = len(results)
    start = (page - 1) * size
    items = results[start : start + size]
    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.get("/status")
async def get_plugin_status():
    """获取插件管理器状态"""
    total = len(_PLUGINS)
    enabled = sum(1 for p in _PLUGINS.values() if p.get("status") == "enabled")
    loaded = sum(1 for p in _PLUGINS.values() if p.get("loaded"))
    return {
        "code": 0,
        "message": "success",
        "data": {"total": total, "enabled": enabled, "loaded": loaded, "disabled": total - enabled},
    }


@router.get("/market")
async def list_market_plugins(page: int = 1, size: int = 20):
    """[预留] 获取插件市场应用列表"""
    return {
        "code": 0,
        "message": "Plugin marketplace coming soon",
        "data": {"items": _MARKET_PLUGINS, "total": 0, "page": page, "size": size},
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
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    return {"code": 0, "message": "success", "data": plugin}


@router.post("/discover")
async def discover_plugins(body: DiscoverPluginsRequest):
    """扫描目录发现插件"""
    from pathlib import Path

    directory = body.directory or "plugins"
    p = Path(directory)
    discovered = []

    if p.exists() and p.is_dir():
        for manifest in p.rglob("manifest.json") if body.recursive else p.glob("manifest.json"):
            try:
                import json

                data = json.loads(manifest.read_text(encoding="utf-8"))
                discovered.append(
                    {
                        "name": data.get("name", manifest.parent.name),
                        "path": str(manifest.parent),
                        "version": data.get("version", "unknown"),
                        "description": data.get("description", ""),
                    }
                )
            except Exception:
                continue

    return {
        "code": 0,
        "message": f"Discovered {len(discovered)} plugins",
        "data": {"plugins": discovered, "directory": directory},
    }


@router.post("/{plugin_id}/install")
async def install_plugin(plugin_id: str, body: InstallPluginRequest):
    """安装插件"""
    if plugin_id in _PLUGINS:
        plugin = _PLUGINS[plugin_id]
        if plugin.get("status") != "disabled":
            return {"code": 0, "message": "Plugin already installed", "data": plugin}
        plugin["status"] = "disabled"
        plugin["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        return {"code": 0, "message": "Plugin installed", "data": plugin}

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    plugin = {
        "id": plugin_id,
        "name": plugin_id,
        "version": "0.1.0",
        "description": f"Plugin from {body.source}",
        "author": "Unknown",
        "status": "disabled",
        "loaded": False,
        "type": "custom",
        "config": body.config or {},
        "source": body.source,
        "created_at": now,
        "updated_at": now,
    }
    _PLUGINS[plugin_id] = plugin
    logger.info("Plugin installed: %s", plugin_id)
    return {"code": 0, "message": "Plugin installed", "data": plugin}


@router.delete("/{plugin_id}/uninstall")
async def uninstall_plugin(plugin_id: str):
    """卸载插件"""
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    if plugin.get("type") == "system":
        raise HTTPException(status_code=403, detail="Cannot uninstall system plugins")

    if plugin.get("status") == "enabled":
        plugin["status"] = "disabled"
        plugin["loaded"] = False
    del _PLUGINS[plugin_id]
    logger.info("Plugin uninstalled: %s", plugin_id)
    return {"code": 0, "message": "Plugin uninstalled"}


@router.post("/{plugin_id}/load")
async def load_plugin(plugin_id: str):
    """加载插件到模块库"""
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    plugin["loaded"] = True
    plugin["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"code": 0, "message": "Plugin loaded", "data": plugin}


@router.post("/{plugin_id}/unload")
async def unload_plugin(plugin_id: str):
    """从模块库卸载插件（保留安装）"""
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    plugin["loaded"] = False
    plugin["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    return {"code": 0, "message": "Plugin unloaded", "data": plugin}


@router.post("/{plugin_id}/enable")
async def enable_plugin(plugin_id: str):
    """启用插件（加载并启动）"""
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    plugin["status"] = "enabled"
    plugin["loaded"] = True
    plugin["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    logger.info("Plugin enabled: %s", plugin_id)
    return {"code": 0, "message": "Plugin enabled", "data": plugin}


@router.post("/{plugin_id}/disable")
async def disable_plugin(plugin_id: str):
    """禁用插件（停止但保留加载）"""
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    plugin["status"] = "disabled"
    plugin["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    logger.info("Plugin disabled: %s", plugin_id)
    return {"code": 0, "message": "Plugin disabled", "data": plugin}


@router.get("/market/{market_plugin_id}")
async def get_market_plugin_detail(market_plugin_id: str):
    """[预留] 获取插件市场应用详情"""
    return {"code": 0, "message": "Marketplace not yet available", "data": None}


@router.get("/{plugin_id}/modules")
async def get_plugin_modules(plugin_id: str):
    """获取插件模块"""
    plugin = _PLUGINS.get(plugin_id)
    if not plugin:
        raise HTTPException(status_code=404, detail=f"Plugin '{plugin_id}' not found")
    return {
        "code": 0,
        "message": "success",
        "data": {"plugin_id": plugin_id, "modules": [], "loaded": plugin.get("loaded", False)},
    }
