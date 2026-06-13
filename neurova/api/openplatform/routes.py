from __future__ import annotations

"""Neurova API 开放平台路由 - 应用管理、Webhook管理、API密钥管理、文档"""

import json
import logging
import secrets
import time
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from fastapi import Path as FPath
from fastapi import Query, Request

from neurova.api.openplatform.events import Event, EventTypes, WebhookDeliveryJob, get_event_system
from neurova.api.openplatform.models import (
    ApiKey,
    ApiKeyCreate,
    ApiScope,
    App,
    AppCreate,
    AppUpdate,
    DeliveryStatus,
    WebhookCreate,
    WebhookEndpoint,
    WebhookEventType,
    WebhookUpdate,
    generate_api_key,
    generate_app_id,
    generate_key_id,
    generate_webhook_id,
    hash_api_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/openplatform", tags=["开放平台"])


# ── 数据文件辅助函数 ──────────────────────────────────────────────
def _data_dir() -> Path:
    d = Path(__file__).parent.parent.parent.parent / "data" / "openplatform"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_data_file(filename: str) -> Dict[str, Any]:
    p = _data_dir() / filename
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text("utf-8"))
    except Exception as e:
        logger.error("Failed to load %s: %s", filename, e)
        return {}


def _save_data_file(filename: str, data: Dict[str, Any]):
    try:
        (_data_dir() / filename).write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")
    except Exception as e:
        logger.error("Failed to save %s: %s", filename, e)
        raise


# ── 认证辅助 ─────────────────────────────────────────────────────
def _get_user_id(request: Request) -> str:
    uid = request.headers.get("X-User-ID")
    if uid:
        return uid
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    raise HTTPException(401, "未提供有效的认证信息")


def _verify_app_owner(app_id: str, user_id: str) -> Dict[str, Any]:
    """验证应用所有权，返回 app dict 或抛出异常"""
    data = _load_data_file("apps.json")
    for app in data.get("apps", []):
        if app.get("app_id") == app_id and app.get("owner_id") == user_id:
            return app
    raise HTTPException(404, "应用不存在或无权访问")


# ── 应用管理 ─────────────────────────────────────────────────────
@router.get("/apps")
async def list_apps(request: Request, page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)):
    uid = _get_user_id(request)
    apps = [a for a in _load_data_file("apps.json").get("apps", []) if a.get("owner_id") == uid]
    start = (page - 1) * page_size
    return {
        "apps": [App.from_dict(a) for a in apps[start : start + page_size]],
        "total": len(apps),
        "page": page,
        "page_size": page_size,
    }


@router.post("/apps", response_model=App)
async def create_app(request: Request, body: AppCreate):
    uid = _get_user_id(request)
    app = App(
        app_id=generate_app_id(),
        app_name=body.app_name,
        app_type=body.app_type,
        description=body.description,
        website=body.website,
        logo_url=body.logo_url,
        redirect_uris=body.redirect_uris,
        scopes=body.scopes,
        owner_id=uid,
        metadata=body.metadata,
    )
    data = _load_data_file("apps.json")
    data.setdefault("apps", []).append(app.to_dict())
    _save_data_file("apps.json", data)
    logger.info("Created app %s for user %s", app.app_id, uid)
    return app


@router.get("/apps/{app_id}", response_model=App)
async def get_app(request: Request, app_id: str = FPath(...)):
    uid = _get_user_id(request)
    return App.from_dict(_verify_app_owner(app_id, uid))


@router.put("/apps/{app_id}", response_model=App)
async def update_app(request: Request, app_id: str = FPath(...), body: AppUpdate = ...):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    data = _load_data_file("apps.json")
    for i, a in enumerate(data.get("apps", [])):
        if a.get("app_id") == app_id:
            for k, v in body.dict(exclude_unset=True).items():
                if v is not None:
                    a[k] = v
            a["updated_at"] = time.time()
            data["apps"][i] = a
            _save_data_file("apps.json", data)
            return App.from_dict(a)
    raise HTTPException(404, "应用不存在")


