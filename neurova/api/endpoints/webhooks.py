"""
Webhook 管理 API

提供以下端点:
- GET    /v1/webhooks                           获取 Webhook 列表
- POST   /v1/webhooks                           创建 Webhook
- GET    /v1/webhooks/{webhook_id}              获取详情
- PUT    /v1/webhooks/{webhook_id}              更新
- DELETE /v1/webhooks/{webhook_id}              删除
- POST   /v1/webhooks/{webhook_id}/test         测试
- GET    /v1/webhooks/{webhook_id}/deliveries   投递记录
"""

from neurova.core.atomic_io import loadJsonStore, saveJsonStore
from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import asyncio
import json
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field
from neurova.core.data_root import dataPath
# P1-5（审计 2026-11-16）：SSRF 防护收口到知识域唯一 URL 校验单源——
# webhook.url 由请求任意指定，test 端点会向它发起服务端 POST，不过闸即
# 内网探测预言机（169.254.169.254、localhost 等，响应码回显可作预言）。
from neurova.security.url_guard import validate_public_http_url

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)],)


class WebhookInfo(BaseModel):
    webhook_id: str
    name: str
    url: str
    events: List[str] = []
    enabled: bool = True
    user_id: str = ""
    created_at: float = 0
    updated_at: float = 0


class WebhookCreate(BaseModel):
    name: str = Field(..., description="Webhook 名称")
    url: str = Field(..., description="回调 URL")
    events: List[str] = Field(default_factory=list, description="订阅事件列表")
    secret: Optional[str] = Field(default=None, description="签名密钥")


class WebhookUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    events: Optional[List[str]] = None
    enabled: Optional[bool] = None


class WebhookTestRequest(BaseModel):
    event_type: str = Field(default="test")
    payload: Dict[str, Any] = Field(default_factory=dict)


class DeliveryInfo(BaseModel):
    delivery_id: str
    webhook_id: str
    event_type: str
    status: str = "pending"
    response_code: Optional[int] = None
    attempts: int = 0
    created_at: float = 0


_webhooks: Dict[str, Dict[str, Any]] = {}
_deliveries: Dict[str, Dict[str, Any]] = {}

_STORE_FILE = dataPath("webhooks.json")
_MAX_DELIVERIES = 200


def _load_store() -> None:
    """启动时从磁盘重载 webhook 与投递记录（进程内 dict 原为易失态）。"""
    _webhooks.clear()
    _deliveries.clear()
    raw = loadJsonStore(_STORE_FILE, {})
    _webhooks.update(raw.get("webhooks", {}) or {})
    _deliveries.update(raw.get("deliveries", {}) or {})


def _save_store() -> None:
    saveJsonStore(_STORE_FILE, {"webhooks": _webhooks, "deliveries": _deliveries})


_load_store()


def _ensurePublicUrl(url: str) -> None:
    """三处入口（create/update/test）共用的出网 URL 闸；不合规显式 400。"""
    if not validate_public_http_url(url or ""):
        raise HTTPException(status_code=400, detail="Webhook URL 不合规：仅允许公网 http/https 地址")


def _canManage(wh: Dict[str, Any], current_user: Dict[str, Any]) -> bool:
    """属主栅栏：admin 全量；属主本人放行。

    存量无主行（user_id 空或历史硬编码的 "default"）按 2026-11-18
    「空属主判给管理员」裁定只归 admin。webhook 是配置面 REST，属主取
    请求身份字典的 user_id（§3 身份通道 ContextVar 在这些路由无写点）。
    """
    if str(current_user.get("role") or "user") == "admin":
        return True
    owner = str(wh.get("user_id") or "")
    if owner in ("", "default"):
        return False
    return owner == str(current_user.get("user_id") or "")


def _ownedWebhookOr404(webhook_id: str, current_user: Dict[str, Any]) -> Dict[str, Any]:
    """取行 + 属主判一起做；不存在或不属当前用户一律 404（不泄露存在性）。"""
    wh = _webhooks.get(webhook_id)
    if not wh or not _canManage(wh, current_user):
        raise HTTPException(status_code=404, detail="Webhook not found")
    return wh


