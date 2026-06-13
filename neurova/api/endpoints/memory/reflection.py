"""
记忆接口 - 反思日志 (Reflection Log)
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
)

from .base import (
    _get_request_id,
    get_memory_manager,
    logger,
    router,
)


class ReflectionLogRequest(BaseModel):
    """反思日志生成请求"""

    reflection_type: str = Field(default="problem_solving", description="反思类型")
    situation: str = Field(default="", description="情境描述")
    thought: str = Field(default="", description="思考过程")
    action: str = Field(default="", description="采取的行动")
    result: str = Field(default="", description="结果")
    lesson: str = Field(default="", description="学到的教训")
    improvement: str = Field(default="", description="改进建议")
    trigger_event: Optional[str] = Field(default=None, description="触发事件")
    related_memories: Optional[List[str]] = Field(default=None, description="相关记忆 ID")
    emotion_score: float = Field(default=0.0, ge=-1.0, le=1.0, description="情感分数")
    tags: Optional[List[str]] = Field(default=None, description="标签")


class ValidateReflectionRequest(BaseModel):
    """验证反思应用请求"""

    validation_result: str = Field(..., description="验证结果 (success/failed)")
    feedback: Optional[str] = Field(default=None, description="反馈")


class ReflectionLogItem(BaseModel):
    """反思日志条目"""

    id: str
    reflection_type: str
    status: str
    situation: str
    thought: str
    action: str
    result: str
    lesson: str
    improvement: str
    trigger_event: Optional[str] = None
    related_memories: List[str]
    emotion_score: float
    confidence: float
    applied_at: Optional[str] = None
    validation_result: Optional[str] = None
    validation_feedback: Optional[str] = None
    validated_at: Optional[str] = None
    created_at: str
    updated_at: str
    tags: List[str]


def reflection_log_entry_to_dict(entry) -> dict:
    """将 ReflectionLogEntry 转换为字典"""
    return {
        "id": entry.id,
        "reflection_type": (
            entry.reflection_type.value if hasattr(entry.reflection_type, "value") else str(entry.reflection_type)
        ),
        "status": entry.status.value if hasattr(entry.status, "value") else str(entry.status),
        "situation": entry.situation,
        "thought": entry.thought,
        "action": entry.action,
        "result": entry.result,
        "lesson": entry.lesson,
        "improvement": entry.improvement,
        "trigger_event": entry.trigger_event,
        "related_memories": list(entry.related_memories) if entry.related_memories else [],
        "emotion_score": entry.emotion_score,
        "tags": list(entry.tags) if entry.tags else [],
        "confidence": entry.confidence,
        "applied_at": entry.applied_at.isoformat() if entry.applied_at else None,
        "validation_result": entry.validation_result,
        "validation_feedback": entry.validation_feedback,
        "validated_at": entry.validated_at.isoformat() if entry.validated_at else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }


@router.get("/reflection/logs", summary="获取反思日志")
async def get_reflection_logs(
    reflection_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取反思日志列表，支持按类型和状态筛选
    """
    try:
        manager = get_memory_manager(agent_id, user)

        result = manager.get_reflection_logs(
            reflection_type=reflection_type,
            status=status,
            limit=limit,
            offset=offset,
        )

        logs = [reflection_log_entry_to_dict(entry) for entry in result.get("logs", [])]

        return APIResponse.ok(
            data={
                "count": len(logs),
                "total": result.get("total", 0),
                "logs": logs,
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取反思日志失败: %s", e)
        raise APIError.internal(f"获取反思日志失败: {str(e)}")


@router.post("/reflection/generate", summary="生成反思日志")
async def generate_reflection(
    request: ReflectionLogRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    生成新的反思日志
    """
    try:
        manager = get_memory_manager(agent_id, user)

        log_id = manager.generate_reflection(
            reflection_type=request.reflection_type,
            situation=request.situation,
            thought=request.thought,
            action=request.action,
            result=request.result,
            lesson=request.lesson,
            improvement=request.improvement,
            trigger_event=request.trigger_event,
            related_memories=request.related_memories,
            emotion_score=request.emotion_score,
            tags=request.tags,
        )

        return APIResponse.ok(
            data={"log_id": log_id},
            message="反思日志生成成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("生成反思日志失败: %s", e)
        raise APIError.internal(f"生成反思日志失败: {str(e)}")


@router.put("/reflection/{log_id}/validate", summary="验证反思应用结果")
async def validate_reflection(
    log_id: str,
    request: ValidateReflectionRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    验证反思日志的应用结果
    """
    try:
        manager = get_memory_manager(agent_id, user)

        entry = manager.validate_reflection(
            log_id=log_id,
            validation_result=request.validation_result,
            feedback=request.feedback,
        )

        return APIResponse.ok(
            data=reflection_log_entry_to_dict(entry),
            message="验证成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("验证反思日志失败: %s", e)
        raise APIError.internal(f"验证反思日志失败: {str(e)}")


@router.get("/reflection/stats", summary="获取反思日志统计")
async def get_reflection_stats(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    获取反思日志统计信息
    """
    try:
        manager = get_memory_manager(agent_id, user)
        stats = manager.get_reflection_stats()

        return APIResponse.ok(
            data=stats,
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取反思统计失败: %s", e)
        raise APIError.internal(f"获取反思统计失败: {str(e)}")


# ============================================================
# Agent 级路由（兼容前端 /agents/{agent_id}/reflection 路径）
# ============================================================


@router.get("/{agent_id}/reflection", summary="获取 Agent 反思记录")
async def get_agent_reflection(
    agent_id: str,
    limit: int = 20,
    offset: int = 0,
    category: Optional[str] = None,
    req: Request = None,
):
    """获取 Agent 的反思记录（前端 ReflectionPage.vue 调用）"""
    try:
        from neurova.agent_registry import AgentRegistry

        registry = AgentRegistry()
        agent = registry.get_agent(agent_id)
        if not agent:
            return APIResponse.ok(
                data={"items": [], "total": 0, "stats": {"total": 0, "suggestions": 0, "status": "低"}},
                request_id=_get_request_id(req),
            )

        manager = getattr(agent, "reflection_manager", None)
        records = getattr(manager, "records", []) if manager else []
        total = len(records)
        items = records[offset : offset + limit]

        # 统计
        by_category = {}
        suggestions = 0
        for r in records:
            cat = getattr(r, "category", "")
            by_category[cat] = by_category.get(cat, 0) + 1
            if getattr(r, "has_suggestion", False):
                suggestions += 1

        status = "低"
        if total > 50:
            status = "高"
        elif total > 20:
            status = "中"

        return APIResponse.ok(
            data={
                "agent_id": agent_id,
                "total": total,
                "items": [
                    {
                        "id": getattr(r, "id", str(i)),
                        "title": getattr(r, "title", "")[:50],
                        "tag": getattr(r, "category", ""),
                        "desc": getattr(r, "content", "")[:100],
                        "lv": int(getattr(r, "confidence", 0.5) * 5),
                        "date": getattr(r, "created_at", "")[:10],
                    }
                    for i, r in enumerate(items)
                ],
                "stats": {
                    "total": total,
                    "suggestions": suggestions,
                    "status": status,
                    "by_category": by_category,
                },
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except Exception as e:
        logger.exception("获取反思记录失败: %s", e)
        return APIResponse.ok(
            data={"items": [], "total": 0, "stats": {"total": 0, "suggestions": 0, "status": "低"}},
            request_id=_get_request_id(req),
        )


@router.get("/{agent_id}/reflection/stats", summary="获取 Agent 反思统计")
async def get_agent_reflection_stats(
    agent_id: str,
    req: Request = None,
):
    """获取 Agent 反思统计（前端 ReflectionPage.vue 调用）"""
    try:
        from neurova.agent_registry import AgentRegistry

        registry = AgentRegistry()
        agent = registry.get_agent(agent_id)
        if not agent:
            return APIResponse.ok(
                data={"agent_id": agent_id, "total": 0, "by_category": {}},
                request_id=_get_request_id(req),
            )

        manager = getattr(agent, "reflection_manager", None)
        records = getattr(manager, "records", []) if manager else []
        total = len(records)

        by_category = {}
        suggestions = 0
        for r in records:
            cat = getattr(r, "category", "")
            by_category[cat] = by_category.get(cat, 0) + 1
            if getattr(r, "has_suggestion", False):
                suggestions += 1

        status = "低"
        if total > 50:
            status = "高"
        elif total > 20:
            status = "中"

        return APIResponse.ok(
            data={
                "agent_id": agent_id,
                "total": total,
                "suggestions": suggestions,
                "status": status,
                "by_category": by_category,
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except Exception as e:
        logger.exception("获取反思统计失败: %s", e)
        return APIResponse.ok(
            data={"agent_id": agent_id, "total": 0, "by_category": {}},
            request_id=_get_request_id(req),
        )
