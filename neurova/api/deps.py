"""
API 依赖注入模块

提供 FastAPI 依赖注入函数，用于统一管理跨端点的公共依赖。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# HTTP Bearer scheme
security = HTTPBearer(auto_error=False)

# 模块级导入（避免重复导入）
from neurova.api.auth import verify_access_token
from neurova.api.endpoints import get_app_state


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """
    FastAPI 依赖：获取当前认证用户

    Args:
        credentials: HTTP Bearer 凭证

    Returns:
        用户信息字典

    Raises:
        HTTPException: 认证失败
    """
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials
    try:
        payload = verify_access_token(token)
    except Exception as e:
        logger.warning("Token verification failed: %s", e)
        payload = None

    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "user_id": payload.get("sub", "unknown"),
        "username": payload.get("username", "unknown"),
        "role": payload.get("role", "user"),
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[Dict[str, Any]]:
    """
    FastAPI 依赖：获取可选的认证用户

    Args:
        credentials: HTTP Bearer 凭证

    Returns:
        用户信息字典或 None
    """
    if not credentials:
        return None

    token = credentials.credentials
    try:
        payload = verify_access_token(token)
    except Exception:
        return None

    if not payload:
        return None

    return {
        "user_id": payload.get("sub", "unknown"),
        "username": payload.get("username", "unknown"),
        "role": payload.get("role", "user"),
    }


def get_agent_instance(agent_id: str = "default"):
    """
    FastAPI 依赖：获取 Agent 实例

    Args:
        agent_id: Agent ID

    Returns:
        Agent 实例

    Raises:
        HTTPException: Agent 不存在
    """
    try:
        app_state = get_app_state()
        if app_state:
            agents = app_state.get("agents", {})
            agent = agents.get(agent_id)
            if agent:
                return agent
    except Exception as e:
        logger.warning("Failed to get agent from app state: %s", e)

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Agent not found: {agent_id}",
    )


def get_memory_manager(
    agent_id: Optional[str] = None,
    user: Optional[Dict[str, Any]] = None,
):
    """
    FastAPI 依赖：获取记忆管理器

    Args:
        agent_id: Agent ID（可选）
        user: 用户信息字典（包含 neuser_id 和 user_id）

    Returns:
        记忆管理器实例

    Raises:
        HTTPException: Agent 或记忆系统不存在
    """
    try:
        app_state = get_app_state()

        if agent_id:
            agents = app_state.get("agents", {}) if app_state else {}
            agent = agents.get(agent_id)
        else:
            agent = app_state.get("default_agent") if app_state else None

        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent not found: {agent_id or 'default'}",
            )

        if not agent.memory_manager:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Memory system not enabled",
            )

        # 设置多用户隔离参数
        if user:
            agent.memory_manager.neuser_id = user.get("neuser_id", "default")
            agent.memory_manager.user_id = user.get("user_id", "default")
        else:
            agent.memory_manager.neuser_id = "default"
            agent.memory_manager.user_id = "default"

        return agent.memory_manager

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to get memory manager: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get memory manager",
        ) from e


def get_provider_manager():
    """
    FastAPI 依赖：获取 LLM Provider 管理器

    Returns:
        Provider 管理器实例

    Raises:
        HTTPException: Provider 管理器不存在
    """
    try:
        app_state = get_app_state()
        if app_state:
            provider_manager = app_state.get("provider_manager")
            if provider_manager:
                return provider_manager
    except Exception as e:
        logger.warning("Failed to get provider manager: %s", e)

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Provider manager not available",
    )


def get_channel_manager():
    """
    FastAPI 依赖：获取渠道管理器

    Returns:
        渠道管理器实例

    Raises:
        HTTPException: 渠道管理器不存在
    """
    try:
        from neurova.channels.manager import get_channel_manager as _get

        return _get()
    except Exception as e:
        logger.error("Failed to get channel manager: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Channel manager not available",
        ) from e


def get_event_bus():
    """
    FastAPI 依赖：获取事件总线

    Returns:
        事件总线实例

    Raises:
        HTTPException: 事件总线不存在
    """
    try:
        from neurova.core.event_bus import get_event_bus as _get

        return _get()
    except Exception as e:
        logger.error("Failed to get event bus: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Event bus not available",
        ) from e


def get_health_checker():
    """
    FastAPI 依赖：获取健康检查器

    Returns:
        健康检查器实例

    Raises:
        HTTPException: 健康检查器不存在
    """
    try:
        from neurova.api.endpoints import get_health_checker as _get

        return _get()
    except Exception as e:
        logger.error("Failed to get health checker: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Health checker not available",
        ) from e


def get_startup_manager():
    """
    FastAPI 依赖：获取启动管理器

    Returns:
        启动管理器实例

    Raises:
        HTTPException: 启动管理器不存在
    """
    try:
        from neurova.api.endpoints import get_startup_manager as _get

        return _get()
    except Exception as e:
        logger.error("Failed to get startup manager: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Startup manager not available",
        ) from e


def get_llm_client():
    """
    FastAPI 依赖：获取 LLM 客户端

    Returns:
        LLM 客户端实例

    Raises:
        HTTPException: LLM 客户端不存在
    """
    try:
        from neurova.api.endpoints import get_llm_client as _get

        return _get()
    except Exception as e:
        logger.error("Failed to get LLM client: %s", e)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM client not available",
        ) from e


# ============================================================
# 权限检查依赖
# ============================================================


def require_role(required_role: str):
    """
    创建角色检查依赖

    Args:
        required_role: 所需角色

    Returns:
        依赖函数
    """

    async def check_role(
        user: Dict[str, Any] = Depends(get_current_user),
    ) -> Dict[str, Any]:
        user_role = user.get("role", "user")
        if user_role != required_role and user_role != "admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required role: {required_role}",
            )
        return user

    return check_role


def require_admin():
    """
    要求管理员权限

    Returns:
        依赖函数
    """
    return require_role("admin")


# ============================================================
# 分页依赖
# ============================================================


class PaginationParams:
    """分页参数"""

    def __init__(
        self,
        page: int = 1,
        page_size: int = 20,
        offset: Optional[int] = None,
        limit: Optional[int] = None,
    ):
        self.page = max(1, page)
        self.page_size = min(max(1, page_size), 100)
        self.offset = offset if offset is not None else (self.page - 1) * self.page_size
        self.limit = limit if limit is not None else self.page_size

    def to_dict(self) -> Dict[str, int]:
        """转换为字典"""
        return {
            "page": self.page,
            "page_size": self.page_size,
            "offset": self.offset,
            "limit": self.limit,
        }


async def get_pagination(
    page: int = 1,
    page_size: int = 20,
    offset: Optional[int] = None,
    limit: Optional[int] = None,
) -> PaginationParams:
    """
    FastAPI 依赖：获取分页参数

    Args:
        page: 页码
        page_size: 每页大小
        offset: 偏移量
        limit: 限制数量

    Returns:
        分页参数对象
    """
    return PaginationParams(
        page=page,
        page_size=page_size,
        offset=offset,
        limit=limit,
    )


# ============================================================
# 请求上下文依赖
# ============================================================


class RequestContext:
    """请求上下文"""

    def __init__(
        self,
        request_id: str,
        user: Optional[Dict[str, Any]] = None,
        agent_id: str = "default",
    ):
        self.request_id = request_id
        self.user = user
        self.agent_id = agent_id

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "request_id": self.request_id,
            "user": self.user,
            "agent_id": self.agent_id,
        }


async def get_request_context(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_optional_user),
    agent_id: str = "default",
) -> RequestContext:
    """
    FastAPI 依赖：获取请求上下文

    Args:
        request: FastAPI 请求对象
        user: 用户信息
        agent_id: Agent ID

    Returns:
        请求上下文对象
    """
    request_id = getattr(request.state, "request_id", None) or str(__import__("uuid").uuid4())
    return RequestContext(
        request_id=request_id,
        user=user,
        agent_id=agent_id,
    )
