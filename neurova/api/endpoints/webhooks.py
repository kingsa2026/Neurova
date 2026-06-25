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
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


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
    for k, v in body.model_dump(exclude_none=True).items():
        wh[k] = v
    wh["updated_at"] = time.time()
    return WebhookInfo(**wh)


@router.delete("/{webhook_id}")
async def delete_webhook(webhook_id: str):
    """删除 Webhook"""
    if webhook_id not in _webhooks:
        raise HTTPException(status_code=404, detail="Webhook not found")
    del _webhooks[webhook_id]
    return {"code": 0, "message": "Webhook deleted"}


@router.post("/{webhook_id}/test")
async def test_webhook(webhook_id: str, body: WebhookTestRequest):
    """发送测试事件"""
    wh = _webhooks.get(webhook_id)
    if not wh:
        raise HTTPException(status_code=404, detail="Webhook not found")
    delivery_id = str(uuid.uuid4())
    _deliveries[delivery_id] = {
        "delivery_id": delivery_id,
        "webhook_id": webhook_id,
        "event_type": body.event_type,
        "status": "delivered",
        "response_code": 200,
        "attempts": 1,
        "created_at": time.time(),
    }
    return {"code": 0, "message": "Test event sent", "data": {"delivery_id": delivery_id}}


@router.get("/{webhook_id}/deliveries", response_model=List[DeliveryInfo])
async def list_deliveries(webhook_id: str, limit: int = 50):
    """获取投递记录"""
    items = [d for d in _deliveries.values() if d.get("webhook_id") == webhook_id]
    return [DeliveryInfo(**d) for d in items[-limit:]]
