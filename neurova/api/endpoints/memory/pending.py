"""记忆待确认队列接口（P1-2，Utopia pending_facts 裁剪版）。

契约：
- GET    /v1/memory/pending                → 待审清单（登录用户看自己的提议；
                                             admin 看全部）
- POST   /v1/memory/pending/{id}/confirm   → 确认入主库（admin 或提议人）
- POST   /v1/memory/pending/{id}/reject    → 拒绝并记指纹防重提（admin 或提议人）
- GET    /v1/memory/pending/decisions      → 裁决历史（admin）

失败方向：队列独立于主记忆库——端点漏挂/前端漏接的后果是"待审项看不见"，
未确认记忆绝不会混进检索。
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Query
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_default
from neurova.core.logger import get_logger
from neurova.interfaces.api_standard import (
    APIError,
    ErrorCodes,
    success_response,
)

from .base import _get_request_id, get_memory_manager, router

logger = get_logger(__name__)


class PendingDecisionRequest(BaseModel):
    note: str = Field(default="", description="裁决备注")


def _get_store():
    from neurova.memory.pending_memory import get_pending_memory_store

    return get_pending_memory_store()


def _is_admin(user: Dict[str, Any]) -> bool:
    return str((user or {}).get("role") or "") == "admin"


@router.get("/pending", summary="待确认记忆清单")
async def list_pending_memories(
    user: Dict[str, Any] = Depends(get_current_user_or_default),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
):
    """登录用户看自己的提议；admin 看全部（字面路由，注册在 /{memory_id} 前）。"""
    try:
        store = _get_store()
        uid = str(user.get("user_id") or "")
        records = store.list_pending() if _is_admin(user) else store.list_pending(proposed_by=uid)
        return success_response(
            data={"items": records, "total": len(records)},
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("待确认记忆清单失败: %s", e)
        raise APIError(ErrorCodes.INTERNAL, f"待确认记忆清单失败: {str(e)}") from e


@router.get("/pending/decisions", summary="待确认记忆裁决历史")
async def list_pending_decisions(
    status: str = Query(default="confirmed", description="confirmed / rejected"),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
):
    """裁决历史（仅 admin）。"""
    if not _is_admin(user):
        raise APIError(ErrorCodes.PERMISSION_DENIED, "仅管理员可查看裁决历史")
    try:
        store = _get_store()
        records = store.list_decisions(status=status)
        return success_response(
            data={"items": records, "total": len(records)},
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("裁决历史查询失败: %s", e)
        raise APIError(ErrorCodes.INTERNAL, f"裁决历史查询失败: {str(e)}") from e


@router.post("/pending/{pending_id}/confirm", summary="确认记忆入主库")
async def confirm_pending_memory(
    pending_id: str,
    body: PendingDecisionRequest = PendingDecisionRequest(),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
):
    """确认后经真实 remember 链路落库（admin 或提议人）。"""
    try:
        store = _get_store()
        rec = store.get(pending_id)
        if rec is None:
            raise APIError(ErrorCodes.NOT_FOUND, "待确认记录不存在")
        uid = str(user.get("user_id") or "")
        if not _is_admin(user) and rec.get("proposed_by") != uid:
            raise APIError(ErrorCodes.PERMISSION_DENIED, "仅提议人或管理员可确认")

        manager = get_memory_manager(agent_id, user)
        memory_id = manager.remember(
            content=rec["content"],
            category=rec["category"],
            memory_type=rec["memory_type"],
            metadata={"from_pending": True, "pending_id": pending_id},
        )
        out = store.confirm(pending_id, lambda c, cat, mt: memory_id)
        return success_response(
            data={"memory_id": out.get("memory_id"), "pending_id": pending_id},
            message="记忆已确认入库",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("确认记忆失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, f"确认记忆失败: {str(e)}") from e


@router.post("/pending/{pending_id}/reject", summary="拒绝记忆提议")
async def reject_pending_memory(
    pending_id: str,
    body: PendingDecisionRequest = PendingDecisionRequest(),
    user: Dict[str, Any] = Depends(get_current_user_or_default),
    agent_id: Optional[str] = Query(default=None, description="Agent ID"),
):
    """拒绝并记指纹（同内容不再被重复提议；admin 或提议人）。"""
    try:
        store = _get_store()
        rec = store.get(pending_id)
        if rec is None:
            raise APIError(ErrorCodes.NOT_FOUND, "待确认记录不存在")
        uid = str(user.get("user_id") or "")
        if not _is_admin(user) and rec.get("proposed_by") != uid:
            raise APIError(ErrorCodes.PERMISSION_DENIED, "仅提议人或管理员可拒绝")

        store.reject(pending_id, rejected_by=uid, note=body.note)
        return success_response(
            data={"pending_id": pending_id, "status": "rejected"},
            message="已拒绝，同内容不再重复提议",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("拒绝记忆失败: %s", e)
        raise APIError(ErrorCodes.MEMORY_OPERATION_FAILED, f"拒绝记忆失败: {str(e)}") from e
