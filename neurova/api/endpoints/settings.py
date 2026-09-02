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

# 默认设置
_default_settings = {
    "theme": "dark",
    "language": "zh-CN",
    "auto_save": True,
    "notifications": True,
    "max_tokens": 4096,
    "temperature": 0.7,
    "stream_mode": True,
}

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


def _get_request_id(request: Request) -> str:
    """安全获取 request_id"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("", response_model=SettingsResponse)
async def get_settings(
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取全局设置 — 登录用户可读"""
    _get_request_id(request)

    # TODO: 从数据库或文件加载设置
    settings = dict(_default_settings)

    return SettingsResponse(
        settings=settings,
        updated_at=str(time.time()),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(
    request: Request,
    body: UpdateSettingsRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新全局设置（仅管理员）"""
    _get_request_id(request)

    # TODO: 保存设置到数据库或文件
    _default_settings.update(body.settings)

    return SettingsResponse(
        settings=dict(_default_settings),
        updated_at=str(time.time()),
    )


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
    """获取特定设置 — 登录用户可读"""
    _get_request_id(request)

    if key not in _default_settings:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")

    return {
        "code": 0,
        "data": {
            "key": key,
            "value": _default_settings[key],
        },
    }


@router.put("/{key}")
async def update_setting(
    request: Request,
    key: str = Path(...),
    value: Any = Body(...),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """更新特定设置（仅管理员）"""
    _get_request_id(request)

    _default_settings[key] = value

    return {
        "code": 0,
        "message": f"Setting '{key}' updated",
        "data": {
            "key": key,
            "value": value,
        },
    }
