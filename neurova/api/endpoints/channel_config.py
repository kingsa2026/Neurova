from __future__ import annotations

"""
渠道配置管理 API

提供渠道配置的 CRUD 操作，支持动态添加/修改/删除渠道配置。
配置持久化到 agent.json 或独立配置文件。

路由:
- GET    /api/channel-configs                  - 列出所有渠道配置
- GET    /api/channel-configs/{channel_type}   - 获取指定渠道配置
- POST   /api/channel-configs                  - 创建/更新渠道配置
- DELETE /api/channel-configs/{channel_type}   - 删除渠道配置
- POST   /api/channel-configs/{channel_type}/test - 测试连接
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neurova.channels.base import ChannelConfig
from neurova.channels.feishu import create_feishu_adapter, FeishuAdapter
from neurova.channels.dingtalk import create_dingtalk_adapter, DingTalkAdapter
from neurova.channels.wecom import create_wecom_adapter, WeComAdapter
from neurova.channels.manager import get_channel_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/channel-configs", tags=["渠道配置"])

# 配置文件路径
CONFIG_DIR = Path(__file__).parent.parent.parent / "data"
CONFIG_FILE = CONFIG_DIR / "channel_configs.json"

# ============================================================
# 请求/响应模型
# ============================================================

class ChannelConfigRequest(BaseModel):
    """渠道配置请求"""
    channel_type: str = Field(..., description="渠道类型: feishu, dingtalk, wecom")
    enabled: bool = Field(True, description="是否启用")
    app_id: str = Field("", description="应用 ID")
    app_secret: str = Field("", description="应用密钥")
    use_stream: bool = Field(True, description="是否使用 Stream 模式")
    webhook_url: str = Field("", description="Webhook 回调 URL")
    webhook_token: str = Field("", description="Webhook 验证 Token")
    encrypt_key: str = Field("", description="加密密钥")
    verification_token: str = Field("", description="验证 Token")
    extra: Dict[str, Any] = Field(default_factory=dict, description="额外配置")

class ChannelConfigResponse(BaseModel):
    """渠道配置响应"""
    channel_type: str
    enabled: bool
    app_id_masked: str
    use_stream: bool
    connected: bool = False
    extra: Dict[str, Any] = Field(default_factory=dict)

class ChannelTestResult(BaseModel):
    """连接测试结果"""
    success: bool
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

# ============================================================
# 配置持久化
# ============================================================

def _load_configs() -> Dict[str, Dict[str, Any]]:
    """从文件加载配置"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {}

def _save_configs(configs: Dict[str, Dict[str, Any]]):
    """保存配置到文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(configs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

# ============================================================
# API 端点
# ============================================================

@router.get("", summary="列出所有渠道配置")
async def list_configs():
    """列出所有已配置的渠道"""
    configs = _load_configs()
    manager = get_channel_manager()

    result = []
    for channel_type, cfg in configs.items():
        adapter = manager.get_adapter(channel_type)
        result.append(ChannelConfigResponse(
            channel_type=channel_type,
            enabled=cfg.get("enabled", True),
            app_id_masked=(cfg.get("app_id", "")[:8] + "***") if cfg.get("app_id") else "",
            use_stream=cfg.get("use_stream", True),
            connected=adapter.is_connected if adapter else False,
            extra=cfg.get("extra", {}),
        ))
    return result

@router.get("/{channel_type}", summary="获取指定渠道配置")
async def get_config(channel_type: str):
    """获取指定渠道的配置"""
    configs = _load_configs()
    if channel_type not in configs:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not configured")

    cfg = configs[channel_type]
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type)

    return ChannelConfigResponse(
        channel_type=channel_type,
        enabled=cfg.get("enabled", True),
        app_id_masked=(cfg.get("app_id", "")[:8] + "***") if cfg.get("app_id") else "",
        use_stream=cfg.get("use_stream", True),
        connected=adapter.is_connected if adapter else False,
        extra=cfg.get("extra", {}),
    )

@router.post("", summary="创建/更新渠道配置")
async def create_or_update_config(request: ChannelConfigRequest):
    """创建或更新渠道配置，并可选地自动注册适配器"""
    # 持久化配置
    configs = _load_configs()
    config_data = request.model_dump()
    # 不保存明文密钥到文件
    if request.app_secret:
        config_data["_app_secret_stored"] = True
    configs[request.channel_type] = config_data
    _save_configs(configs)

    # 创建适配器并注册
    channel_config = ChannelConfig(
        channel_type=request.channel_type,
        enabled=request.enabled,
        app_id=request.app_id,
        app_secret=request.app_secret,
        use_stream=request.use_stream,
        webhook_url=request.webhook_url,
        webhook_token=request.webhook_token,
        encrypt_key=request.encrypt_key,
        verification_token=request.verification_token,
        extra=request.extra,
    )

    adapter = _create_adapter(request.channel_type, channel_config)
    manager = get_channel_manager()
    manager.register_adapter(adapter)

    return {
        "success": True,
        "channel_type": request.channel_type,
        "message": f"Channel '{request.channel_type}' configured and registered",
    }

@router.delete("/{channel_type}", summary="删除渠道配置")
async def delete_config(channel_type: str):
    """删除渠道配置并注销适配器"""
    configs = _load_configs()
    if channel_type not in configs:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not found")

    # 先断开连接
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type)
    if adapter and adapter.is_connected:
        await adapter.disconnect()

    # 注销适配器
    manager.unregister_adapter(channel_type)

    # 删除配置
    del configs[channel_type]
    _save_configs(configs)

    return {"success": True, "message": f"Channel '{channel_type}' deleted"}

@router.post("/{channel_type}/test", summary="测试渠道连接")
async def test_connection(channel_type: str, request: ChannelConfigRequest):
    """测试渠道连接是否正常"""
    channel_config = ChannelConfig(
        channel_type=channel_type,
        enabled=True,
        app_id=request.app_id,
        app_secret=request.app_secret,
        use_stream=request.use_stream,
        webhook_url=request.webhook_url,
        extra=request.extra,
    )

    adapter = _create_adapter(channel_type, channel_config)

    try:
        success = await adapter.connect()
        if success:
            health = await adapter.health_check()
            await adapter.disconnect()
            return ChannelTestResult(
                success=True,
                message=f"Connection to {channel_type} successful",
                details=health,
            )
        else:
            return ChannelTestResult(
                success=False,
                message=f"Failed to connect to {channel_type}",
            )
    except Exception as e:
        return ChannelTestResult(
            success=False,
            message=f"Connection error: {str(e)}",
            details={"error": str(e)},
        )

def _create_adapter(channel_type: str, config: ChannelConfig):
    """根据类型创建适配器"""
    if channel_type == "feishu":
        return create_feishu_adapter(
            app_id=config.app_id,
            app_secret=config.app_secret,
            use_stream=config.use_stream,
            encrypt_key=config.encrypt_key,
            verification_token=config.verification_token,
            webhook_url=config.webhook_url,
            extra=config.extra,
        )
    elif channel_type == "dingtalk":
        return create_dingtalk_adapter(
            app_id=config.app_id,
            app_secret=config.app_secret,
            use_stream=config.use_stream,
            extra=config.extra,
        )
    elif channel_type == "wecom":
        return create_wecom_adapter(
            corpid=config.app_id,
            app_secret=config.app_secret,
            agentid=config.extra.get("agentid", ""),
            use_stream=config.use_stream,
            callback_token=config.webhook_token,
            encoding_aes_key=config.encrypt_key,
            webhook_url=config.webhook_url,
            extra=config.extra,
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported channel type: {channel_type}")
