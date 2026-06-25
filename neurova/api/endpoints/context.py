from __future__ import annotations

"""
上下文系统接口 - Context Endpoint

提供以下API:
1. 构建上下文 (POST /api/v1/context/build)
2. 获取上下文统计 (GET /api/v1/context/stats)
3. 获取上下文预览 (GET /api/v1/context/{context_id}/preview)
4. 注入反思日志 (GET /api/v1/context/inject/reflection)
5. 注入记忆 (GET /api/v1/context/inject/memories)
6. 注入高温记忆 (GET /api/v1/context/inject/hot)
7. 压缩上下文 (POST /api/v1/context/{context_id}/compress)
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.context_pool import ContextInput, ContextSource

logger = get_logger(__name__)

router = APIRouter()


class BuildContextRequest(BaseModel):
    """构建上下文请求"""

    agent_id: str = Field(default="default", description="Agent ID")
    user_input: str = Field(default="", description="用户输入")
    session_id: Optional[str] = Field(default=None, description="会话 ID")
    max_tokens: int = Field(default=16000, description="最大 token 数")
    include_reflection: bool = Field(default=True, description="包含反思日志")
    include_memories: bool = Field(default=True, description="包含记忆")
    include_constitution: bool = Field(default=True, description="包含宪法规则")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="附加元数据")


class BuildContextResponse(BaseModel):
    """构建上下文响应"""

    context_id: str
    content: str
    token_count: int
    sources: List[str]
    build_time: float


class ContextStats(BaseModel):
    """上下文统计"""

    total_contexts: int = 0
    average_tokens: float = 0
    cache_hit_rate: float = 0
    compression_rate: float = 0


class ContextPreview(BaseModel):
    """上下文预览"""

    context_id: str
    content: str
    token_count: int
    sources: List[str]


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_context_builder(user_id: str = None, agent_id: str = None, session_id: str = None):
    """获取上下文构建器（隔离版本）

    Args:
        user_id: 用户ID（必需）
        agent_id: Agent ID（必需）
        session_id: 会话ID（可选）
    """
    try:
        from neurova.context_pool import ContextPool

        if user_id is None or agent_id is None:
            logger.warning("ContextPool requires user_id and agent_id for isolation. Using default values.")
            user_id = user_id or "default_user"
            agent_id = agent_id or "default_agent"
        return ContextPool(user_id=user_id, agent_id=agent_id, session_id=session_id)
    except Exception as e:
        logger.warning("ContextPool not available: %s", e)
        return None


@router.post("/build", response_model=BuildContextResponse)
async def build_context(
    request: Request,
    body: BuildContextRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """构建上下文（带用户隔离）"""
    _get_request_id(request)
    start_time = time.time()
    context_id = str(uuid.uuid4())

    try:
        # 从JWT获取用户ID，确保隔离
        user_id = current_user.get("user_id", "unknown")
        agent_id = body.agent_id
        session_id = body.session_id

        # 使用隔离的上下文构建器
        context_builder = _get_context_builder(user_id=user_id, agent_id=agent_id, session_id=session_id)

        if context_builder:
            # 使用 ContextPool 构建上下文
            try:
                # 添加用户输入到上下文池
                user_context = ContextInput(
                    content=body.user_input,
                    source=ContextSource.USER_INPUT,
                    priority=10,  # 高优先级
                )
                context_builder.add_context(user_context)

                # 构建上下文（使用默认模型名称）
                context_messages = context_builder.build_context_for_model("default")

                # 转换为字符串格式
                context_content = "\n".join(
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in context_messages
                )
                sources = [msg.get("source", "context_pool") for msg in context_messages]

            except Exception as e:
                logger.warning("ContextPool failed, falling back: %s", e)
                # 降级到原有逻辑
                context_builder = None

        if not context_builder:
            # 降级：使用原有的 Agent 构建器
            agent = _get_agent(agent_id)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            context_content = ""
            sources = []

            if hasattr(agent, "build_context"):
                result = await agent.build_context(
                    user_input=body.user_input,
                    session_id=session_id,
                    max_tokens=body.max_tokens,
                    include_reflection=body.include_reflection,
                    include_memories=body.include_memories,
                    include_constitution=body.include_constitution,
                )
                if isinstance(result, dict):
                    context_content = result.get("content", "")
                    sources = result.get("sources", [])
                else:
                    context_content = str(result)
            else:
                # 降级：构建基础上下文
                context_content = f"User: {body.user_input}\n\nSystem: Processing request..."
                sources = ["user_input"]

        return BuildContextResponse(
            context_id=context_id,
            content=context_content,
            token_count=len(context_content.split()),  # 简单估算
            sources=sources,
            build_time=time.time() - start_time,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Build context error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build context: {str(e)}")


@router.post("/build/v2", response_model=BuildContextResponse)
async def build_context_v2(
    request: Request,
    body: BuildContextRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """构建上下文 V2（增强版，带用户隔离）"""
    _get_request_id(request)
    start_time = time.time()
    context_id = str(uuid.uuid4())

    try:
        # 从JWT获取用户ID，确保隔离
        user_id = current_user.get("user_id", "unknown")
        agent_id = body.agent_id
        session_id = body.session_id

        # 使用隔离的上下文构建器
        context_builder = _get_context_builder(user_id=user_id, agent_id=agent_id, session_id=session_id)

        if context_builder:
            # 使用 ContextPool 构建上下文
            try:
                # 添加用户输入到上下文池
                user_context = ContextInput(
                    content=body.user_input,
                    source=ContextSource.USER_INPUT,
                    priority=10,  # 高优先级
                )
                context_builder.add_context(user_context)

                # 构建上下文（使用默认模型名称）
                context_messages = context_builder.build_context_for_model("default")

                # 转换为字符串格式
                context_content = "\n".join(
                    f"{msg.get('role', 'unknown')}: {msg.get('content', '')}" for msg in context_messages
                )
                sources = [msg.get("source", "context_pool") for msg in context_messages]

            except Exception as e:
                logger.warning("ContextPool failed, falling back: %s", e)
                # 降级到原有逻辑
                context_builder = None

        if not context_builder:
            # 降级：使用原有的 Agent 构建器
            agent = _get_agent(agent_id)
            if not agent:
                raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

            # 使用 UnifiedContextInjector
            context_content = ""
            sources = []

            if hasattr(agent, "unified_injector") and agent.unified_injector:
                result = await agent.unified_injector.build_context(
                    user_input=body.user_input,
                    max_tokens=body.max_tokens,
                    include_reflection=body.include_reflection,
                    include_memories=body.include_memories,
                )
                context_content = result.get("content", "")
                sources = result.get("sources", [])
            elif hasattr(agent, "build_context"):
                result = await agent.build_context(
                    user_input=body.user_input,
                    session_id=session_id,
                    max_tokens=body.max_tokens,
                )
                if isinstance(result, dict):
                    context_content = result.get("content", "")
                    sources = result.get("sources", [])
                else:
                    context_content = str(result)
            else:
                context_content = f"User: {body.user_input}"
                sources = ["user_input"]

        return BuildContextResponse(
            context_id=context_id,
            content=context_content,
            token_count=len(context_content.split()),
            sources=sources,
            build_time=time.time() - start_time,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Build context v2 error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to build context: {str(e)}")


@router.get("/stats", response_model=ContextStats)
async def get_context_stats(request: Request):
    """获取上下文统计信息"""
    return ContextStats(
        total_contexts=0,
        average_tokens=0,
        cache_hit_rate=0,
        compression_rate=0,
    )


@router.get("/{context_id}/preview", response_model=ContextPreview)
async def get_context_preview(
    request: Request,
    context_id: str = Path(..., description="上下文ID"),
):
    """获取上下文预览"""
    # TODO: 实现上下文缓存和预览
    return ContextPreview(
        context_id=context_id,
        content="Context preview not available",
        token_count=0,
        sources=[],
    )


@router.post("/{context_id}/compress")
async def compress_context(
    request: Request,
    context_id: str = Path(..., description="上下文ID"),
    target_tokens: int = Query(default=4000, description="目标 token 数"),
):
    """压缩上下文"""
    request_id = _get_request_id(request)

    try:
        # TODO: 实现上下文压缩
        return {
            "code": 0,
            "message": "Context compression not implemented yet",
            "data": {
                "context_id": context_id,
                "target_tokens": target_tokens,
            },
            "request_id": request_id,
        }
    except Exception as e:
        logger.error(f"Compress context error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to compress context: {str(e)}")


@router.get("/inject/reflection")
async def inject_reflection_log(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
):
    """注入反思日志到上下文"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 获取反思日志
        reflection_logs = []
        if hasattr(agent, "growth_log_manager") and agent.growth_log_manager:
            reflection_logs = agent.growth_log_manager.get_recent_logs(limit=limit)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "reflection_logs": reflection_logs,
                "count": len(reflection_logs),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Inject reflection error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inject reflection: {str(e)}")


