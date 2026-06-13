"""
记忆接口 - 工作记忆 (Working Memory)
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
)

from .base import (
    _get_request_id,
    _get_user_ids_from_token,
    get_memory_manager,
    logger,
    router,
)


class AddTurnRequest(BaseModel):
    """添加对话轮次请求"""

    role: str = Field(..., description="角色 (user/assistant/system)")
    content: str = Field(..., description="内容")
    metadata: Optional[dict] = Field(default=None, description="元数据")


class CompressTurnRequest(BaseModel):
    """压缩请求"""

    content: str = Field(..., max_length=10000, description="待压缩内容")


class CachePlanRequest(BaseModel):
    """缓存计划请求"""

    task_description: str = Field(..., description="任务描述")
    steps: list = Field(..., description="执行步骤列表")
    task_type: Optional[str] = Field(default=None, description="任务类型")
    context: Optional[dict] = Field(default=None, description="上下文")


class RetrievePlanRequest(BaseModel):
    """检索计划请求"""

    task_description: str = Field(..., description="任务描述")
    task_type: Optional[str] = Field(default=None, description="任务类型")
    top_k: Optional[int] = Field(default=3, ge=1, le=10, description="返回数量")


class RecordPlanResultRequest(BaseModel):
    """记录计划执行结果请求"""

    plan_id: str = Field(..., description="计划ID")
    success: bool = Field(..., description="是否成功")


@router.post("/wm/turns", summary="添加对话轮次")
async def add_wm_turn(
    request: AddTurnRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    添加对话轮次到工作记忆
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        manager.wm_add_turn(request.role, request.content, request.metadata)

        return APIResponse.ok(
            data={"added": True},
            message="添加成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("添加对话轮次失败: %s", e)
        raise APIError.internal(f"添加对话轮次失败: {str(e)}")


@router.get("/wm/context", summary="获取工作记忆上下文")
async def get_wm_context(
    max_turns: Optional[int] = Query(default=None, ge=1, le=100, description="最大轮数"),
    use_folded: Optional[bool] = Query(default=True, description="是否使用折叠状态"),
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取当前工作记忆上下文
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        context = manager.wm_get_context(max_turns, use_folded)

        return APIResponse.ok(
            data={"context": context},
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取工作记忆上下文失败: %s", e)
        raise APIError.internal(f"获取工作记忆上下文失败: {str(e)}")


@router.post("/wm/compress", summary="压缩单轮内容")
async def compress_turn(
    request: CompressTurnRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    压缩单轮对话内容
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        compressed = manager.wm_compress_turn(request.content)

        return APIResponse.ok(
            data={"original": request.content, "compressed": compressed},
            message="压缩完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("压缩失败: %s", e)
        raise APIError.internal(f"压缩失败: {str(e)}")


@router.post("/wm/plans", summary="缓存执行计划")
async def cache_wm_plan(
    request: CachePlanRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    缓存执行计划到工作记忆
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        plan_id = manager.wm_cache_plan(request.task_description, request.steps, request.task_type, request.context)

        return APIResponse.ok(
            data={"plan_id": plan_id},
            message="计划缓存成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("缓存计划失败: %s", e)
        raise APIError.internal(f"缓存计划失败: {str(e)}")


@router.post("/wm/plans/retrieve", summary="检索执行计划")
async def retrieve_wm_plan(
    request: RetrievePlanRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    从工作记忆检索相似的执行计划
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        plans = manager.wm_retrieve_plan(request.task_description, request.task_type, request.top_k)

        return APIResponse.ok(
            data={"count": len(plans), "plans": plans},
            message="检索完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("检索计划失败: %s", e)
        raise APIError.internal(f"检索计划失败: {str(e)}")


@router.post("/wm/plans/result", summary="记录计划执行结果")
async def record_plan_result(
    request: RecordPlanResultRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    记录计划执行结果
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        manager.wm_record_plan_result(request.plan_id, request.success)

        return APIResponse.ok(
            data={"recorded": True},
            message="记录成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("记录结果失败: %s", e)
        raise APIError.internal(f"记录结果失败: {str(e)}")


@router.get("/wm/stats", summary="获取工作记忆统计")
async def get_wm_stats(
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取工作记忆的统计信息
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        stats = manager.wm_get_stats()

        return APIResponse.ok(
            data=stats,
            message="获取统计成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取工作记忆统计失败: %s", e)
        raise APIError.internal(f"获取工作记忆统计失败: {str(e)}")


@router.delete("/wm", summary="清空工作记忆")
async def clear_wm(
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """
    清空当前工作记忆
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        manager.wm_clear()

        return APIResponse.ok(
            data={"cleared": True},
            message="清空成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("清空工作记忆失败: %s", e)
        raise APIError.internal(f"清空工作记忆失败: {str(e)}")
