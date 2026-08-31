"""
Memory Settings API — 记忆系统可调参数的统一读写端点

GET    /settings              获取所有参数（含当前值和默认值）
GET    /settings/schema       获取参数 schema（含类型、范围、描述）
GET    /settings/{section}    获取某个分组的参数
PUT    /settings              批量更新参数并持久化
PUT    /settings/reset        重置参数（全部或指定 key）
GET    /settings/export       导出当前配置 JSON
PUT    /settings/import       导入配置 JSON
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from neurova.api.deps import get_current_user, require_admin

logger = get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------

class SettingsUpdateRequest(BaseModel):
    """批量更新请求"""
    settings: Dict[str, Any] = Field(
        ..., description="要更新的参数键值对，如 {\"temperature.decay_rate\": 0.2}"
    )


class SettingsResetRequest(BaseModel):
    """重置请求"""
    keys: Optional[List[str]] = Field(
        default=None,
        description="要重置的参数 key 列表。null 表示重置全部"
    )


class SettingsImportRequest(BaseModel):
    """导入请求"""
    settings: Dict[str, Any] = Field(
        ..., description="要导入的配置键值对"
    )


# ---------------------------------------------------------------------------
# 端点
# ---------------------------------------------------------------------------

@router.get("/settings")
async def get_memory_settings(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取所有记忆系统参数（当前值 + 默认值）— 登录用户可读"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    return {
        "code": 0,
        "message": "success",
        "data": cfg.get_all(),
    }


@router.get("/settings/schema")
async def get_settings_schema(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取参数 schema（含类型、范围、描述、当前值）— 登录用户可读"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    return {
        "code": 0,
        "message": "success",
        "data": cfg.get_schema(),
    }


@router.get("/settings/{section}")
async def get_settings_section(
    section: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取某个分组的参数，如 /settings/temperature"""
    from neurova.cognitive_layers.memory_layer.settings_config import (
        get_memory_settings as _get,
        PARAM_SCHEMAS,
    )
    # 校验 section 存在
    valid_sections = set(s.key.split(".")[0] for s in PARAM_SCHEMAS)
    if section not in valid_sections:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown section: {section}. Valid: {sorted(valid_sections)}"
        )
    cfg = _get()
    return {
        "code": 0,
        "message": "success",
        "data": cfg.get_section(section),
    }


@router.put("/settings")
async def update_memory_settings(
    body: SettingsUpdateRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """批量更新参数并持久化 — 仅管理员（全局配置）"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    updated = cfg.update_and_save(body.settings)
    if not updated:
        return {
            "code": 1,
            "message": "No valid settings were updated",
            "data": {"updated": []},
        }
    return {
        "code": 0,
        "message": f"Updated {len(updated)} setting(s)",
        "data": {"updated": updated},
    }


@router.put("/settings/reset")
async def reset_memory_settings(
    body: SettingsResetRequest = SettingsResetRequest(),
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """重置参数（全部或指定 key）— 仅管理员（全局配置）"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    cfg.reset_and_save(body.keys)
    return {
        "code": 0,
        "message": "Settings reset to defaults",
        "data": cfg.get_all(),
    }


@router.get("/settings/export")
async def export_memory_settings(
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """导出当前配置为 JSON — 登录用户可读"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    return {
        "code": 0,
        "message": "success",
        "data": cfg.get_all(),
    }


@router.put("/settings/import")
async def import_memory_settings(
    body: SettingsImportRequest,
    admin: Dict[str, Any] = Depends(require_admin()),
):
    """导入配置 — 仅管理员（全局配置）"""
    from neurova.cognitive_layers.memory_layer.settings_config import get_memory_settings as _get
    cfg = _get()
    updated = cfg.update_and_save(body.settings)
    return {
        "code": 0,
        "message": f"Imported {len(updated)} setting(s)",
        "data": {"imported": updated},
    }
