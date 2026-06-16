from __future__ import annotations

"""
记忆接口 - 基础模块

共享导入、请求/响应模型、辅助函数
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from neurova.interfaces.api_standard import (
    APIError,
    ErrorCodes,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["记忆管理"])

# ============================================================
# 辅助函数
# ============================================================


def _get_request_id(req: Optional[Request]) -> Optional[str]:
    return getattr(req.state, "request_id", None) if req else None


def resolve_user(user: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """将可选用户解析为有效用户(未认证时返回默认用户)"""
    return user or {"user_id": "default", "username": "default", "role": "user"}


def _get_user_ids_from_token(req: Optional[Request]) -> tuple:
    """从请求的 Token 中提取 neuser_id 和 user_id

    尝试从 Authorization header 解析 JWT token 中的用户标识，
    如果解析失败则返回默认值。
    """
    neuser_id = "default"
    user_id = "default"

    if req:
        try:
            auth_header = req.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
                from neurova.api.auth import verify_access_token

                payload = verify_access_token(token)
                if payload:
                    neuser_id = payload.get("neuser_id", "default")
                    user_id = payload.get("user_id", payload.get("sub", "default"))
        except Exception:
            pass  # Token 解析失败时使用默认值

    return neuser_id, user_id


# ============================================================
# 请求/响应模型
# ============================================================


class AddMemoryRequest(BaseModel):
    """添加记忆请求"""

    content: str = Field(..., min_length=1, max_length=50000, description="记忆内容")
    category: Optional[str] = Field(default=None, description="记忆分类 (为空则自动推断)")
    is_important: Optional[bool] = Field(default=None, description="是否重要 (为空则自动判断)")
    is_crystallized: Optional[bool] = Field(default=None, description="是否固化 (为空则自动判断)")
    emotion_score: float = Field(default=0.0, ge=-1.0, le=1.0, description="情感分数")
    perspective: Optional[str] = Field(default=None, description="记忆视角 (为空则自动推断)")
    metadata: Optional[dict] = Field(default=None, description="额外元数据")
    auto_classify: bool = Field(default=True, description="是否自动分类推断 (默认开启)")
    classification_context: Optional[dict] = Field(default=None, description="分类上下文")
    auto_analyze_emotion: bool = Field(default=True, description="是否自动分析情绪 (默认开启)")


class MemoryItem(BaseModel):
    """记忆项"""

    id: str
    agent_id: str
    content: str
    category: str
    temperature: float
    lifecycle_stage: str
    is_important: bool
    is_crystallized: bool
    emotion_score: float
    access_count: int
    created_at: str
    last_accessed_at: Optional[str] = None


def memory_to_dict(memory) -> dict:
    """将 Memory 对象转换为字典（安全序列化，容忍损坏数据）"""
    try:
        return {
            "id": getattr(memory, "id", ""),
            "agent_id": getattr(memory, "agent_id", ""),
            "content": str(getattr(memory, "content", "")),
            "category": str(getattr(memory, "category", "")),
            "temperature": float(getattr(memory, "temperature", 100.0)),
            "lifecycle_stage": str(getattr(memory, "lifecycle_stage", "")),
            "is_important": bool(getattr(memory, "is_important", False)),
            "is_crystallized": bool(getattr(memory, "is_crystallized", False)),
            "emotion_score": float(getattr(memory, "emotion_score", 0.5)),
            "access_count": int(getattr(memory, "access_count", 0)),
            "created_at": str(getattr(memory, "created_at", "")),
            "last_accessed_at": str(getattr(memory, "last_accessed_at", "")),
        }
    except Exception:
        return {
            "id": str(getattr(memory, "id", "unknown")),
            "content": str(getattr(memory, "content", "(数据损坏)")),
            "category": "unknown",
        }


def get_memory_manager(agent_id: Optional[str] = None, user: Optional[Dict[str, Any]] = None):
    """
    获取记忆管理器

    参数:
    agent_id: Agent ID（可选）
    user: 用户信息字典（包含neuser_id和user_id），如果为None则使用默认值
    """
    from neurova.api.app import get_app_state

    _state = get_app_state()
    if not _state:
        raise APIError(ErrorCodes.AGENT_NOT_INITIALIZED, "应用状态未初始化") from None

    if agent_id:
        agent = _state.agents.get(agent_id)
        if not agent:
            raise APIError.not_found(f"Agent 不存在: {agent_id}") from None
    else:
        agent = _state.get_agent()
        if not agent:
            raise APIError(ErrorCodes.AGENT_NOT_INITIALIZED, "默认 Agent 未初始化") from None

    if not agent.memory_manager:
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, "记忆系统未启用") from None

    # 设置多用户隔离参数(安全设置，跳过只读属性)
    if user:
        if hasattr(agent.memory_manager, 'neuser_id'):
            try:
                agent.memory_manager.neuser_id = user.get("neuser_id", "default")
            except (AttributeError, AttributeError):
                pass
        if hasattr(agent.memory_manager, 'user_id'):
            try:
                agent.memory_manager.user_id = user.get("user_id", "default")
            except (AttributeError, AttributeError):
                pass

    return agent.memory_manager