@router.get("", response_model=List[WebhookInfo])
async def list_webhooks(current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取 Webhook 列表（仅本人；admin 全量）"""
    return [WebhookInfo(**w) for w in _webhooks.values() if _canManage(w, current_user)]


@router.post("", response_model=WebhookInfo)
async def create_webhook(body: WebhookCreate, current_user: Dict[str, Any] = Depends(get_current_user)):
    """创建 Webhook（属主=发起者本人）"""
    _ensurePublicUrl(body.url)
    wh_id = str(uuid.uuid4())
    now = time.time()
    wh = {
        "webhook_id": wh_id,
        "name": body.name,
        "url": body.url,
        "events": body.events,
        "enabled": True,
        "user_id": str(current_user.get("user_id") or ""),
        "created_at": now,
        "updated_at": now,
    }
    _webhooks[wh_id] = wh
    _save_store()
    return WebhookInfo(**wh)


@router.get("/{webhook_id}", response_model=WebhookInfo)
async def get_webhook(webhook_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取 Webhook 详情（属主或 admin）"""
    wh = _ownedWebhookOr404(webhook_id, current_user)
    return WebhookInfo(**wh)


@router.put("/{webhook_id}", response_model=WebhookInfo)
async def update_webhook(webhook_id: str, body: WebhookUpdate,
                         current_user: Dict[str, Any] = Depends(get_current_user)):
    """更新 Webhook（属主或 admin）"""
    wh = _ownedWebhookOr404(webhook_id, current_user)
    updates = safe_model_dump(body, exclude_none=True)  # s9: pydantic v1 兼容
    if "url" in updates:
        _ensurePublicUrl(updates["url"])
    for k, v in updates.items():
        wh[k] = v
    wh["updated_at"] = time.time()
    _save_store()
    return WebhookInfo(**wh)


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """删除 Webhook（属主或 admin）"""
    _ownedWebhookOr404(webhook_id, current_user)
    del _webhooks[webhook_id]
    for did in [d for d, v in _deliveries.items() if v.get("webhook_id") == webhook_id]:
        del _deliveries[did]
    _save_store()
    return {"code": 0, "message": "Webhook deleted"}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, body: WebhookTestRequest,
                       current_user: Dict[str, Any] = Depends(get_current_user)):
    """发送测试事件：真实 POST 到 webhook.url，投递结果如实记录（不得谎报 delivered）。

    属主或 admin 才可触发——本端点会向 webhook.url 发起服务端 POST，
    不设属主门等于开放"借服务器外送"面。
    """
    wh = _ownedWebhookOr404(webhook_id, current_user)
    # P1-5：存量行（闸上线前入库）在发起服务端 POST 前同样复核
    _ensurePublicUrl(wh.get("url") or "")
    delivery_id = str(uuid.uuid4())
    delivery = {
        "delivery_id": delivery_id,
        "webhook_id": webhook_id,
        "event_type": body.event_type,
        "status": "failed",
        "response_code": None,
        "attempts": 1,
        "created_at": time.time(),
    }
    try:
        from neurova.security import safe_fetch

        response = await asyncio.to_thread(
            safe_fetch.safe_fetch,
            wh["url"],
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-Neurova-Webhook": webhook_id,
            },
            data=json.dumps(
                {"event_type": body.event_type, "payload": body.payload},
                ensure_ascii=False,
            ).encode("utf-8"),
            timeout=10,
        )
        delivery["response_code"] = response.status
        delivery["status"] = "delivered" if 200 <= response.status < 300 else "failed"
    except safe_fetch.HTTPStatusError as e:
        delivery["response_code"] = e.status
        delivery["error"] = str(e)[:200]
        logger.warning("Webhook test to %s failed: %s", wh.get("url"), e)
    except Exception as e:  # noqa: BLE001
        delivery["error"] = str(e)[:200]
        logger.warning("Webhook test to %s failed: %s", wh.get("url"), e)
    _deliveries[delivery_id] = delivery
    if len(_deliveries) > _MAX_DELIVERIES:
        for stale in sorted(_deliveries, key=lambda k: _deliveries[k]["created_at"])[: len(_deliveries) - _MAX_DELIVERIES]:
            del _deliveries[stale]
    _save_store()
    return {
        "code": 0,
        "message": "Test delivered" if delivery["status"] == "delivered" else "Test failed",
        "data": {"delivery_id": delivery_id, "status": delivery["status"], "response_code": delivery["response_code"]},
    }


@router.get("/{webhook_id}/deliveries", response_model=List[DeliveryInfo])
async def list_deliveries(webhook_id: str, limit: int = 50,
                          current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取投递记录（随 webhook 属主门）"""
    _ownedWebhookOr404(webhook_id, current_user)
    items = [d for d in _deliveries.values() if d.get("webhook_id") == webhook_id]
    return [DeliveryInfo(**{k: v for k, v in d.items() if k != "error"}) for d in items[-limit:]]
