"""Console annotation endpoints and compatibility-exported request models."""
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from neurova.api.deps import get_current_user

router = APIRouter()


class AnnotationCreateRequest(BaseModel):
    __module__ = "neurova.api.endpoints.console"
    question: str
    answer: str


class AnnotationUpdateRequest(BaseModel):
    __module__ = "neurova.api.endpoints.console"
    answer: Optional[str] = None
    enabled: Optional[bool] = None


@router.get("/annotations")
async def list_annotations(
    request: Request,
    q: str = Query(default="", description="按问题/答案子串过滤"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """精准回复命中表清单（管理页：按命中次数排序）。"""
    from neurova.core.annotation_store import get_annotation_store

    store = get_annotation_store()
    items = store.list_annotations(limit=limit)
    if q:
        ql = q.lower()
        items = [a for a in items if ql in (a.get("question") or "").lower() or ql in (a.get("answer") or "").lower()]
    return {"code": 0, "message": "ok", "data": {"items": items, "total": store.count()}}


@router.post("/annotations")
async def create_annotation(
    body: AnnotationCreateRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """手工新增精准回复（不限于反馈链路沉淀）。"""
    if not body.question.strip() or not body.answer.strip():
        raise HTTPException(status_code=400, detail="question/answer 不能为空")
    from neurova.core.annotation_store import get_annotation_store

    ann_id = get_annotation_store().add(body.question.strip(), body.answer.strip(), source="manual")
    return {"code": 0, "message": "ok", "data": {"id": ann_id}}


@router.put("/annotations/{annotation_id}")
async def update_annotation(
    annotation_id: str,
    body: AnnotationUpdateRequest,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新答案 / 启停用（停用即下线该精准回复）。"""
    from neurova.core.annotation_store import get_annotation_store

    store = get_annotation_store()
    if store.get(annotation_id) is None:
        raise HTTPException(status_code=404, detail="标注不存在")
    if body.answer is not None:
        store.update_answer(annotation_id, body.answer)
    if body.enabled is not None:
        store.set_enabled(annotation_id, body.enabled)
    return {"code": 0, "message": "ok", "data": store.get(annotation_id)}


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(
    annotation_id: str,
    request: Request,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    from neurova.core.annotation_store import get_annotation_store

    if not get_annotation_store().delete(annotation_id):
        raise HTTPException(status_code=404, detail="标注不存在")
    return {"code": 0, "message": "ok"}


@router.get("/annotations/export")
async def export_training_set(request: Request, current_user: Dict[str, Any] = Depends(get_current_user)):
    """重训练化集导出：JSONL（input/output 对）——供后续 SFT 微调集。"""
    from neurova.core.annotation_store import get_annotation_store

    lines = get_annotation_store().export_training_set()
    return {"code": 0, "message": "ok", "data": {"jsonl": "\n".join(lines), "count": len(lines)}}