@router.get("/inject/memories")
async def inject_memories(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    query: str = Query(default="", description="搜索查询"),
    limit: int = Query(default=10, ge=1, le=100, description="数量限制"),
):
    """注入相关记忆到上下文"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 搜索记忆
        memories = []
        if hasattr(agent, "memory_manager") and agent.memory_manager:
            if query:
                memories = agent.memory_manager.search(query=query, limit=limit)
            else:
                memories = agent.memory_manager.get_recent(limit=limit)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "memories": memories,
                "count": len(memories),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Inject memories error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inject memories: {str(e)}")


@router.get("/inject/hot")
async def inject_hot_memories(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=5, ge=1, le=50, description="数量限制"),
):
    """注入高温记忆到上下文"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 获取高温记忆
        hot_memories = []
        if hasattr(agent, "memory_manager") and agent.memory_manager:
            hot_memories = agent.memory_manager.get_hot_memories(limit=limit)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "hot_memories": hot_memories,
                "count": len(hot_memories),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Inject hot memories error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to inject hot memories: {str(e)}")


@router.get("/token-budget")
async def get_token_budget(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取 Token 预算信息"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 获取 Token 预算
        budget = {
            "max_tokens": 16000,
            "used_tokens": 0,
            "available_tokens": 16000,
        }

        if hasattr(agent, "unified_injector") and agent.unified_injector:
            if hasattr(agent.unified_injector, "get_token_budget"):
                budget = agent.unified_injector.get_token_budget()

        return {
            "code": 0,
            "message": "success",
            "data": budget,
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get token budget error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get token budget: {str(e)}")


@router.put("/token-budget")
async def set_token_budget(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    max_tokens: int = Query(default=16000, ge=1000, le=128000, description="最大 token 数"),
):
    """设置 Token 预算"""
    request_id = _get_request_id(request)

    try:
        agent = _get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")

        # 设置 Token 预算
        if hasattr(agent, "unified_injector") and agent.unified_injector:
            if hasattr(agent.unified_injector, "set_token_budget"):
                agent.unified_injector.set_token_budget(max_tokens)

        return {
            "code": 0,
            "message": "Token budget updated",
            "data": {"max_tokens": max_tokens},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set token budget error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to set token budget: {str(e)}")
