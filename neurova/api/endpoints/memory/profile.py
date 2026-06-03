"""
记忆接口 - 自我模型 & 用户画像
"""

from typing import Any, Dict, List, Optional

from fastapi import Request, Depends
from pydantic import BaseModel, Field
from neurova.api.auth import get_current_user

from neurova.interfaces.api_standard import (
    APIResponse,
    APIError,
)
from .base import (
    router, logger, _get_request_id, get_memory_manager, _get_user_ids_from_token,
)

class UpdateSelfModelRequest(BaseModel):
    """更新自我模型请求"""
    narrative_identity: Optional[str] = Field(default=None, description="叙事身份")
    values: Optional[List[str]] = Field(default=None, description="价值观列表")
    goals: Optional[List[str]] = Field(default=None, description="目标列表")
    capabilities: Optional[List[str]] = Field(default=None, description="能力列表")
    limitations: Optional[List[str]] = Field(default=None, description="限制列表")
    preferred_style: Optional[str] = Field(default=None, description="偏好风格")

class UpdateUserProfileRequest(BaseModel):
    """更新用户画像请求"""
    preferences: Optional[dict] = Field(default=None, description="偏好设置")
    interaction_patterns: Optional[List[str]] = Field(default=None, description="交互模式")
    conversation_style: Optional[str] = Field(default=None, description="对话风格")
    knowledge_level: Optional[int] = Field(default=None, ge=1, le=5, description="知识水平")

@router.get("/self-model", summary="获取自我模型")
async def get_self_model(
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取Agent的自我模型（持久身份、价值观、能力等）
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        self_model = manager.get_self_model()
        return APIResponse.ok(
            data=self_model,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"获取自我模型失败: {e}")
        raise APIError.internal(f"获取自我模型失败: {str(e)}")

@router.put("/self-model", summary="更新自我模型")
async def update_self_model(
    request: UpdateSelfModelRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    更新Agent的自我模型
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        updates = {}
        if request.narrative_identity is not None:
            updates['narrative_identity'] = request.narrative_identity
        if request.values is not None:
            updates['values'] = request.values
        if request.goals is not None:
            updates['goals'] = request.goals
        if request.capabilities is not None:
            updates['capabilities'] = request.capabilities
        if request.limitations is not None:
            updates['limitations'] = request.limitations
        if request.preferred_style is not None:
            updates['preferred_style'] = request.preferred_style

        manager.update_self_model(updates)
        return APIResponse.ok(
            data={"updated": list(updates.keys())},
            message="自我模型已更新",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"更新自我模型失败: {e}")
        raise APIError.internal(f"更新自我模型失败: {str(e)}")

@router.get("/users/{user_id}/profile", summary="获取用户画像")
async def get_user_profile(
    user_id: str,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取特定用户的画像
    """
    try:
        # 从Token中获取用户ID
        neuser_id, token_user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, token_user_id)
        profile = manager.get_user_profile(user_id)
        return APIResponse.ok(
            data=profile or {"message": "用户画像不存在"},
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"获取用户画像失败: {e}")
        raise APIError.internal(f"获取用户画像失败: {str(e)}")

@router.put("/users/{user_id}/profile", summary="更新用户画像")
async def update_user_profile(
    user_id: str,
    request: UpdateUserProfileRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    更新特定用户的画像
    """
    try:
        # 从Token中获取用户ID
        neuser_id, token_user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, token_user_id)
        updates = {}
        if request.preferences is not None:
            updates['preferences'] = request.preferences
        if request.interaction_patterns is not None:
            updates['interaction_patterns'] = request.interaction_patterns
        if request.conversation_style is not None:
            updates['conversation_style'] = request.conversation_style
        if request.knowledge_level is not None:
            updates['knowledge_level'] = request.knowledge_level

        manager.update_user_profile(user_id, updates)
        return APIResponse.ok(
            data={"user_id": user_id, "updated": list(updates.keys())},
            message="用户画像已更新",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"更新用户画像失败: {e}")
        raise APIError.internal(f"更新用户画像失败: {str(e)}")
