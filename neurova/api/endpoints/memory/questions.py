"""
记忆接口 - 问题队列 (Question Queue)
"""

from typing import Any, Dict, List, Optional

from fastapi import Depends, Query
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


class MarkQuestionAskedRequest(BaseModel):
    """标记问题已问请求"""

    question: str = Field(..., min_length=1, max_length=1000, description="问题内容")
    answer: str = Field(..., description="回答内容")


class QuestionItem(BaseModel):
    """问题条目"""

    id: str
    question_type: Optional[str] = None
    question: str
    context: Optional[str] = None
    priority: float
    is_asked: bool
    answer: Optional[str] = None
    answered_at: Optional[str] = None
    created_at: str
    updated_at: str
    tags: List[str]


def question_entry_to_dict(entry) -> dict:
    """将 QuestionQueueEntry 转换为字典"""
    return {
        "id": entry.id,
        "question_type": (
            entry.question_type.value
            if hasattr(entry.question_type, "value")
            else str(entry.question_type) if entry.question_type else None
        ),
        "question": entry.question,
        "context": entry.context,
        "priority": entry.priority,
        "is_asked": entry.is_asked,
        "answer": entry.answer,
        "answered_at": entry.answered_at.isoformat() if entry.answered_at else None,
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
        "tags": list(entry.tags) if entry.tags else [],
    }


@router.get("/questions/pending", summary="获取待问问题")
async def get_pending_questions(
    limit: int = Query(default=10, ge=1, le=50, description="返回条数"),
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取待问问题列表
    """
    try:
        manager = get_memory_manager(agent_id, user)
        questions = manager.get_pending_questions(limit=limit)

        return success_response(
            data={
                "count": len(questions),
                "questions": [question_entry_to_dict(q) for q in questions],
            },
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取待问问题失败: %s", e)
        raise APIError.internal(f"获取待问问题失败: {str(e)}")


@router.post("/questions/ask", summary="标记问题已问")
async def mark_question_asked(
    request: MarkQuestionAskedRequest,
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    标记一个问题为已问状态
    """
    try:
        manager = get_memory_manager(agent_id, user)
        entry = manager.mark_question_asked(
            question=request.question,
            answer=request.answer,
        )

        return success_response(
            data=question_entry_to_dict(entry),
            message="标记成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("标记问题失败: %s", e)
        raise APIError.internal(f"标记问题失败: {str(e)}")


@router.get("/questions/stats", summary="获取问题队列统计")
async def get_question_queue_stats(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    获取问题队列统计信息
    """
    try:
        manager = get_memory_manager(agent_id, user)
        stats = manager.get_question_stats()

        return success_response(
            data=stats,
            message="获取成功",
            request_id=_get_request_id(None),
        )

    except APIError:
        raise
    except Exception as e:
        logger.exception("获取问题队列统计失败: %s", e)
        raise APIError.internal(f"获取问题队列统计失败: {str(e)}")
