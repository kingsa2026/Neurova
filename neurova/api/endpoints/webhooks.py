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

from neurova.core.logger import get_logger
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容
import json
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

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

_STORE_FILE = "data/webhooks.json"
_MAX_DELIVERIES = 200


def _load_store() -> None:
    """启动时从磁盘重载 webhook 与投递记录（进程内 dict 原为易失态）。"""
    _webhooks.clear()
    _deliveries.clear()
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            _webhooks.update(raw.get("webhooks", {}) or {})
            _deliveries.update(raw.get("deliveries", {}) or {})
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load webhook store: %s", e)


def _save_store() -> None:
    p = pathlib.Path(_STORE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"webhooks": _webhooks, "deliveries": _deliveries}, f, indent=2, ensure_ascii=False)


_load_store()


@router.get("", response_model=List[WebhookInfo])
async def list_webhooks():
    """获取 Webhook 列表"""
    return [WebhookInfo(**w) for w in _webhooks.values()]


@router.post("", response_model=WebhookInfo)
async def create_webhook(body: WebhookCreate):
    """创建 Webhook"""
    wh_id = str(uuid.uuid4())
    now = time.time()
    wh = {
        "webhook_id": wh_id,
        "name": body.name,
        "url": body.url,
        "events": body.events,
        "enabled": True,
        "user_id": "default",
        "created_at": now,
        "updated_at": now,
    }
    _webhooks[wh_id] = wh
    _save_store()
    return WebhookInfo(**wh)


@router.get("/{webhook_id}", response_model=WebhookInfo)
async def get_webhook(webhook_id: str):
    """获取 Webhook 详情"""
    wh = _webhooks.get(webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return WebhookInfo(**wh)


@router.put("/{webhook_id}", response_model=WebhookInfo)
async def update_webhook(webhook_id: str, body: WebhookUpdate):
    """更新 Webhook"""
    wh = _webhooks.get(webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    for k, v in safe_model_dump(body, exclude_none=True).items():  # s9: pydantic v1 兼容
        wh[k] = v
    wh["updated_at"] = time.time()
    _save_store()
    return WebhookInfo(**wh)


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str):
    """删除 Webhook"""
    if webhook_id not in _webhooks:
        raise HTTPException(status_code=404, detail="Webhook not found")
    del _webhooks[webhook_id]
    for did in [d for d, v in _deliveries.items() if v.get("webhook_id") == webhook_id]:
        del _deliveries[did]
    _save_store()
    return {"code": 0, "message": "Webhook deleted"}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, body: WebhookTestRequest):
    """发送测试事件：真实 POST 到 webhook.url，投递结果如实记录（不得谎报 delivered）。"""
    wh = _webhooks.get(webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
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
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                wh["url"],
                json={"event_type": body.event_type, "payload": body.payload},
                headers={"X-Neurova-Webhook": webhook_id},
            )
        delivery["response_code"] = resp.status_code
        delivery["status"] = "delivered" if 200 <= resp.status_code < 300 else "failed"
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
async def list_deliveries(webhook_id: str, limit: int = 50):
    """获取投递记录"""
    items = [d for d in _deliveries.values() if d.get("webhook_id") == webhook_id]
    return [DeliveryInfo(**{k: v for k, v in d.items() if k != "error"}) for d in items[-limit:]]
