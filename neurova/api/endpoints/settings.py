from __future__ import annotations

"""
设置管理接口 - Settings Endpoint

功能:
1. 获取全局设置 (GET /api/v1/settings)
2. 更新全局设置 (PUT /api/v1/settings)
3. 获取特定设置 (GET /api/v1/settings/{key})
4. 更新特定设置 (PUT /api/v1/settings/{key})
5. 获取 CORS 配置 (GET /api/v1/settings/cors)
6. 更新 CORS 配置 (PUT /api/v1/settings/cors)

路由顺序说明：/cors 必须在 /{key} 之前注册，否则 "cors" 会被
路径参数 {key} 捕获（GET /cors → get_setting("cors") → 404）。
"""

import json
from neurova.core.logger import get_logger
import time
import uuid
from pathlib import Path as FilePath
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)

router = APIRouter(prefix="/v1/settings")

# 默认设置（平铺 legacy 键，供 /{key} 兼容读写）
_default_settings = {
    "theme": "dark",
    "language": "zh-CN",
    "auto_save": True,
    "notifications": True,
    "stream_mode": True,
    # 2026-09-10：max_tokens/temperature 两键移除——全链零消费的死参数；
    # 温度已迁记忆设置 llm.temperature（全局默认生成温度，agent 显式值优先）
    # 2026-09-12 更正：max_tokens 有真实消费方（openai_loop 每请求读
    # llm_client.config.max_tokens），以 advanced.max_output_tokens 形式
    # 回归（见 core/app_settings.py，全局默认、显式 agent 配置优先）。
}

# 结构化 section（真持久化，data/app_settings.json——替换内存 stub：
# 此前高级选项卡保存即丢、读取形状错位，整页为装饰性）
_SETTINGS_SECTIONS = ("general", "security", "storage", "advanced")

# CORS 配置文件路径
_CORS_CONFIG_FILE = FilePath(__file__).parent.parent.parent.parent / "config" / "cors.json"

# 默认 CORS origins（开发端口 + Tauri v2 桌面壳 WebView origin）
_DEFAULT_CORS_ORIGINS = [
    "http://localhost:8100",
    "http://localhost:5173",
    "http://localhost:3000",
    "http://127.0.0.1:8100",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
    "http://tauri.localhost",
    "https://tauri.localhost",
]


class SettingsResponse(BaseModel):
    """设置响应"""

    settings: Dict[str, Any]
    updated_at: Optional[str] = None


class UpdateSettingsRequest(BaseModel):
    """更新设置请求"""

    settings: Dict[str, Any] = Field(..., description="设置键值对")


class SshCredentialRequest(BaseModel):
    """SSH 主机凭据（多主机按 host 分键；密钥/密码加密落盘，读取永不回显）"""

    host: str = Field(..., description="目标主机 IP/域名（作为分键）")
    user: str = Field("", description="SSH 用户名")
    port: int = Field(22, ge=1, le=65535, description="SSH 端口")
    key_text: str = Field("", description="私钥文本（粘贴，与 password 二选一，优先）")
    password: str = Field("", description="密码（无密钥时用）")


class SocialCredentialRequest(BaseModel):
    """社交平台凭据（web_reach social_exec 消费；键由该平台所需集决定）"""

    platform: str = Field(..., description="平台：twitter/reddit/xiaohongshu/facebook/instagram/linkedin/github")
    credentials: Dict[str, str] = Field(default_factory=dict, description="凭据键值（仅接受该平台所需键）")


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _merged_settings() -> Dict[str, Any]:
    """设置统一读源（2026-09-12 P7）：进程内默认 + 持久化 flat 段 + 结构化 section。

    原缺陷：flat 键（theme/language/auto_save/...）PUT 只写内存 `_default_settings`
    谎报保存且重启丢；单键 GET 只读内存与整表 GET（已合并持久层）语义分裂。
    flat 键现统一落 data/app_settings.json 的 "flat" section。
    """
    from neurova.core.app_settings import load_app_settings

    stored = load_app_settings()
    flat = stored.pop("flat", None) or {}
    settings = dict(_default_settings)
    settings.update(flat)
    settings.update(stored)
    return settings


