"""
记忆接口 - 时序知识图谱 (Temporal Knowledge Graph)
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_default
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
    success_response,
)

from .base import (
    _get_request_id,
    _get_user_ids_from_token,
    get_memory_manager,
    logger,
    router,
)


class AddTemporalFactRequest(BaseModel):
    """添加时序事实请求"""

    entity: str = Field(..., description="主体实体")
    attribute: str = Field(..., description="属性名")
    value: Any = Field(..., description="属性值")
    timestamp: Optional[str] = Field(default=None, description="时间戳（ISO8601格式，默认当前时间）")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="置信度")
    source: Optional[str] = Field(default=None, description="信息来源")
    metadata: Optional[dict] = Field(default=None, description="额外元数据，如对话ID/环境等")


class QueryTemporalRequest(BaseModel):
    """查询时序事实请求"""

    entity: str = Field(..., description="主体实体")
    relation: Optional[str] = Field(default=None, description="关系/属性（可选）")
    start_time: Optional[str] = Field(default=None, description="起始时间")
    end_time: Optional[str] = Field(default=None, description="结束时间")
    limit: Optional[int] = Field(default=10, ge=1, le=100, description="返回数量")


@router.post("/tkg/facts", summary="添加时序事实")
async def add_temporal_fact(
    request: AddTemporalFactRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    添加时序事实到知识图谱

    用于记录具有时间维度的实体属性变化
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        fact_id = manager.tkg_add_fact(
            entity=request.entity,
            attribute=request.attribute,
            value=request.value,
            timestamp=request.timestamp,
            confidence=request.confidence,
            source=request.source,
            metadata=request.metadata,
        )

        return success_response(
            data={"fact_id": fact_id},
            message="时序事实已添加",
            request_id=_get_request_id(req),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("添加时序事实失败: %s", e)
        raise APIError.internal(f"添加时序事实失败: {str(e)}")


@router.post("/tkg/query", summary="查询时序事实")
async def query_temporal_facts(
    request: QueryTemporalRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    查询时序知识图谱中的事实

    支持按实体、关系、时间范围进行查询
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        facts = manager.tkg_query(
            entity=request.entity,
            relation=request.relation,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
        )

        return success_response(
            data={
                "count": len(facts),
                "facts": facts,
            },
            message="查询成功",
            request_id=_get_request_id(req),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("查询时序事实失败: %s", e)
        raise APIError.internal(f"查询时序事实失败: {str(e)}")


@router.get("/tkg/history/{entity}/{relation}", summary="获取事实演变历史")
async def get_temporal_history(
    entity: str,
    relation: str,
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取指定实体关系的事实演变历史
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        history = manager.tkg_get_history(
            entity=entity,
            relation=relation,
        )

        return success_response(
            data={
                "entity": entity,
                "relation": relation,
                "count": len(history),
                "history": history,
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取事实演变历史失败: %s", e)
        raise APIError.internal(f"获取事实演变历史失败: {str(e)}")


@router.get("/tkg/stats", summary="获取时序知识图谱统计")
async def get_tkg_stats(
    agent_id: Optional[str] = None,
    req: Request = None,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取时序知识图谱统计信息
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)

        manager = get_memory_manager(agent_id, neuser_id, user_id)
        stats = manager.tkg_get_stats()

        return success_response(
            data=stats,
            message="获取成功",
            request_id=_get_request_id(req),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取时序图谱统计失败: %s", e)
        raise APIError.internal(f"获取时序图谱统计失败: {str(e)}")
