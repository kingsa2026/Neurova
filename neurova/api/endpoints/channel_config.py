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
- POST   /api/channel-configs/wechat/ilink/qrcode        - 生成 iLink 登录二维码（只生成不等待）
- GET    /api/channel-configs/wechat/ilink/qrcode/status - 单次查询 iLink 扫码状态
"""

import asyncio
import json
from neurova.core.logger import get_logger
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Query
from neurova.api.auth import get_current_user, Depends
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

router = APIRouter(dependencies=[Depends(get_current_user)],prefix="/channel-configs", tags=["渠道配置"])

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
    agent_id: str = "default"
    enabled: bool
    app_id_masked: str
    use_stream: bool
    connected: bool = False
    extra: Dict[str, Any] = Field(default_factory=dict)


class ChannelTestResult(BaseModel):
    """连接测试结果"""

    success: bool
    message: str
    needs_scan: bool = False  # F-2：wechat iLink 无 token 时诚实失败并引导扫码
    details: Dict[str, Any] = Field(default_factory=dict)


class WechatIlinkQrcodeRequest(BaseModel):
    """iLink 二维码生成请求（字段缺省时回退已保存配置/默认路径）"""

    token_file: str = Field("", description="Token 文件路径")
    bot_token: str = Field("", description="已填写的 Bot Token（有则无需扫码）")


# ============================================================
# 配置持久化（2026-09-13 渠道按 agent 多实例隔离，对齐 QwenPaw：
# agent 是渠道的所有者——存储升 v2 {version:2, agents:{agent_id:{channel_type:cfg}}}，
# 旧 v1 平铺首载幂等迁移进 default）
# ============================================================


def _save_store(store: Dict[str, Any]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_name(CONFIG_FILE.name + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_FILE)


def _load_store() -> Dict[str, Any]:
    if not CONFIG_FILE.exists():
        return {"version": 2, "agents": {}}
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, IOError):
        return {"version": 2, "agents": {}}
    if isinstance(raw, dict) and raw.get("version") == 2 and isinstance(raw.get("agents"), dict):
        return raw
    # v1 平铺 {channel_type: cfg} → 迁移为 default agent 并落盘（幂等）
    v1 = {k: v for k, v in raw.items() if isinstance(v, dict)} if isinstance(raw, dict) else {}
    store = {"version": 2, "agents": {"default": v1}}
    if v1:
        _save_store(store)
    return store


def _agent_map(store: Dict[str, Any], agent_id: str) -> Dict[str, Dict[str, Any]]:
    return store["agents"].setdefault(agent_id, {})


def _load_configs() -> Dict[str, Dict[str, Any]]:
    """v1 兼容门面：default agent 的平铺视图（既有调用/测试零破坏）。"""
    return _agent_map(_load_store(), "default")


def _save_configs(configs: Dict[str, Dict[str, Any]]) -> None:
    """v1 兼容门面：整表覆盖 default agent 视图并升 v2 落盘。"""
    store = _load_store()
    store["agents"]["default"] = configs
    _save_store(store)


# 各平台身份字段（QwenPaw channels/conflict.py _CHANNEL_IDENTITY_FIELDS 对齐）：
# 同平台跨 agent 撞身份 → 平台回调会串号，保存必须拒绝。
_IDENTITY_FIELDS: Dict[str, tuple] = {
    "feishu": ("app_id", None),
    "dingtalk": ("app_id", None),
    "wecom": ("app_id", None),
    "qq": ("app_id", None),
    "yuanbao": ("app_id", None),
    "telegram": ("bot_token", "extra"),
    "discord": ("bot_token", "extra"),
    "wechat": ("bot_token", "extra"),
    "xiaoyi": ("access_key", "extra"),
    "matrix": ("access_token", "extra"),
    "qqbot": ("access_token", "extra"),
    "sip": ("sip_username", "extra"),
}


def _extract_identity(channel_type: str, cfg: Dict[str, Any]) -> str:
    """取渠道实例的平台身份值（空身份不参与冲突比对）。"""
    spec = _IDENTITY_FIELDS.get(channel_type)
    if not spec or not isinstance(cfg, dict):
        return ""
    field, where = spec
    scope = cfg.get(where, {}) if where else cfg
    if not isinstance(scope, dict):
        return ""
    return str(scope.get(field) or "")


def _norm_agent(agent_id) -> str:
    """端点被直调（不经 FastAPI DI）时，`Query(default=...)` 会以 Query 对象
    作默认值进入函数体——回落到 default，保证直调式测试（blocking regression）
    与 DI 路径行为一致。"""
    return agent_id if isinstance(agent_id, str) and agent_id else "default"


def _identity_conflict_owner(store: Dict[str, Any], agent_id: str, channel_type: str,
                             cfg: Dict[str, Any]) -> Optional[str]:
    """QP conflict 语义：同平台同身份已被其他 agent 配置 → 返回冲突 agent_id。"""
    ident = _extract_identity(channel_type, cfg)
    if not ident:
        return None
    for other_agent, channels in store["agents"].items():
        if other_agent == agent_id or not isinstance(channels, dict):
            continue
        other_cfg = channels.get(channel_type)
        if isinstance(other_cfg, dict) and _extract_identity(channel_type, other_cfg) == ident:
            return other_agent
    return None


# ============================================================
# iLink 扫码登录辅助（F-2/F-3：非阻塞两段式）
# ============================================================

# 与 wechat_auth._authenticate_ilink 的缺省路径保持一致
ILINK_DEFAULT_TOKEN_FILE = "~/.Neurova/weixin_bot_token"


def _wechat_extra_token_file(extra: Dict[str, Any]) -> str:
    """解析 iLink token 文件路径（expanduser，绝不写回 ~ 原始串）。"""
    token_file = (extra or {}).get("token_file") or ILINK_DEFAULT_TOKEN_FILE
    return str(Path(token_file).expanduser())


def _read_token_file(path: str) -> str:
    """读取 token 文件内容（不存在/不可读返回空串——与 authenticate 的"空文件视为无 token"一致）。"""
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except (OSError, IOError):
        return ""


def _wechat_needs_scan(extra: Dict[str, Any]) -> bool:
    """wechat iLink 模式且无可用 token（表单/已存配置均无 bot_token 且 token 文件无内容）。

    非 ilink 模式（wecom/official）恒 False——不影响既有渠道行为。
    """
    mode = (extra or {}).get("mode", "ilink")
    if mode != "ilink":
        return False
    if (extra or {}).get("bot_token"):
        return False
    return not _read_token_file(_wechat_extra_token_file(extra))


def _make_ilink_adapter(token_file: str):
    """创建仅用于扫码两段式端点的轻量 iLink 适配器（无 kwargs → 不触发 authenticate/网络）。"""
    adapter = create_wechat_adapter(mode="ilink")
    adapter.ilink_token_file = token_file
    return adapter


def _wechat_authenticated(adapter) -> bool:
    """核验 wechat 适配器的真实认证状态。

    F-2 根因：WeChatAdapter.connect() 恒 True，认证结果只体现在各模式的
    *_initialized 标志上；测试连接必须核验该标志，否则空/错凭据假阳性。
    """
    mode = getattr(adapter, "mode", "")
    if mode == "ilink":
        return bool(getattr(adapter, "_ilink_initialized", False))
    if mode == "official":
        return bool(getattr(adapter, "_official_initialized", False))
    return bool(getattr(adapter, "_wecom_initialized", False))


@router.post("/wechat/ilink/qrcode", summary="生成 iLink 登录二维码（非阻塞，只生成不等待）")
async def create_wechat_ilink_qrcode(
    request: Optional[WechatIlinkQrcodeRequest] = None,
    agent_id: str = Query(default="default"),
):
    agent_id = _norm_agent(agent_id)
    """F-3 两段式·生成段：已有有效 token 直接 ready；否则一次 POST 生成二维码即返回。

    绝不在后端循环等待扫码（等待由前端轮询 status 端点驱动）。
    """
    req = request or WechatIlinkQrcodeRequest()
    saved_extra = (_agent_map(_load_store(), agent_id).get("wechat", {}) or {}).get("extra", {}) or {}

    bot_token = req.bot_token or saved_extra.get("bot_token", "")
    token_file = str(Path(req.token_file or saved_extra.get("token_file", "") or ILINK_DEFAULT_TOKEN_FILE).expanduser())

    if bot_token or _read_token_file(token_file):
        return {"status": "ready"}

    adapter = _make_ilink_adapter(token_file)
    # RES-P0-2 红线延续：同步网络工作必须下沉线程池
    qr = await asyncio.to_thread(adapter._request_ilink_qrcode)
    if qr is None:
        raise HTTPException(status_code=502, detail="生成 iLink 二维码失败（iLink 服务不可达或返回异常）")
    return {"status": "pending", "qr_url": qr.get("qr_url", ""), "qr_id": qr.get("qr_id", "")}


@router.get("/wechat/ilink/qrcode/status", summary="单次查询 iLink 扫码状态（confirmed 落盘 token）")
async def get_wechat_ilink_qrcode_status(qr_id: str = "", agent_id: str = Query(default="default")):
    agent_id = _norm_agent(agent_id)
    """F-3 两段式·轮询段：单次 GET /auth/status，如实返回 pending/scanned/expired。

    confirmed → 将 bot_token 写入 token 文件（与后台 connect 流程同一落盘路径）；
    网络失败 → 502（诚实暴露，由前端决定重试）。
    """
    if not qr_id:
        raise HTTPException(status_code=400, detail="qr_id 不能为空")

    saved_extra = (_agent_map(_load_store(), agent_id).get("wechat", {}) or {}).get("extra", {}) or {}
    token_file = _wechat_extra_token_file(saved_extra)
    adapter = _make_ilink_adapter(token_file)

    def _poll_and_maybe_save() -> Dict[str, Any]:
        data = adapter._poll_scan_once(qr_id)
        if data.get("status") == "confirmed":
            adapter.ilink_bot_token = data.get("bot_token", "")
            adapter._save_ilink_token()
        return data

    data = await asyncio.to_thread(_poll_and_maybe_save)
    status = data.get("status", "pending")
    if status == "error":
        raise HTTPException(status_code=502, detail=data.get("message", "查询扫码状态失败"))

    result: Dict[str, Any] = {"status": status}
    if status == "confirmed":
        result["token_saved"] = bool(adapter.ilink_bot_token)
    return result


# ============================================================
# API 端点
# ============================================================


async def bootstrap_channel_adapters(manager=None) -> Dict[str, int]:
    """启动装配（2026-09-13 Phase B，QP start_all_configured_agents 对齐）

    服务启动时按持久化配置逐 (agent_id, channel_type) 重建适配器并连接——
    此前无任何装配环节，配置在但重启后全渠道不连接（保存时才注册）。
    - enabled=False 跳过；wechat iLink 无 token 跳过（等扫码，绝不 300s 轮询）；
    - 工厂同步网络下沉线程池（RES-P0-2 同约束）；单渠道失败仅告警。
    """
    manager = manager or get_channel_manager()
    stats = {"registered": 0, "connected": 0, "skipped": 0, "failed": 0}
    store = _load_store()
    for agent_id, channels in (store.get("agents") or {}).items():
        if not isinstance(channels, dict):
            continue
        for channel_type, cfg in channels.items():
            if not isinstance(cfg, dict) or not cfg.get("enabled", True):
                stats["skipped"] += 1
                continue
            if channel_type == "wechat" and _wechat_needs_scan(cfg.get("extra") or {}):
                stats["skipped"] += 1
                continue
            channel_config = ChannelConfig(
                channel_type=channel_type,
                enabled=True,
                app_id=cfg.get("app_id", "") or "",
                app_secret=cfg.get("app_secret", "") or "",
                use_stream=cfg.get("use_stream", True),
                webhook_url=cfg.get("webhook_url", "") or "",
                webhook_token=cfg.get("webhook_token", "") or "",
                encrypt_key=cfg.get("encrypt_key", "") or "",
                verification_token=cfg.get("verification_token", "") or "",
                extra=cfg.get("extra", {}) or {},
            )
            try:
                adapter = await asyncio.to_thread(_create_adapter, channel_type, channel_config)
            except Exception as e:  # noqa: BLE001 - 单渠道故障不拖装配
                stats["failed"] += 1
                logger.warning("渠道装配失败 %s(agent=%s): %s", channel_type, agent_id, e)
                continue
            if adapter is None:
                stats["skipped"] += 1
                continue
            manager.register_adapter(adapter, agent_id=agent_id)
            stats["registered"] += 1
            try:
                ok = await adapter.connect()
                if ok:
                    stats["connected"] += 1
            except Exception as e:  # noqa: BLE001
                stats["failed"] += 1
                logger.warning("渠道连接失败 %s(agent=%s): %s", channel_type, agent_id, e)
    logger.info("渠道启动装配完成: %s", stats)
    return stats


@router.get("/ingress/stats", summary="入站持久化队列状态（P0-5）")
async def ingress_stats():
    """渠道入站持久化队列统计（pending/processing/dead_letter/processed）。

    供渠道管理页展示"重启不丢消息"的队列健康面。队列不可用时返回
    enabled=False（fail-open 直发模式）。
    """
    manager = get_channel_manager()
    queue = getattr(manager, "ingress_queue", None)
    if queue is None:
        return {"enabled": False}
    try:
        return {"enabled": True, **queue.stats()}
    except Exception as e:  # noqa: BLE001 - 状态查询失败不炸端点
        return {"enabled": False, "error": str(e)}


@router.get("", summary="列出渠道配置")
async def list_configs(agent_id: str = Query(default="default", description="Agent ID")):
    agent_id = _norm_agent(agent_id)
    """列出指定 agent 已配置的渠道（agent 隔离视图，缺省 default 向后兼容）"""
    manager = get_channel_manager()

    result = []
    for channel_type, cfg in _agent_map(_load_store(), agent_id).items():
        adapter = manager.get_adapter(channel_type, agent_id=agent_id)
        result.append(
            ChannelConfigResponse(
                channel_type=channel_type,
                agent_id=agent_id,
                enabled=cfg.get("enabled", True),
                app_id_masked=(cfg.get("app_id", "")[:8] + "***") if cfg.get("app_id") else "",
                use_stream=cfg.get("use_stream", True),
                connected=adapter.is_connected if adapter else False,
                extra=cfg.get("extra", {}) or {},
            )
        )
    return result


@router.get("/schemas", summary="插件渠道动态表单 schema（B4-d）")
async def list_plugin_channel_schemas():
    """已注册插件渠道的 config_fields 动态表单 schema（前端渲染用）。

    必须注册在 /{channel_type} 参数路由之前（字面量优先），
    否则 schemas 会被当作 channel_type 404。
    """
    from neurova.channels.plugin_channels import get_plugin_channel_registry

    return {
        "code": 0,
        "message": "success",
        "data": {"schemas": get_plugin_channel_registry().schemas()},
    }


@router.get("/{channel_type}", summary="获取指定渠道配置")
async def get_config(channel_type: str, agent_id: str = Query(default="default")):
    agent_id = _norm_agent(agent_id)
    """获取指定 agent 的渠道配置"""
    configs = _agent_map(_load_store(), agent_id)
    if channel_type not in configs:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not configured")

    cfg = configs[channel_type]
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type, agent_id=agent_id)

    return ChannelConfigResponse(
        channel_type=channel_type,
        agent_id=agent_id,
        enabled=cfg.get("enabled", True),
        app_id_masked=(cfg.get("app_id", "")[:8] + "***") if cfg.get("app_id") else "",
        use_stream=cfg.get("use_stream", True),
        connected=adapter.is_connected if adapter else False,
        extra=cfg.get("extra", {}) or {},
    )


@router.post("", summary="创建/更新渠道配置")
async def create_or_update_config(
    request: ChannelConfigRequest,
    agent_id: str = Query(default="default", description="归属 Agent（agent 隔离多实例）"),
):
    agent_id = _norm_agent(agent_id)
    """创建或更新指定 agent 的渠道配置并注册适配器

    2026-09-13 agent 隔离（QP：agent 是渠道所有者）：配置写 agents[agent_id]、
    适配器按 (agent_id, channel_type) 复合键注册；保存前做平台身份冲突检测
    （同 bot 撞两 agent → 平台回调串号，409 拒，对齐 QP conflict.py）。
    """
    store = _load_store()
    config_data = safe_model_dump(request)  # s9: pydantic v1 兼容
    # 不保存明文密钥到文件
    if request.app_secret:
        config_data["_app_secret_stored"] = True

    owner = _identity_conflict_owner(store, agent_id, request.channel_type, config_data)
    if owner:
        raise HTTPException(
            status_code=409,
            detail=f"平台身份冲突：agent『{owner}』已配置同身份渠道；同一 bot 双接入会导致消息串台",
        )

    _agent_map(store, agent_id)[request.channel_type] = config_data
    _save_store(store)

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

    # F-3：wechat iLink 无 token 时保存不再触发 300s 阻塞轮询——
    # 只持久化配置并返回 needs_scan，适配器注册推迟到扫码确认后（前端重发保存）
    needs_scan = request.channel_type == "wechat" and _wechat_needs_scan(request.extra)

    if not needs_scan:
        # RES-P0-2：工厂内含同步网络工作（如 iLink 认证最长 300s 轮询），
        # 必须下沉线程池，否则一次保存即冻结整个事件循环
        adapter = await asyncio.to_thread(_create_adapter, request.channel_type, channel_config)
        manager = get_channel_manager()
        if adapter is not None:
            manager.register_adapter(adapter, agent_id=agent_id)

    return {
        "success": True,
        "channel_type": request.channel_type,
        "agent_id": agent_id,
        "message": f"Channel '{request.channel_type}' configured and registered (agent={agent_id})",
        "needs_scan": needs_scan,
    }


@router.delete("/{channel_type}", summary="删除渠道配置")
async def delete_config(channel_type: str, agent_id: str = Query(default="default")):
    agent_id = _norm_agent(agent_id)
    """删除指定 agent 的渠道配置并注销其适配器实例"""
    store = _load_store()
    configs = _agent_map(store, agent_id)
    if channel_type not in configs:
        raise HTTPException(status_code=404, detail=f"Channel '{channel_type}' not found")

    # 先断开连接
    manager = get_channel_manager()
    adapter = manager.get_adapter(channel_type, agent_id=agent_id)
    if adapter and adapter.is_connected:
        await adapter.disconnect()

    # 注销适配器（复合键视图，不动其他 agent 的同平台实例）
    manager.unregister_adapter(channel_type, agent_id=agent_id)

    # 删除配置
    del configs[channel_type]
    _save_store(store)

    return {"success": True, "message": f"Channel '{channel_type}' deleted", "agent_id": agent_id}


@router.post("/{channel_type}/test", summary="测试渠道连接")
async def test_connection(channel_type: str, request: ChannelConfigRequest, agent_id: str = Query(default="default")):
    agent_id = _norm_agent(agent_id)
    """测试渠道连接是否正常"""
    # F-2：wechat iLink 无 token 时诚实失败并引导扫码——绝不创建适配器
    # （旧路径会进入 authenticate→二维码 300s 阻塞轮询，或空 extra 假成功）
    if channel_type == "wechat" and _wechat_needs_scan(request.extra):
        return ChannelTestResult(
            success=False,
            needs_scan=True,
            message="微信 iLink 渠道尚未登录：请先扫码获取 Token 后重试",
        )

    channel_config = ChannelConfig(
        channel_type=channel_type,
        enabled=True,
        app_id=request.app_id,
        app_secret=request.app_secret,
        use_stream=request.use_stream,
        webhook_url=request.webhook_url,
        extra=request.extra,
    )

    # RES-P0-2：同 create_or_update_config——同步工厂下沉线程池
    adapter = await asyncio.to_thread(_create_adapter, channel_type, channel_config)

    if adapter is None:
        return ChannelTestResult(
            success=False,
            message=f"Channel type '{channel_type}' does not have a registered adapter factory yet. Config saved successfully.",
        )

    try:
        success = await adapter.connect()
        # F-2：wechat connect() 恒 True，认证状态必须单独核验（verify 已在工厂内执行，
        # 有界 10s），凭据无效时诚实失败
        if channel_type == "wechat":
            success = success and _wechat_authenticated(adapter)
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
            # RES-P0-2 根修：mode/agentid 此前与 **extra 重复传参——extra 携带
            # mode（前端必带）时必然 TypeError→400，保存/测试从未真正可达。
            wechat_kwargs = dict(extra)
            wechat_kwargs.setdefault("mode", "ilink")
            wechat_kwargs.pop("agentid", None)
            return create_wechat_adapter(
                corpid=config.app_id,
                corpsecret=config.app_secret,
                agentid=extra.get("agentid", ""),
                **wechat_kwargs,
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
        # B4-d：插件化自定义渠道注册表优先于"仅存配置"兜底
        try:
            from neurova.channels.plugin_channels import get_plugin_channel_registry

            plugin_adapter = get_plugin_channel_registry().create_adapter(channel_type, config)
            if plugin_adapter is not None:
                return plugin_adapter
        except Exception as e:  # noqa: BLE001 — 插件工厂异常不阻断内置链路
            logger.warning("Plugin channel factory failed for '%s': %s", channel_type, e)
        # For channel types without a dedicated factory (yuanbao, matrix, mattermost, etc.),
        # persist the config but skip adapter creation — the adapter can be registered
        # manually or via a future factory implementation.
        logger.warning("No adapter factory for channel type '%s', config saved only", channel_type)
        return None