from __future__ import annotations

"""
设置管理接口 - Settings Endpoint

功能:
1. 获取全局设置 (GET /api/v1/settings)
2. 更新全局设置 (PUT /api/v1/settings)
3. 获取特定设置 (GET /api/v1/settings/{key})
4. 更新特定设置 (PUT /api/v1/settings/{key})
"""

import logging
import time
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

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
async def get_settings(request: Request):
    """获取全局设置"""
    request_id = _get_request_id(request)

    # TODO: 从数据库或文件加载设置
    settings = dict(_default_settings)

    return SettingsResponse(
        settings=settings,
        updated_at=str(time.time()),
    )


@router.put("", response_model=SettingsResponse)
async def update_settings(request: Request, body: UpdateSettingsRequest):
    """更新全局设置"""
    request_id = _get_request_id(request)

    # TODO: 保存设置到数据库或文件
    _default_settings.update(body.settings)

    return SettingsResponse(
        settings=dict(_default_settings),
        updated_at=str(time.time()),
    )


@router.get("/{key}")
async def get_setting(request: Request, key: str = Path(...)):
    """获取特定设置"""
    request_id = _get_request_id(request)

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
async def update_setting(request: Request, key: str = Path(...), value: Any = Body(...)):
    """更新特定设置"""
    request_id = _get_request_id(request)

    _default_settings[key] = value

    return {
        "code": 0,
        "message": f"Setting '{key}' updated",
        "data": {
            "key": key,
            "value": value,
        },
    }