@router.get("", response_model=SettingsResponse)
async def get_settings(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取全局设置 — 登录用户可读（结构化 section 持久化 + 平铺 legacy 键）"""
    _get_request_id(request)

    return SettingsResponse(
        settings=_merged_settings(),
        updated_at=str(time.time()),
    )


def _hot_apply_output_budget(request: Request) -> int:
    """把全局默认输出预算热应用到存活 agent（仅补默认/跟进自己应用过的值，
    用户显式配置永不覆盖）。失败静默——预算在 agent 重建时仍会应用。"""
    applied = 0
    try:
        agents = getattr(getattr(request.app, "state", None), "agents", None) or {}
        from neurova.core.app_settings import apply_global_output_budget

        for agent in agents.values():
            config = getattr(getattr(agent, "llm_client", None), "config", None)
            if config is not None and apply_global_output_budget(config):
                applied += 1
    except Exception:  # noqa: BLE001
        logger.debug("输出预算热应用失败（跳过）", exc_info=True)
    return applied


@router.put("", response_model=SettingsResponse)
async def update_settings(
    request: Request,
    body: UpdateSettingsRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新全局设置（仅管理员）— section 值为 dict 时持久化到 app_settings"""
    _get_request_id(request)

    from neurova.core.app_settings import save_app_settings

    flat_updates: Dict[str, Any] = {}
    for key, value in body.settings.items():
        if key in _SETTINGS_SECTIONS and isinstance(value, dict):
            save_app_settings(key, value)
        else:
            flat_updates[key] = value
    if flat_updates:
        # P7：flat 键落盘（原只写内存谎报保存）；同步进程内默认保持读一致
        save_app_settings("flat", flat_updates)
        _default_settings.update(flat_updates)

    if "advanced" in body.settings:
        applied = _hot_apply_output_budget(request)
        if applied:
            logger.info("全局输出预算已热应用到 %d 个存活 agent", applied)

    return SettingsResponse(
        settings=_merged_settings(),
        updated_at=str(time.time()),
    )


# ─── SSH 多主机凭据（computer_ssh_exec 消费；按当前用户分桶，登录即可自管）───


@router.get("/ssh-credentials")
async def list_ssh_credentials(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出当前用户已配置的 SSH 主机（脱敏：host/user/port/auth，不回显密钥/密码）。"""
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    return {"code": 0, "data": {"hosts": get_credential_store().list_ssh_hosts(uid)}}


@router.post("/ssh-credentials")
async def upsert_ssh_credential(
    request: Request,
    body: SshCredentialRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """新增/更新一个 SSH 主机凭据（加密落盘）。host 必填；key_text 与 password 至少其一。"""
    host = (body.host or "").strip()
    if not host:
        raise HTTPException(status_code=422, detail="host 不能为空")
    if not body.key_text and not body.password:
        raise HTTPException(status_code=422, detail="需提供 key_text（私钥）或 password 之一")
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    ok = get_credential_store().set_ssh_host(
        uid, host, user=body.user, port=body.port, key_text=body.key_text, password=body.password
    )
    if not ok:
        raise HTTPException(status_code=500, detail="SSH 凭据保存失败")
    return {"code": 0, "data": {"host": host, "saved": True}}


@router.delete("/ssh-credentials/{host}")
async def delete_ssh_credential(
    request: Request,
    host: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除一个 SSH 主机凭据。"""
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    if not get_credential_store().delete_ssh_host(uid, host):
        raise HTTPException(status_code=404, detail=f"未找到主机凭据: {host}")
    return {"code": 0, "data": {"host": host, "deleted": True}}


# ─── 社交平台凭据（web_reach social_exec 消费；与 SSH 复用同一配置面/加密桶）───


@router.get("/social-credentials")
async def list_social_credentials(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出各社交平台凭据配置状态（脱敏：平台 + 所需键是否已配，不回显值）。"""
    from neurova.web_reach.credentials import get_credential_store

    uid = str(current_user.get("user_id") or "default")
    return {"code": 0, "data": {"platforms": get_credential_store().platform_status(uid)}}


@router.post("/social-credentials")
async def set_social_credential(
    request: Request,
    body: SocialCredentialRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """保存某社交平台凭据（只接受该平台所需键；空值不覆盖）。"""
    from neurova.web_reach.credentials import PLATFORM_REQUIRED_KEYS, get_credential_store

    platform = (body.platform or "").strip().lower()
    if platform not in PLATFORM_REQUIRED_KEYS:
        raise HTTPException(status_code=422, detail=f"不支持的平台: {body.platform}")
    if not any((body.credentials or {}).values()):
        raise HTTPException(status_code=422, detail="未提供任何凭据值")
    uid = str(current_user.get("user_id") or "default")
    ok = get_credential_store().set_platform_credentials(uid, platform, body.credentials)
    if not ok:
        raise HTTPException(status_code=500, detail="凭据保存失败")
    return {"code": 0, "data": {"platform": platform, "saved": True}}


@router.delete("/social-credentials/{platform}")
async def clear_social_credential(
    request: Request,
    platform: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """清除某社交平台的全部凭据。"""
    from neurova.web_reach.credentials import PLATFORM_REQUIRED_KEYS, get_credential_store

    platform = (platform or "").strip().lower()
    if platform not in PLATFORM_REQUIRED_KEYS:
        raise HTTPException(status_code=404, detail=f"不支持的平台: {platform}")
    uid = str(current_user.get("user_id") or "default")
    n = get_credential_store().clear_platform_credentials(uid, platform)
    return {"code": 0, "data": {"platform": platform, "cleared": n}}


# ─── CORS 配置管理（必须在 /{key} 之前注册，避免被路径参数遮蔽）───


class CorsConfigResponse(BaseModel):
    """CORS 配置响应"""

    origins: List[str]
    allow_credentials: bool = True
    allow_methods: List[str] = ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]
    allow_headers: List[str] = ["Authorization", "Content-Type", "Accept", "X-Request-ID"]
    updated_at: Optional[str] = None


class UpdateCorsConfigRequest(BaseModel):
    """更新 CORS 配置请求"""

    origins: List[str] = Field(..., description="允许的来源列表")
    allow_credentials: Optional[bool] = Field(None, description="是否允许凭证")
    allow_methods: Optional[List[str]] = Field(None, description="允许的 HTTP 方法")
    allow_headers: Optional[List[str]] = Field(None, description="允许的请求头")


def _load_cors_config() -> Dict[str, Any]:
    """从文件加载 CORS 配置"""
    if _CORS_CONFIG_FILE.exists():
        try:
            with open(_CORS_CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Failed to load CORS config: %s", e)
    return {
        "origins": _DEFAULT_CORS_ORIGINS,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        "allow_headers": ["Authorization", "Content-Type", "Accept", "X-Request-ID"],
    }


def _save_cors_config(config: Dict[str, Any]) -> bool:
    """保存 CORS 配置到文件"""
    try:
        _CORS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_CORS_CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        logger.error("Failed to save CORS config: %s", e)
        return False


@router.get("/cors", response_model=CorsConfigResponse)
async def get_cors_config(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取 CORS 配置 — 登录用户可读"""
    _get_request_id(request)
    config = _load_cors_config()

    return CorsConfigResponse(
        origins=config.get("origins", _DEFAULT_CORS_ORIGINS),
        allow_credentials=config.get("allow_credentials", True),
        allow_methods=config.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
        allow_headers=config.get("allow_headers", ["Authorization", "Content-Type", "Accept", "X-Request-ID"]),
        updated_at=str(time.time()),
    )


@router.put("/cors", response_model=CorsConfigResponse)
async def update_cors_config(
    request: Request,
    body: UpdateCorsConfigRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新 CORS 配置（仅管理员；未授权篡改 CORS 白名单可绕过浏览器同源保护）"""
    _get_request_id(request)

    # 验证 origins 格式
    validated_origins = []
    for origin in body.origins:
        origin = origin.strip()
        if not origin:
            continue
        # 验证 URL 格式
        if not origin.startswith("http://") and not origin.startswith("https://"):
            raise HTTPException(
                status_code=400, detail=f"Invalid origin format: {origin}. Must start with http:// or https://"
            )
        validated_origins.append(origin)

    if not validated_origins:
        raise HTTPException(status_code=400, detail="At least one origin is required")

    config = _load_cors_config()
    config["origins"] = validated_origins

    if body.allow_credentials is not None:
        config["allow_credentials"] = body.allow_credentials
    if body.allow_methods is not None:
        config["allow_methods"] = body.allow_methods
    if body.allow_headers is not None:
        config["allow_headers"] = body.allow_headers

    if not _save_cors_config(config):
        raise HTTPException(status_code=500, detail="Failed to save CORS config")

    logger.info("CORS config updated by user, origins: %s", validated_origins)

    return CorsConfigResponse(
        origins=config["origins"],
        allow_credentials=config.get("allow_credentials", True),
        allow_methods=config.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"]),
        allow_headers=config.get("allow_headers", ["Authorization", "Content-Type", "Accept", "X-Request-ID"]),
        updated_at=str(time.time()),
    )


# ─── 单个设置（/{key} 必须放在 /cors 之后）───


@router.get("/{key}")
async def get_setting(
    request: Request,
    key: str = Path(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取特定设置 — 登录用户可读（读源与整表一致：默认+持久化）"""
    _get_request_id(request)

    settings = _merged_settings()
    if key not in settings:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return {
        "code": 0,
        "data": {
            "key": key,
            "value": settings[key],
        },
    }


@router.put("/{key}")
async def update_setting(
    request: Request,
    key: str = Path(...),
    value: Any = Body(..., embed=True),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新特定设置（仅管理员）— 落 app_settings 的 flat 段（P7：原只写内存谎报保存）"""
    _get_request_id(request)

    from neurova.core.app_settings import save_app_settings

    if key in _SETTINGS_SECTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"'{key}' 是结构化 section，请用 PUT /v1/settings 提交对象",
        )
    save_app_settings("flat", {key: value})
    _default_settings[key] = value

    return {
        "code": 0,
        "message": f"Setting '{key}' updated",
        "data": {
            "key": key,
            "value": value,
        },
    }
