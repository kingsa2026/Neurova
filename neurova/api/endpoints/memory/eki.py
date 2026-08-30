"""
记忆接口 - 分类 & EKI 认知优化器
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import Depends
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_default
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
    success_response,
)

from .base import (
    _get_request_id,
    get_memory_manager,
    logger,
    router,
)


class ClassifyMemoryRequest(BaseModel):
    """分类记忆请求"""

    content: str = Field(..., min_length=1, max_length=50000, description="记忆内容")
    context: Optional[dict] = Field(default=None, description="分类上下文")


class ClassifyMemoryResponse(BaseModel):
    """分类结果响应"""

    category: str
    category_confidence: float
    type: str
    type_confidence: float
    perspective: str
    perspective_confidence: float
    is_important: bool
    is_crystallized: bool
    confidence: float
    reasoning: str


class ProcessTaskRequest(BaseModel):
    """EKI任务处理请求"""

    task_embedding: List[float] = Field(..., description="任务嵌入向量")
    memory_context: List[str] = Field(default_factory=list, description="相关记忆ID列表")
    user_feedback: Optional[float] = Field(default=None, ge=0.0, le=1.0, description="用户反馈 (0-1)")


class RecommendReinforcementRequest(BaseModel):
    """强化推荐请求"""

    top_k: int = Field(default=10, ge=1, le=100, description="推荐数量")


class PredictDecayRequest(BaseModel):
    """衰减预测请求"""

    memory_id: str = Field(..., description="记忆ID")
    horizon: int = Field(default=7, ge=1, le=30, description="预测天数")


class BatchUpdateRequest(BaseModel):
    """批量更新请求"""

    batch_data: List[dict] = Field(..., description="批量数据 [{memory_id, observations, obs_type}]")


class EKIConfigRequest(BaseModel):
    """EKI配置请求"""

    ensemble_size: Optional[int] = Field(default=None, ge=10, le=200, description="EKI集合大小")
    embed_dim: Optional[int] = Field(default=None, ge=2, le=32, description="嵌入维度")
    use_surrogate: Optional[bool] = Field(default=None, description="是否使用代理模型")
    auto_update: Optional[bool] = Field(default=None, description="是否自动更新")


# ============================================================
# 分类路由
# ============================================================


@router.post("/classify", summary="分类记忆内容")
async def classify_memory_content(
    request: ClassifyMemoryRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    对记忆内容进行分类推断

    返回分类结果但不会创建记忆
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.classify_memory(request.content, request.context)

        return success_response(
            data={
                "category": result["category"][0],
                "category_confidence": result["category"][1],
                "type": result["type"][0],
                "type_confidence": result["type"][1],
                "perspective": result["perspective"][0],
                "perspective_confidence": result["perspective"][1],
                "is_important": result["is_important"],
                "is_crystallized": result["is_crystallized"],
                "confidence": result["confidence"],
                "reasoning": result["reasoning"],
            },
            message="分类完成",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("分类失败: %s", e)
        raise APIError.internal(f"分类失败: {str(e)}")


@router.post("/classify-and-remember", summary="分类并记忆")
async def classify_and_remember(
    request: ClassifyMemoryRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    自动分类并创建记忆 (一站式操作)
    """
    try:
        manager = get_memory_manager(agent_id, user)

        # 分类结果作为 tags 并入记忆（classify_and_remember 内部先分类再 remember）
        memory_id = manager.classify_and_remember(
            content=request.content,
            metadata={"context": request.context} if request.context else None,
        )

        result = manager.classify_memory(request.content)

        return success_response(
            data={
                "memory_id": memory_id,
                "classification": {
                    "categories": result["categories"],
                    "tags": result["tags"],
                },
                "timestamp": datetime.now().isoformat(),
            },
            message="分类并记忆完成",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("分类并记忆失败: %s", e)
        raise APIError.internal(f"分类并记忆失败: {str(e)}")


# ============================================================
# EKI认知优化器路由
# ============================================================


@router.get("/eki/status", summary="获取EKI状态")
async def get_eki_status(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取EKI认知优化器状态
    """
    try:
        manager = get_memory_manager(agent_id, user)
        enabled = manager.eki_get_enabled()

        if not enabled:
            return success_response(
                data={"enabled": False, "message": "EKI优化器已禁用"},
                message="获取成功",
                request_id=_get_request_id(None),
            )

        stats = manager.eki_get_statistics()

        return success_response(
            data={
                "enabled": True,
                "statistics": stats,
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取EKI状态失败: %s", e)
        raise APIError.internal(f"获取EKI状态失败: {str(e)}")


@router.post("/eki/process", summary="处理EKI任务")
async def process_eki_task(
    request: ProcessTaskRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    EKI任务处理 - 评估任务价值并更新认知状态

    用于评估任务的信息增益，决定是否需要强化相关记忆
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.eki_process_task(
            task_embedding=request.task_embedding,
            memory_context=request.memory_context,
            user_feedback=request.user_feedback,
        )

        return success_response(
            data=result,
            message="任务处理完成",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("EKI任务处理失败: %s", e)
        raise APIError.internal(f"EKI任务处理失败: {str(e)}")


@router.get("/eki/reinforce", summary="获取强化推荐")
async def get_reinforcement_recommendations(
    top_k: int = 10,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取EKI推荐需要强化的记忆
    """
    try:
        manager = get_memory_manager(agent_id, user)
        recommendations = manager.eki_get_reinforcement_recommendations(top_k=top_k)

        return success_response(
            data={
                "count": len(recommendations),
                "recommendations": recommendations,
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取强化推荐失败: %s", e)
        raise APIError.internal(f"获取强化推荐失败: {str(e)}")


@router.get("/eki/decay/{memory_id}", summary="预测记忆衰减")
async def predict_memory_decay(
    memory_id: str,
    horizon: int = 7,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    预测指定记忆的温度衰减趋势
    """
    try:
        manager = get_memory_manager(agent_id, user)
        prediction = manager.eki_predict_decay(memory_id=memory_id, horizon=horizon)

        return success_response(
            data=prediction,
            message="预测成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("预测记忆衰减失败: %s", e)
        raise APIError.internal(f"预测记忆衰减失败: {str(e)}")


@router.get("/eki/strength/{memory_id}", summary="获取记忆强度")
async def get_memory_strength(
    memory_id: str,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取指定记忆的认知强度
    """
    try:
        manager = get_memory_manager(agent_id, user)
        strength = manager.eki_get_memory_strength(memory_id=memory_id)

        return success_response(
            data={"memory_id": memory_id, "strength": strength},
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取记忆强度失败: %s", e)
        raise APIError.internal(f"获取记忆强度失败: {str(e)}")


@router.get("/eki/statistics", summary="获取EKI统计信息")
async def get_eki_statistics(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取EKI认知优化器详细统计信息
    """
    try:
        manager = get_memory_manager(agent_id, user)
        stats = manager.eki_get_statistics()

        return success_response(
            data=stats,
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取EKI统计信息失败: %s", e)
        raise APIError.internal(f"获取EKI统计信息失败: {str(e)}")


@router.post("/eki/batch-update", summary="批量更新认知状态")
async def batch_update_cognitive_state(
    request: BatchUpdateRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    批量更新认知状态

    用于一次更新多条记忆的认知观测值
    """
    try:
        manager = get_memory_manager(agent_id, user)
        results = manager.eki_batch_update(batch_data=request.batch_data)

        return success_response(
            data={
                "updated_count": len(results),
                "results": results,
            },
            message="批量更新完成",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("批量更新认知状态失败: %s", e)
        raise APIError.internal(f"批量更新认知状态失败: {str(e)}")


@router.put("/eki/config", summary="配置EKI优化器")
async def configure_eki(
    request: EKIConfigRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    配置EKI认知优化器参数
    """
    try:
        manager = get_memory_manager(agent_id, user)
        config = {}
        if request.ensemble_size is not None:
            config["ensemble_size"] = request.ensemble_size
        if request.embed_dim is not None:
            config["embed_dim"] = request.embed_dim
        if request.use_surrogate is not None:
            config["use_surrogate"] = request.use_surrogate
        if request.auto_update is not None:
            config["auto_update"] = request.auto_update

        manager.eki_configure(config)

        return success_response(
            data=config,
            message="EKI配置已更新",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("配置EKI失败: %s", e)
        raise APIError.internal(f"配置EKI失败: {str(e)}")


@router.put("/eki/enable", summary="启用/禁用EKI优化器")
async def set_eki_enabled(
    enabled: bool = True,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    启用或禁用EKI认知优化器
    """
    try:
        manager = get_memory_manager(agent_id, user)
        manager.eki_set_enabled(enabled)

        status = "已启用" if enabled else "已禁用"
        return success_response(
            data={"enabled": enabled},
            message=f"EKI优化器{status}",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("设置EKI状态失败: %s", e)
        raise APIError.internal(f"设置EKI状态失败: {str(e)}")
