"""
记忆接口 - 情绪分析 (Emotion Analysis)
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends, Query, Request
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
    memory_to_dict,
    router,
)


class AnalyzeEmotionRequest(BaseModel):
    """分析文本情绪请求"""

    text: str = Field(..., min_length=1, max_length=50000, description="待分析文本")


class EmotionAnalysisResult(BaseModel):
    """情绪分析结果"""

    scores: dict
    dominant_emotion: str
    overall_score: float
    tags: List[str]


# 注意：/emotion/{emotion_type} 路径参数路由必须在本文件所有
# /emotion/* 字面路由（summary/distribution/types）之后注册，
# 否则它们会被吞掉（FastAPI 按注册顺序匹配）。见文件末尾。


@router.get("/emotion/summary", summary="获取情绪统计摘要")
async def get_emotion_summary(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取情绪统计摘要

    返回各情绪类型的数量、占比、平均分等统计信息
    """
    try:
        manager = get_memory_manager(agent_id, user)
        # 尝试调用 get_emotion_summary，不存在时返回默认数据
        if hasattr(manager, 'get_emotion_summary'):
            summary = manager.get_emotion_summary()
        else:
            summary = {
                "current": {},
                "categories": [],
                "history": [],
            }

        return success_response(
            data=summary,
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取情绪统计失败: %s", e)
        # 返回空数据而非 500
        return success_response(
            data={"current": {}, "categories": [], "history": []},
            message="获取成功(降级)",
            request_id=_get_request_id(None),
        )


@router.get("/emotion/distribution", summary="获取情绪分布")
async def get_emotion_distribution(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取情绪分布统计

    返回各情绪类型的记忆数量
    """
    try:
        manager = get_memory_manager(agent_id, user)
        if hasattr(manager, 'get_emotion_distribution'):
            distribution = manager.get_emotion_distribution()
        else:
            distribution = {}

        return success_response(
            data={
                "distribution": distribution,
                "total": sum(distribution.values()) if distribution else 0,
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取情绪分布失败: %s", e)
        raise APIError.internal(f"获取情绪分布失败: {str(e)}")


@router.post("/emotion/analyze", summary="分析文本情绪")
async def analyze_emotion(
    request: AnalyzeEmotionRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    分析文本情绪

    返回各情绪维度的分数、主导情绪和情绪标签
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.analyze_emotion(request.text)

        return success_response(
            data=result,
            message="分析完成",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("情绪分析失败: %s", e)
        raise APIError.internal(f"情绪分析失败: {str(e)}")


@router.get("/emotion/types", summary="获取支持的情绪类型")
async def get_emotion_types(
    req: Request = None,
):
    """
    获取支持的情绪类型列表

    返回系统支持的所有情绪类型及其层次、类别、强度范围
    """
    try:
        from neurova.cognitive_layers.memory_layer.emotion import get_emotion_analyzer_instance

        hierarchy = get_emotion_analyzer_instance().get_emotion_hierarchy()

        emotion_types = [
            {
                "type": emotion,
                "layer": info.get("layer"),
                "category": info.get("category"),
                "intensity_range": list(info.get("intensity_range", ())),
            }
            for emotion, info in hierarchy.items()
        ]

        return success_response(
            data={
                "emotion_types": emotion_types,
                "count": len(emotion_types),
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )

    except Exception as e:
        logger.exception("获取情绪类型失败: %s", e)
        raise APIError.internal(f"获取情绪类型失败: {str(e)}")


@router.get("/emotion/{emotion_type}", summary="按情绪类型查询记忆")
async def get_memories_by_emotion(
    emotion_type: str,
    min_score: float = Query(default=0.0, ge=0.0, le=1.0, description="最小情绪分数"),
    limit: int = Query(default=20, ge=1, le=100, description="返回条数"),
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    按情绪类型查询记忆

    情绪类型可选值: joy, sadness, love, fear, hope, anger, surprise
    """
    try:
        manager = get_memory_manager(agent_id, user)
        memories = manager.get_memories_by_emotion(emotion=emotion_type, limit=limit)

        return success_response(
            data={
                "count": len(memories),
                "emotion_type": emotion_type,
                "memories": [memory_to_dict(m) for m in memories],
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("按情绪查询记忆失败: %s", e)
        raise APIError.internal(f"按情绪查询记忆失败: {str(e)}")