@router.delete("/apps/{app_id}")
async def delete_app(request: Request, app_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    data = _load_data_file("apps.json")
    apps = data.get("apps", [])
    data["apps"] = [a for a in apps if a.get("app_id") != app_id]
    _save_data_file("apps.json", data)
    return {"message": "应用删除成功"}


# ── Webhook管理 ──────────────────────────────────────────────────
@router.get("/apps/{app_id}/webhooks")
async def list_webhooks(request: Request, app_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    whs = [w for w in _load_data_file("webhooks.json").get("webhooks", []) if w.get("app_id") == app_id]
    return {"webhooks": [WebhookEndpoint.from_dict(w) for w in whs], "total": len(whs)}


@router.post("/apps/{app_id}/webhooks", response_model=WebhookEndpoint)
async def create_webhook(request: Request, app_id: str = FPath(...), body: WebhookCreate = ...):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    wh = WebhookEndpoint(
        webhook_id=generate_webhook_id(),
        app_id=app_id,
        url=body.url,
        events=body.events,
        description=body.description,
        metadata=body.metadata,
    )
    data = _load_data_file("webhooks.json")
    data.setdefault("webhooks", []).append(wh.to_dict())
    _save_data_file("webhooks.json", data)
    get_event_system().register_endpoint(wh)
    return wh


@router.get("/apps/{app_id}/webhooks/{webhook_id}", response_model=WebhookEndpoint)
async def get_webhook(request: Request, app_id: str = FPath(...), webhook_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    for w in _load_data_file("webhooks.json").get("webhooks", []):
        if w.get("webhook_id") == webhook_id and w.get("app_id") == app_id:
            return WebhookEndpoint.from_dict(w)
    raise HTTPException(404, "Webhook不存在")


@router.put("/apps/{app_id}/webhooks/{webhook_id}", response_model=WebhookEndpoint)
async def update_webhook(
    request: Request, app_id: str = FPath(...), webhook_id: str = FPath(...), body: WebhookUpdate = ...
):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    data = _load_data_file("webhooks.json")
    for i, w in enumerate(data.get("webhooks", [])):
        if w.get("webhook_id") == webhook_id and w.get("app_id") == app_id:
            for k, v in body.dict(exclude_unset=True).items():
                if v is not None:
                    w[k] = v
            w["updated_at"] = time.time()
            data["webhooks"][i] = w
            _save_data_file("webhooks.json", data)
            return WebhookEndpoint.from_dict(w)
    raise HTTPException(404, "Webhook不存在")


@router.delete("/apps/{app_id}/webhooks/{webhook_id}")
async def delete_webhook(request: Request, app_id: str = FPath(...), webhook_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    data = _load_data_file("webhooks.json")
    whs = data.get("webhooks", [])
    data["webhooks"] = [w for w in whs if not (w.get("webhook_id") == webhook_id and w.get("app_id") == app_id)]
    _save_data_file("webhooks.json", data)
    get_event_system().unregister_endpoint(webhook_id)
    return {"message": "Webhook删除成功"}


@router.get("/apps/{app_id}/webhooks/{webhook_id}/deliveries")
async def list_webhook_deliveries(
    request: Request,
    app_id: str = FPath(...),
    webhook_id: str = FPath(...),
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    ds = DeliveryStatus(status) if status else None
    deliveries = get_event_system().list_deliveries(webhook_id, ds, limit)
    return {"deliveries": [d.to_dict() for d in deliveries], "total": len(deliveries)}


@router.post("/apps/{app_id}/webhooks/{webhook_id}/test")
async def test_webhook(request: Request, app_id: str = FPath(...), webhook_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    endpoint = get_event_system().get_endpoint(webhook_id)
    if endpoint is None:
        raise HTTPException(404, "Webhook不存在")
    test_event = Event(
        event_id=f"test_{secrets.token_hex(8)}",
        event_type=EventTypes.CUSTOM,
        payload={"test": True, "message": "这是一条测试事件", "timestamp": time.time()},
        source="test",
    )
    job = WebhookDeliveryJob(test_event, endpoint)
    delivery = await job.execute()
    return {
        "message": "测试事件发送完成",
        "delivery_id": delivery.delivery_id,
        "status": delivery.status.value,
        "response_status": delivery.response_status,
        "error_message": delivery.error_message,
    }


# ── API密钥管理 ──────────────────────────────────────────────────
@router.get("/apps/{app_id}/keys")
async def list_keys(request: Request, app_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    keys = [k for k in _load_data_file("api_keys.json").get("keys", []) if k.get("app_id") == app_id]
    return {"keys": keys, "total": len(keys)}


@router.post("/apps/{app_id}/keys")
async def create_key(request: Request, app_id: str = FPath(...), body: ApiKeyCreate = ...):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    api_key = generate_api_key()
    kid = generate_key_id()
    expires_at = time.time() + body.expires_in if body.expires_in else None
    obj = ApiKey(
        key_id=kid,
        key_hash=hash_api_key(api_key),
        app_id=app_id,
        name=body.name,
        scopes=body.scopes,
        expires_at=expires_at,
        rate_limit=body.rate_limit,
        metadata=body.metadata,
    )
    data = _load_data_file("api_keys.json")
    data.setdefault("keys", []).append(obj.to_dict())
    _save_data_file("api_keys.json", data)
    return {
        "key_id": kid,
        "api_key": api_key,
        "name": body.name,
        "scopes": [s.value for s in body.scopes],
        "expires_at": expires_at,
        "created_at": obj.created_at,
    }


@router.delete("/apps/{app_id}/keys/{key_id}")
async def revoke_key(request: Request, app_id: str = FPath(...), key_id: str = FPath(...)):
    uid = _get_user_id(request)
    _verify_app_owner(app_id, uid)
    data = _load_data_file("api_keys.json")
    found = False
    for k in data.get("keys", []):
        if k.get("key_id") == key_id and k.get("app_id") == app_id:
            k["is_active"] = False
            k["revoked_at"] = time.time()
            found = True
            break
    if not found:
        raise HTTPException(404, "API密钥不存在")
    _save_data_file("api_keys.json", data)
    return {"message": "API密钥撤销成功"}


# ── 开发者文档 ───────────────────────────────────────────────────
@router.get("/docs")
async def get_docs_index():
    return {
        "title": "Neurova 开放平台 API 文档",
        "version": "1.0.0",
        "description": "Neurova 开放平台API，用于第三方应用集成。",
        "sections": [
            {
                "title": "应用管理",
                "endpoints": [
                    {"method": "GET", "path": "/openplatform/apps"},
                    {"method": "POST", "path": "/openplatform/apps"},
                    {"method": "GET", "path": "/openplatform/apps/{app_id}"},
                    {"method": "PUT", "path": "/openplatform/apps/{app_id}"},
                    {"method": "DELETE", "path": "/openplatform/apps/{app_id}"},
                ],
            },
            {
                "title": "Webhook管理",
                "endpoints": [
                    {"method": "GET", "path": "/openplatform/apps/{app_id}/webhooks"},
                    {"method": "POST", "path": "/openplatform/apps/{app_id}/webhooks"},
                    {"method": "POST", "path": "/openplatform/apps/{app_id}/webhooks/{webhook_id}/test"},
                    {"method": "DELETE", "path": "/openplatform/apps/{app_id}/webhooks/{webhook_id}"},
                ],
            },
            {
                "title": "API密钥管理",
                "endpoints": [
                    {"method": "POST", "path": "/openplatform/apps/{app_id}/keys"},
                    {"method": "DELETE", "path": "/openplatform/apps/{app_id}/keys/{key_id}"},
                ],
            },
        ],
    }


@router.get("/events")
async def get_events_list():
    return {"events": [{"value": e.value, "name": e.name} for e in WebhookEventType]}


@router.get("/scopes")
async def get_scopes_list():
    scopes = []
    for s in ApiScope:
        scopes.append({"value": s.value, "name": s.name, "description": _get_scope_description(s)})
    return {"scopes": scopes}


def _get_scope_description(scope: ApiScope) -> str:
    _map = {
        ApiScope.USER_READ: "读取用户信息",
        ApiScope.USER_WRITE: "修改用户信息",
        ApiScope.USER_ADMIN: "用户管理",
        ApiScope.AGENT_READ: "读取Agent信息",
        ApiScope.AGENT_WRITE: "修改Agent配置",
        ApiScope.AGENT_ADMIN: "Agent管理",
        ApiScope.MEMORY_READ: "读取记忆",
        ApiScope.MEMORY_WRITE: "写入记忆",
        ApiScope.MEMORY_ADMIN: "记忆管理",
        ApiScope.TOOL_READ: "读取工具信息",
        ApiScope.TOOL_WRITE: "修改工具配置",
        ApiScope.TOOL_ADMIN: "工具管理",
        ApiScope.WEBHOOK_READ: "读取Webhook",
        ApiScope.WEBHOOK_WRITE: "修改Webhook",
        ApiScope.WEBHOOK_ADMIN: "Webhook管理",
        ApiScope.API_KEY_READ: "读取API密钥",
        ApiScope.API_KEY_WRITE: "修改API密钥",
        ApiScope.API_KEY_ADMIN: "API密钥管理",
        ApiScope.SYSTEM_READ: "读取系统信息",
        ApiScope.SYSTEM_WRITE: "修改系统配置",
        ApiScope.SYSTEM_ADMIN: "系统管理",
        ApiScope.ANALYTICS_READ: "读取分析数据",
        ApiScope.ANALYTICS_WRITE: "写入分析数据",
        ApiScope.ALL: "全部权限",
    }
    return _map.get(scope, "")


@router.get("/stats")
async def get_stats(request: Request):
    uid = _get_user_id(request)
    apps = [a for a in _load_data_file("apps.json").get("apps", []) if a.get("owner_id") == uid]
    app_ids = {a["app_id"] for a in apps}
    keys = [k for k in _load_data_file("api_keys.json").get("keys", []) if k.get("app_id") in app_ids]
    whs = [w for w in _load_data_file("webhooks.json").get("webhooks", []) if w.get("app_id") in app_ids]
    return {
        "user_id": uid,
        "total_apps": len(apps),
        "active_apps": sum(1 for a in apps if a.get("is_active")),
        "total_api_keys": len(keys),
        "active_api_keys": sum(1 for k in keys if k.get("is_active")),
        "total_webhooks": len(whs),
        "active_webhooks": sum(1 for w in whs if w.get("is_active")),
        "event_system": get_event_system().get_stats(),
    }
