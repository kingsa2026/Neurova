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
from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from neurova.channels.base import ChannelConfig
from neurova.channels.dingtalk import create_dingtalk_adapter
from neurova.channels.discord import create_discord_adapter
from neurova.channels.feishu import create_feishu_adapter
from neurova.channels.manager import get_channel_manager
from neurova.channels.mqtt import create_mqtt_adapter
from neurova.channels.qq import create_qq_adapter
from neurova.channels.qqbot import create_qqbot_adapter
from neurova.channels.qclaw import create_qclaw_adapter
from neurova.channels.sip import create_sip_adapter
from neurova.channels.telegram import create_telegram_adapter
from neurova.channels.wechat import create_wechat_adapter
from neurova.channels.wecom import create_wecom_adapter
from neurova.channels.xiaoyi import create_xiaoyi_adapter
from neurova.api.endpoints._pydantic_compat import safe_model_dump  # s9: pydantic v1 兼容

logger = get_logger(__name__)

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
        result.append(
            ChannelConfigResponse(
                channel_type=channel_type,
                enabled=cfg.get("enabled", True),
                app_id_masked=(cfg.get("app_id", "")[:8] + "***") if cfg.get("app_id") else "",
                use_stream=cfg.get("use_stream", True),
                connected=adapter.is_connected if adapter else False,
                extra=cfg.get("extra", {}),
            )
        )
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
    config_data = safe_model_dump(request)  # s9: pydantic v1 兼容
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
    if adapter is not None:
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

    if adapter is None:
        return ChannelTestResult(
            success=False,
            message=f"Channel type '{channel_type}' does not have a registered adapter factory yet. Config saved successfully.",
        )

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
    extra = config.extra or {}

    # --- Gen 1: formal ChannelConfig-based adapters ---
    if channel_type == "feishu":
        return create_feishu_adapter(
            app_id=config.app_id,
            app_secret=config.app_secret,
            use_stream=config.use_stream,
            encrypt_key=config.encrypt_key,
            verification_token=config.verification_token,
            webhook_url=config.webhook_url,
            extra=extra,
        )
    elif channel_type == "dingtalk":
        return create_dingtalk_adapter(
            app_id=config.app_id,
            app_secret=config.app_secret,
            use_stream=config.use_stream,
            extra=extra,
        )
    elif channel_type == "wecom":
        return create_wecom_adapter(
            corpid=config.app_id,
            app_secret=config.app_secret,
            agentid=extra.get("agentid", ""),
            use_stream=config.use_stream,
            callback_token=config.webhook_token,
            encoding_aes_key=config.encrypt_key,
            webhook_url=config.webhook_url,
            extra=extra,
        )

    # --- Gen 2: config-dict-based adapters ---
    elif channel_type == "xiaoyi":
        try:
            return create_xiaoyi_adapter(
                access_key=extra.get("access_key", ""),
                secret_key=extra.get("secret_key", ""),
                agent_id=extra.get("agent_id", ""),
            )
        except Exception as e:
            logger.warning("Failed to create xiaoyi adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "discord":
        try:
            return create_discord_adapter(bot_token=extra.get("bot_token", ""))
        except Exception as e:
            logger.warning("Failed to create discord adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "telegram":
        try:
            return create_telegram_adapter(bot_token=extra.get("bot_token", ""))
        except Exception as e:
            logger.warning("Failed to create telegram adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "qq":
        try:
            return create_qq_adapter(
                app_id=config.app_id or extra.get("app_id", ""),
                token=extra.get("token", ""),
                secret=config.app_secret or extra.get("client_secret", ""),
            )
        except Exception as e:
            logger.warning("Failed to create qq adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "qqbot":
        try:
            return create_qqbot_adapter(
                access_token=extra.get("access_token", ""),
                http_url=extra.get("http_api_url", "http://127.0.0.1:3000"),
            )
        except Exception as e:
            logger.warning("Failed to create qqbot adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "wechat":
        try:
            return create_wechat_adapter(
                corpid=config.app_id,
                corpsecret=config.app_secret,
                agentid=extra.get("agentid", ""),
                mode=extra.get("mode", "ilink"),
                **extra,
            )
        except Exception as e:
            logger.warning("Failed to create wechat adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "sip":
        try:
            return create_sip_adapter(
                username=extra.get("sip_username", ""),
                password=extra.get("sip_password", ""),
                mode=extra.get("sip_mode", "dev"),
            )
        except Exception as e:
            logger.warning("Failed to create sip adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "mqtt":
        try:
            return create_mqtt_adapter(
                host=extra.get("host", "127.0.0.1"),
                port=extra.get("port", 1883),
                username=extra.get("username", ""),
                password=extra.get("password", ""),
            )
        except Exception as e:
            logger.warning("Failed to create mqtt adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    elif channel_type == "qclaw":
        try:
            return create_qclaw_adapter(
                app_id=config.app_id,
                app_secret=config.app_secret,
            )
        except Exception as e:
            logger.warning("Failed to create qclaw adapter: %s", e)
            raise HTTPException(status_code=400, detail=str(e))

    else:
        # For channel types without a dedicated factory (yuanbao, matrix, mattermost, etc.),
        # persist the config but skip adapter creation — the adapter can be registered
        # manually or via a future factory implementation.
        logger.warning("No adapter factory for channel type '%s', config saved only", channel_type)
        return None
