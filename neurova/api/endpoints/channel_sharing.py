"""
渠道上下文共享配置 API

功能:
1. 获取共享配置 (GET /api/v1/channel-sharing)
2. 设置全局开关 (POST /api/v1/channel-sharing/enable)
3. 禁用全局开关 (POST /api/v1/channel-sharing/disable)
4. 设置共享渠道列表 (POST /api/v1/channel-sharing/channels)
5. 获取可用渠道列表 (GET /api/v1/channel-sharing/available-channels)
6. 测试共享配置 (POST /api/v1/channel-sharing/test)
7. 获取共享状态 (GET /api/v1/channel-sharing/status)
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class SetChannelsRequest(BaseModel):
    """设置共享渠道列表请求"""

    channels: List[str] = Field(..., description="参与上下文共享的渠道列表")
    shared_context: bool = Field(default=True, description="是否启用上下文共享")


class TestSharingRequest(BaseModel):
    """测试共享配置请求"""

    channel: str = Field(..., description="要测试的渠道类型")


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_sharing_config: Dict[str, Any] = {
    "enabled": True,
    "shared_channels": ["web", "mobile", "api"],
    "default_context": "user_profile",
    "auto_sync": True,
    "sync_interval": 300,
    "created_at": time.time(),
    "updated_at": time.time(),
}

_channel_sharing_status: Dict[str, Dict[str, Any]] = {}

# Available channels from MessageChannel enum
_AVAILABLE_CHANNELS = [
    "wechat",
    "feishu",
    "dingtalk",
    "wecom",
    "webhook",
    "api",
    "telegram",
    "websocket",
    "sip",
    "qqbot",
    "qq",
    "qclaw",
    "mqtt",
    "discord",
    "mobile",
    "xiaoyi",
    "web",
]


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------


def _get_channel_label(channel_type: str) -> str:
    """获取渠道显示名称"""
    labels = {
        "wechat": "微信",
        "feishu": "飞书",
        "dingtalk": "钉钉",
        "wecom": "企业微信",
        "webhook": "Webhook",
        "api": "API",
        "telegram": "Telegram",
        "websocket": "WebSocket",
        "sip": "SIP",
        "qqbot": "QQ 机器人",
        "qq": "QQ",
        "qclaw": "QCLaw",
        "mqtt": "MQTT",
        "discord": "Discord",
        "mobile": "移动端",
        "xiaoyi": "小翼",
        "web": "Web 前端",
    }
    return labels.get(channel_type, channel_type)


def _get_channel_description(channel_type: str) -> str:
    """获取渠道描述"""
    descriptions = {
        "wechat": "微信公众号/小程序消息接入",
        "feishu": "飞书机器人接入，支持群聊和私聊",
        "dingtalk": "钉钉机器人接入，支持 Stream 和 Webhook 模式",
        "wecom": "企业微信应用消息接入",
        "webhook": "通用 Webhook 回调接入",
        "api": "REST API 直接调用",
        "telegram": "Telegram Bot API 接入",
        "websocket": "WebSocket 长连接接入",
        "sip": "SIP 语音通话接入",
        "qqbot": "QQ 机器人接入",
        "qq": "QQ 消息接入",
        "qclaw": "QCLaw 平台接入",
        "mqtt": "MQTT 物联网协议接入",
        "discord": "Discord Bot 接入",
        "mobile": "移动端 App 接入",
        "xiaoyi": "小翼智能助手接入",
        "web": "Web 前端界面接入",
    }
    return descriptions.get(channel_type, f"{_get_channel_label(channel_type)}渠道")


def _get_config_description(config: Dict[str, Any]) -> str:
    """获取配置描述"""
    enabled = config.get("enabled", False)
    channels = config.get("shared_channels", [])
    if not enabled:
        return "渠道上下文共享已禁用，各渠道上下文完全隔离"
    if not channels:
        return "渠道上下文共享已启用，但尚未配置共享渠道"
    return f"渠道上下文共享已启用，共享渠道: {', '.join(channels)}"


def _get_sharing_manager():
    """获取渠道共享管理器（如果可用）"""
    try:
        from neurova.channels import get_channel_manager

        return get_channel_manager()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("")
async def get_channel_sharing_config():
    """获取渠道共享配置"""
    return {
        "code": 0,
        "data": {
            "config": _sharing_config.copy(),
            "description": _get_config_description(_sharing_config),
            "last_updated": _sharing_config.get("updated_at"),
        },
    }


@router.post("/enable")
async def enable_sharing():
    """启用渠道上下文共享"""
    _sharing_config["enabled"] = True
    _sharing_config["updated_at"] = time.time()
    return {
        "code": 0,
        "message": "渠道上下文共享已启用",
        "data": {
            "enabled": True,
            "shared_channels": _sharing_config.get("shared_channels", []),
        },
    }


@router.post("/disable")
async def disable_sharing():
    """禁用渠道上下文共享，禁用后每个渠道的上下文将完全隔离"""
    _sharing_config["enabled"] = False
    _sharing_config["updated_at"] = time.time()
    return {
        "code": 0,
        "message": "渠道上下文共享已禁用",
        "data": {
            "enabled": False,
            "shared_channels": _sharing_config.get("shared_channels", []),
        },
    }


@router.post("/channels")
async def set_shared_channels(body: SetChannelsRequest):
    """设置参与上下文共享的渠道列表"""
    # 验证渠道是否有效
    invalid_channels = [ch for ch in body.channels if ch not in _AVAILABLE_CHANNELS]
    if invalid_channels:
        raise HTTPException(
            status_code=400,
            detail=f"无效的渠道类型: {', '.join(invalid_channels)}。可用渠道: {', '.join(_AVAILABLE_CHANNELS)}",
        )

    _sharing_config["shared_channels"] = body.channels
    _sharing_config["enabled"] = body.shared_context
    _sharing_config["updated_at"] = time.time()

    return {
        "code": 0,
        "message": f"已设置 {len(body.channels)} 个共享渠道",
        "data": {
            "shared_channels": body.channels,
            "enabled": body.shared_context,
            "channel_labels": [_get_channel_label(ch) for ch in body.channels],
        },
    }


@router.get("/available-channels")
async def get_available_channels():
    """获取所有可用的渠道列表，用于前端下拉选择"""
    channels_info = []
    for channel_type in _AVAILABLE_CHANNELS:
        channels_info.append(
            {
                "type": channel_type,
                "label": _get_channel_label(channel_type),
                "description": _get_channel_description(channel_type),
                "is_shared": channel_type in _sharing_config.get("shared_channels", []),
            }
        )

    return {
        "code": 0,
        "data": {
            "channels": channels_info,
            "total": len(channels_info),
            "shared_count": len(_sharing_config.get("shared_channels", [])),
        },
    }


@router.post("/test")
async def test_sharing_config(body: TestSharingRequest):
    """测试指定渠道的共享配置，返回该渠道是否启用共享以及与其他渠道的共享关系"""
    channel = body.channel
    if channel not in _AVAILABLE_CHANNELS:
        raise HTTPException(
            status_code=400, detail=f"无效的渠道类型: {channel}。可用渠道: {', '.join(_AVAILABLE_CHANNELS)}"
        )

    shared_channels = _sharing_config.get("shared_channels", [])
    is_shared = channel in shared_channels
    is_enabled = _sharing_config.get("enabled", False)

    # 获取共享关系
    shared_with = []
    if is_shared and is_enabled:
        shared_with = [ch for ch in shared_channels if ch != channel]

    # 获取渠道状态
    manager = _get_sharing_manager()
    channel_status = "unknown"
    if manager:
        try:
            adapter = manager.get_adapter(channel)
            if adapter:
                channel_status = "connected" if adapter.is_connected else "disconnected"
        except Exception:
            channel_status = "unavailable"

    return {
        "code": 0,
        "data": {
            "channel": channel,
            "channel_label": _get_channel_label(channel),
            "is_shared": is_shared,
            "is_enabled": is_enabled,
            "shared_with": shared_with,
            "shared_with_labels": [_get_channel_label(ch) for ch in shared_with],
            "channel_status": channel_status,
            "test_result": "success" if is_shared else "not_shared",
            "message": f"渠道 '{_get_channel_label(channel)}' {'已启用' if is_shared else '未启用'}上下文共享",
        },
    }


@router.get("/status")
async def get_sharing_status():
    """获取渠道上下文共享状态的简要摘要，用于前端仪表盘显示"""
    shared_channels = _sharing_config.get("shared_channels", [])
    is_enabled = _sharing_config.get("enabled", False)

    # 计算共享统计
    total_channels = len(_AVAILABLE_CHANNELS)
    shared_count = len(shared_channels)
    unshared_count = total_channels - shared_count

    # 获取管理器状态
    manager = _get_sharing_manager()
    connected_channels = 0
    if manager:
        try:
            adapters_status = manager.list_adapters()
            connected_channels = sum(1 for info in adapters_status.values() if info.get("connected", False))
        except Exception:
            pass

    return {
        "code": 0,
        "data": {
            "enabled": is_enabled,
            "total_channels": total_channels,
            "shared_channels": shared_channels,
            "shared_count": shared_count,
            "unshared_count": unshared_count,
            "connected_channels": connected_channels,
            "description": _get_config_description(_sharing_config),
            "last_updated": _sharing_config.get("updated_at"),
            "auto_sync": _sharing_config.get("auto_sync", False),
            "sync_interval": _sharing_config.get("sync_interval", 300),
        },
    }
