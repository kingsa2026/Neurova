from __future__ import annotations

"""
渠道管理接口 - Channel Endpoint

功能:
1. 获取渠道列表 (GET /api/v1/channels)
2. 获取渠道详情 (GET /api/v1/channels/{id})
3. 创建渠道 (POST /api/v1/channels)
4. 更新渠道 (PUT /api/v1/channels/{id})
5. 删除渠道 (DELETE /api/v1/channels/{id})
6. 测试渠道连接 (POST /api/v1/channels/{id}/test)
"""

import logging
import time
import typing
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class ChannelInfo(BaseModel):
    """渠道信息"""
    channel_id: str
    name: str
    channel_type: str = "feishu"
    status: str = "disconnected"
    enabled: bool = True
    config: Dict[str, Any] = {}
    created_at: float = 0
    updated_at: float = 0


class ChannelCreate(BaseModel):
    """创建渠道请求"""
    name: str = Field(..., description="渠道名称")
    channel_type: str = Field(default="feishu", description="渠道类型")
    enabled: bool = Field(default=True, description="是否启用")
    config: Dict[str, Any] = Field(default_factory=dict, description="渠道配置")


class ChannelUpdate(BaseModel):
    """更新渠道请求"""
    name: Optional[str] = None
    enabled: Optional[bool] = None
    config: Optional[Dict[str, Any]] = None


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_channel_manager():
    """获取渠道管理器"""
    try:
        from neurova.channels.manager import ChannelManager
        return ChannelManager()
    except Exception as e:
        logger.warning(f"ChannelManager not available: {e}")
        return None


@router.get("", response_model=List[ChannelInfo])
async def get_channels(
    request: Request,
    channel_type: Optional[str] = Query(default=None, description="渠道类型筛选"),
    status: Optional[str] = Query(default=None, description="状态筛选"),
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取渠道列表"""
    channel_manager = _get_channel_manager()
    
    channels = []
    if channel_manager:
        try:
            if hasattr(channel_manager, "get_channels"):
                channels = channel_manager.get_channels(
                    channel_type=channel_type,
                    status=status,
                    limit=limit,
                )
        except Exception as e:
            logger.warning(f"Failed to get channels: {e}")
    
    return channels


@router.post("", response_model=ChannelInfo)
async def create_channel(
    request: Request,
    body: ChannelCreate,
):
    """创建渠道"""
    request_id = _get_request_id(request)
    
    channel_manager = _get_channel_manager()
    
    channel_id = str(uuid.uuid4())
    timestamp = time.time()
    
    if channel_manager:
        try:
            if hasattr(channel_manager, "create_channel"):
                channel_manager.create_channel(
                    channel_id=channel_id,
                    name=body.name,
                    channel_type=body.channel_type,
                    enabled=body.enabled,
                    config=body.config,
                )
        except Exception as e:
            logger.warning(f"Failed to create channel: {e}")
    
    return ChannelInfo(
        channel_id=channel_id,
        name=body.name,
        channel_type=body.channel_type,
        status="disconnected",
        enabled=body.enabled,
        config=body.config,
        created_at=timestamp,
        updated_at=timestamp,
    )


@router.get("/{channel_id}", response_model=ChannelInfo)
async def get_channel(
    request: Request,
    channel_id: str = Path(..., description="渠道ID"),
):
    """获取渠道详情"""
    channel_manager = _get_channel_manager()
    
    if channel_manager:
        try:
            if hasattr(channel_manager, "get_channel"):
                channel = channel_manager.get_channel(channel_id)
                if channel:
                    return channel
        except Exception as e:
            logger.warning(f"Failed to get channel: {e}")
    
    raise HTTPException(status_code=404, detail=f"Channel '{channel_id}' not found")


@router.put("/{channel_id}", response_model=ChannelInfo)
async def update_channel(
    request: Request,
    channel_id: str = Path(..., description="渠道ID"),
    body: ChannelUpdate = ChannelUpdate(),
):
    """更新渠道"""
    request_id = _get_request_id(request)
    
    channel_manager = _get_channel_manager()
    
    if channel_manager:
        try:
            if hasattr(channel_manager, "update_channel"):
                update_data = body.dict(exclude_unset=True)
                channel_manager.update_channel(channel_id, update_data)
        except Exception as e:
            logger.warning(f"Failed to update channel: {e}")
    
    return await get_channel(request, channel_id)


@router.delete("/{channel_id}")
async def delete_channel(
    request: Request,
    channel_id: str = Path(..., description="渠道ID"),
):
    """删除渠道"""
    request_id = _get_request_id(request)
    
    channel_manager = _get_channel_manager()
    
    if channel_manager:
        try:
            if hasattr(channel_manager, "delete_channel"):
                channel_manager.delete_channel(channel_id)
        except Exception as e:
            logger.warning(f"Failed to delete channel: {e}")
    
    return {
        "code": 0,
        "message": f"Channel '{channel_id}' deleted",
        "data": {"channel_id": channel_id},
        "request_id": request_id,
    }


@router.post("/{channel_id}/test")
async def test_channel_connection(
    request: Request,
    channel_id: str = Path(..., description="渠道ID"),
):
    """测试渠道连接"""
    request_id = _get_request_id(request)
    
    channel_manager = _get_channel_manager()
    
    if channel_manager:
        try:
            if hasattr(channel_manager, "test_connection"):
                result = channel_manager.test_connection(channel_id)
                return {
                    "code": 0,
                    "message": "Connection test completed",
                    "data": {"channel_id": channel_id, "result": result},
                    "request_id": request_id,
                }
        except Exception as e:
            logger.warning(f"Failed to test channel connection: {e}")
    
    return {
        "code": 0,
        "message": "Connection test not available",
        "data": {"channel_id": channel_id},
        "request_id": request_id,
    }
