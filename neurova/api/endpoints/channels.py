from __future__ import annotations

"""
渠道管理 API 端点

提供渠道适配器的配置、状态查询、Webhook 回调处理等 API。

路由:
- GET  /api/channels                    - 列出所有渠道状态
- GET  /api/channels/{type}             - 获取指定渠道状态
- POST /api/channels/{type}/connect     - 连接指定渠道
- POST /api/channels/{type}/disconnect  - 断开指定渠道
- POST /api/channels/{type}/send        - 通过指定渠道发送消息
- POST /api/channels/{type}/webhook     - Webhook 回调入口（飞书/钉钉/企微）
- POST /api/channels/{type}/verify      - URL 验证（飞书/企微）
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

from neurova.channels.base import ChannelConfig, ChannelMessage
from neurova.channels.manager import get_channel_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channels", tags=["渠道管理"])

# ============================================================
# 请求/响应模型
# ============================================================

class ChannelStatusResponse(BaseModel):
    """渠道状态响应"""
    channel_type: str
    connected: bool
    enabled: bool = True
    extra: Dict[str, Any] = Field(default_factory=dict)

class ChannelListResponse(BaseModel):
    """渠道列表响应"""
    running: bool
    adapters: Dict[str, ChannelStatusResponse]

class SendMessageRequest(BaseModel):
    """发送消息请求"""
    chat_id: str = Field(..., description="会话 ID")
    content: str = Field(..., description="消息内容")
    message_type: str = Field("text", description="消息类型: text, markdown, image, file")
    extra: Dict[str, Any] = Field(default_factory=dict)

class SendMessageResponse(BaseModel):
    """发送消息响应"""
    success: bool
    message_id: Optional[str] = None
    error: Optional[str] = None

class ConnectRequest(BaseModel):
    """连接渠道请求"""
    app_id: str = Field("", description="应用 ID")
    app_secret: str = Field("", description="应用密钥")
    use_stream: bool = Field(True, description="是否使用 Stream 模式")
    extra: Dict[str, Any] = Field(default_factory=dict)

class WebhookConfigRequest(BaseModel):
    """Webhook 配置请求"""
    webhook_url: str = Field("", description="Webhook 回调 URL")
    token: str = Field("", description="验证 Token")
    encrypt_key: str = Field("", description="加密密钥")

# ============================================================
# 渠道管理
# ============================================================

@router.get("", summary="列出所有渠道状态")
async def list_channels():
    """列出所有已注册的渠道适配器状态"""
    manager = get_channel_manager()
    health = await manager.health_check()
    return health

@router.get("/{channel_type}", summary="获取指定渠道状态")
async def get_channel_status(channel_type: str):
    """获取指定渠道的连接状态"""
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not found")
    return await adapter.health_check()

@router.post("/{channel_type}/connect", summary="连接指定渠道")
async def connect_channel(channel_type: str, request: ConnectRequest):
    """连接指定渠道适配器"""
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not found")

    # 更新配置
    if request.app_id:
        adapter.config.app_id = request.app_id
    if request.app_secret:
        adapter.config.app_secret = request.app_secret
    adapter.config.use_stream = request.use_stream
    adapter.config.extra.update(request.extra)

    success = await adapter.connect()
    return {"success": success, "channel_type": channel_type}

@router.post("/{channel_type}/disconnect", summary="断开指定渠道")
async def disconnect_channel(channel_type: str):
    """断开指定渠道适配器"""
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not found")
    await adapter.disconnect()
    return {"success": True, "channel_type": channel_type}

@router.post("/{channel_type}/send", summary="发送消息")
async def send_message(channel_type: str, request: SendMessageRequest):
    """通过指定渠道发送消息"""
    manager = get_channel_manager()
    msg_id = await manager.send_message(
        channel_type=channel_type,
        chat_id=request.chat_id,
        content=request.content,
        message_type=request.message_type,
        **request.extra,
    )
    return SendMessageResponse(
        success=msg_id is not None,
        message_id=msg_id,
        error=None if msg_id else "Failed to send message",
    )

# ============================================================
# Webhook 回调处理
# ============================================================

@router.post("/{channel_type}/webhook", summary="Webhook 回调入口")
async def handle_webhook(channel_type: str, request: Request):
    """
    处理各平台的 Webhook 回调

    - 飞书: POST JSON，包含 challenge / header / event
    - 钉钉: POST JSON 或 form-data
    - 企业微信: POST XML
    """
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type)
    if not adapter:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not found")

    body = await request.body()
    content_type = request.headers.get("content-type", "")

    try:
        if channel_type == "feishu":
            return await _handle_feishu_webhook(adapter, body, request.query_params)
        elif channel_type == "dingtalk":
            return await _handle_dingtalk_webhook(adapter, body, request.query_params)
        elif channel_type == "wecom":
            return await _handle_wecom_webhook(adapter, body, request.query_params, request)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported webhook for {channel_type}")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Webhook error for {channel_type}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def _handle_feishu_webhook(adapter, body: bytes, query_params) -> dict:
    """处理飞书 Webhook"""
    import json

    data = json.loads(body)

    # URL 验证（challenge）
    if "challenge" in data:
        return {"challenge": data["challenge"]}

    # 消息事件
    event = data.get("event", {})
    msg = event.get("message", {})
    sender = event.get("sender", {})

    content = ""
    msg_type = msg.get("message_type", "text")
    if msg_type == "text":
        try:
            content_json = json.loads(msg.get("content", "{}"))
            content = content_json.get("text", "")
        except json.JSONDecodeError:
            content = msg.get("content", "")

    channel_msg = adapter._make_message(
        message_id=msg.get("message_id", ""),
        sender_id=sender.get("sender_id", {}).get("user_id", ""),
        sender_name=sender.get("sender_id", {}).get("user_id", ""),
        content=content.strip(),
        chat_id=msg.get("chat_id", ""),
        chat_type=msg.get("chat_type", "p2p"),
        message_type=msg_type,
        raw_event=data,
    )

    from neurova.channels.base import ChannelEventType
    await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
    return {"code": 0}

async def _handle_dingtalk_webhook(adapter, body: bytes, query_params) -> dict:
    """处理钉钉 Webhook"""
    import json

    # 钉钉 Webhook 可能是 JSON 或 form-data
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        # form-data 格式
        data = dict(query_params)

    msg_id = data.get("msgId", "")
    sender_id = data.get("senderId", "")
    sender_name = data.get("senderNick", "")
    chat_id = data.get("conversationId", "")
    msg_type = data.get("msgtype", "text")
    conversation_type = data.get("conversationType", "1")

    content = ""
    if msg_type == "text":
        content = data.get("text", {}).get("content", "").strip()

    channel_msg = adapter._make_message(
        message_id=msg_id,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        chat_id=chat_id,
        chat_type="group" if conversation_type == "2" else "p2p",
        message_type=msg_type,
        raw_event=data,
    )

    from neurova.channels.base import ChannelEventType
    await adapter._emit_event(ChannelEventType.MESSAGE_RECEIVED, channel_msg)
    return {"errcode": 0}

async def _handle_wecom_webhook(adapter, body: bytes, query_params, request) -> dict:
    """处理企业微信 Webhook"""
    msg_signature = request.query_params.get("msg_signature", "")
    timestamp = request.query_params.get("timestamp", "")
    nonce = request.query_params.get("nonce", "")
    echostr = request.query_params.get("echostr", "")

    # URL 验证
    if echostr:
        return Response(
            content=adapter.verify_url(msg_signature, timestamp, nonce, echostr),
            media_type="text/plain",
        )

    # 消息回调
    xml_data = body.decode("utf-8")
    reply_xml = adapter.handle_callback(msg_signature, timestamp, nonce, xml_data)

    if reply_xml:
        return Response(content=reply_xml, media_type="application/xml")
    return {"errcode": 0}

# ============================================================
# 健康检查
# ============================================================

@router.get("/health/all", summary="渠道健康检查")
async def health_check_all():
    """检查所有渠道的健康状态"""
    manager = get_channel_manager()
    return await manager.health_check()
