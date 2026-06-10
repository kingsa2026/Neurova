"""
负一屏设置 API - Negative Screen Settings Endpoint

功能：
1. 获取用户负一屏配置 (GET /api/v1/settings/negative-screen)
2. 更新用户负一屏配置 (PUT /api/v1/settings/negative-screen)
3. 测试负一屏推送 (POST /api/v1/settings/negative-screen/test)
4. 删除用户负一屏配置 (DELETE /api/v1/settings/negative-screen)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from neurova.notifications.negative_screen import (
    NegativeScreenConfig,
    NegativeScreenConfigManager,
    NegativeScreenPusher,
    create_negative_screen_config_manager,
    create_negative_screen_pusher,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ─── 请求/响应模型 ──────────────────────────────────────────────────────────


class NegativeScreenConfigResponse(BaseModel):
    """负一屏配置响应"""
    user_id: str
    auth_code: Optional[str] = None
    enabled: bool = False
    push_url: str = ""
    masked_auth_code: Optional[str] = None


class UpdateNegativeScreenConfigRequest(BaseModel):
    """更新负一屏配置请求"""
    auth_code: Optional[str] = Field(None, description="授权码")
    enabled: Optional[bool] = Field(None, description="是否启用")
    push_url: Optional[str] = Field(None, description="推送URL")


class TestPushRequest(BaseModel):
    """测试推送请求"""
    task_name: str = Field("测试任务", description="任务名称")
    task_content: str = Field("## 测试内容\n\n这是一条测试推送", description="任务内容")
    task_result: str = Field("测试完成", description="任务结果")


class TestPushResponse(BaseModel):
    """测试推送响应"""
    success: bool
    task_id: Optional[str] = None
    response_code: Optional[str] = None
    error: Optional[str] = None


# ─── 依赖注入 ────────────────────────────────────────────────────────────────


def _get_config_manager() -> NegativeScreenConfigManager:
    """获取配置管理器"""
    return create_negative_screen_config_manager()


def _get_pusher() -> NegativeScreenPusher:
    """获取推送器"""
    return create_negative_screen_pusher()


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_current_user_id(request: Request) -> str:
    """
    获取当前用户ID
    
    TODO: 从 JWT token 或 session 中获取实际用户ID
    """
    # 这里简化处理，实际应该从认证中获取
    # 可以从 request.state.user_id 或 JWT token 中获取
    return getattr(request.state, "user_id", "default_user")


# ─── API 端点 ────────────────────────────────────────────────────────────────


@router.get("", response_model=NegativeScreenConfigResponse)
async def get_negative_screen_config(
    request: Request,
    config_manager: NegativeScreenConfigManager = Depends(_get_config_manager),
):
    """获取用户负一屏配置"""
    request_id = _get_request_id(request)
    user_id = _get_current_user_id(request)
    
    try:
        config = config_manager.get_config(user_id)
        
        if config is None:
            # 返回默认配置
            return NegativeScreenConfigResponse(
                user_id=user_id,
                auth_code=None,
                enabled=False,
                push_url="https://hiboard-claw-drcn.ai.dbankcloud.cn/distribution/message/cloud/claw/msg/upload",
                masked_auth_code=None,
            )
        
        return NegativeScreenConfigResponse(
            user_id=config.user_id,
            auth_code=config.auth_code,
            enabled=config.enabled,
            push_url=config.push_url,
            masked_auth_code=config.masked_auth_code,
        )
        
    except Exception as e:
        logger.exception(f"获取负一屏配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取配置失败: {str(e)}",
        )


@router.put("")
async def update_negative_screen_config(
    request: Request,
    body: UpdateNegativeScreenConfigRequest,
    config_manager: NegativeScreenConfigManager = Depends(_get_config_manager),
):
    """更新用户负一屏配置"""
    request_id = _get_request_id(request)
    user_id = _get_current_user_id(request)
    
    try:
        # 获取现有配置或创建新配置
        config = config_manager.get_config(user_id)
        
        if config is None:
            config = NegativeScreenConfig(user_id=user_id)
        
        # 更新字段
        if body.auth_code is not None:
            config.auth_code = body.auth_code
        if body.enabled is not None:
            config.enabled = body.enabled
        if body.push_url is not None:
            config.push_url = body.push_url
        
        # 保存配置
        success = config_manager.save_config(config)
        
        if not success:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="保存配置失败",
            )
        
        logger.info(f"用户 {user_id} 更新负一屏配置")
        
        return {
            "code": 0,
            "message": "配置已更新",
            "data": {
                "user_id": user_id,
                "masked_auth_code": config.masked_auth_code,
                "enabled": config.enabled,
            },
            "request_id": request_id,
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"更新负一屏配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新配置失败: {str(e)}",
        )


@router.post("/test", response_model=TestPushResponse)
async def test_negative_screen_push(
    request: Request,
    body: TestPushRequest,
    config_manager: NegativeScreenConfigManager = Depends(_get_config_manager),
    pusher: NegativeScreenPusher = Depends(_get_pusher),
):
    """测试负一屏推送"""
    request_id = _get_request_id(request)
    user_id = _get_current_user_id(request)
    
    try:
        # 获取用户配置
        config = config_manager.get_config(user_id)
        
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="未配置负一屏推送，请先配置 authCode",
            )
        
        if not config.enabled:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="负一屏推送功能已禁用",
            )
        
        if not config.auth_code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="authCode 未设置",
            )
        
        # 执行测试推送
        result = await pusher.push_task(
            config=config,
            task_name=body.task_name,
            task_content=body.task_content,
            task_result=body.task_result,
        )
        
        if result.success:
            logger.info(f"用户 {user_id} 测试推送成功")
            return TestPushResponse(
                success=True,
                task_id=result.task_id,
                response_code=result.response_code,
            )
        else:
            logger.warning(f"用户 {user_id} 测试推送失败: {result.error}")
            return TestPushResponse(
                success=False,
                error=result.error,
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"测试推送失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"测试推送失败: {str(e)}",
        )


@router.delete("")
async def delete_negative_screen_config(
    request: Request,
    config_manager: NegativeScreenConfigManager = Depends(_get_config_manager),
):
    """删除用户负一屏配置"""
    request_id = _get_request_id(request)
    user_id = _get_current_user_id(request)
    
    try:
        success = config_manager.delete_config(user_id)
        
        if success:
            logger.info(f"用户 {user_id} 删除负一屏配置")
            return {
                "code": 0,
                "message": "配置已删除",
                "data": {"user_id": user_id},
                "request_id": request_id,
            }
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="配置不存在",
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"删除负一屏配置失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"删除配置失败: {str(e)}",
        )
