"""元认知接口 - Metacognition API Endpoint（V3 融合终态）

统一读统一台账 MetaLedger（单一事实源），原进程内存 _RECORDS stub 已死。
数据契约与前端 NeurUI/src/api/modules/metacognition.ts 逐字对齐：
- entries: {id,type,content,context,confidence,created_at}
- stats:   {total_entries, by_type, avg_confidence, recent_trend}
- state:   B 认知负荷真状态（写穿透）+ 四因子
- history: 反思时间线
- lessons: 结构化洞察（洞察编译器产出，仅活跃期内）
- reflect: 手动触发 SelfModelEngine（洞察编译器，全确定性零 LLM）
"""

from neurova.core.logger import get_logger
import typing

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from neurova.api.auth import get_current_user_or_default

from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger
from neurova.cognitive_layers.meta_cognition_layer.self_model import get_self_model_engine

logger = get_logger(__name__)
router = APIRouter()


# ── Models ─────────────────────────────────────────────


class MetacognitionRecordCreate(BaseModel):
    type: str = "monitoring"
    content: str
    context: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


def _lesson_active(meta: dict) -> bool:
    """教训活跃性过滤（与 SelfModelEngine.check_tool_advisory 同口径）。"""
    import datetime

    expires_at = meta.get("expires_at")
    if not expires_at:
        return True
    try:
        return expires_at >= datetime.datetime.now(datetime.timezone.utc).isoformat()
    except Exception:
        return True


# ── Endpoints ──────────────────────────────────────────


@router.get("/{agent_id}/metacognition")
async def get_metacognition_records(
    agent_id: str,
    request: Request,
    type: typing.Optional[str] = Query(None, alias="type"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user_or_default),
):
    """获取 Agent 的元认知记录列表（台账读投影；只返回 thought 条目）"""
    result = get_meta_ledger(agent_id).list_records(
        agent_id=agent_id, page=page, size=size, record_type=type, kind="thought"
    )
    return {"code": 0, "message": "success", "data": result}


@router.post("/{agent_id}/metacognition")
async def create_metacognition_record(
    agent_id: str,
    body: MetacognitionRecordCreate,
    request: Request,
    user: dict = Depends(get_current_user_or_default),
):
    """创建一条元认知记录（落库持久）"""
    rid = get_meta_ledger(agent_id).create_record(
        agent_id=agent_id,
        kind="thought",
        type=body.type,
        content=body.content,
        context=body.context or "",
        confidence=body.confidence,
    )
    record = get_meta_ledger(agent_id).list_records(agent_id=agent_id, page=1, size=1)
    item = next((i for i in record["items"] if i["id"] == rid), None)
    logger.info("Metacognition record created for agent %s: %s", agent_id, rid)
    return {"code": 0, "message": "Record created", "data": item or {"id": rid}}


@router.get("/{agent_id}/metacognition/stats")
async def get_metacognition_stats(
    agent_id: str,
    request: Request,
    user: dict = Depends(get_current_user_or_default),
):
    """元认知统计（契约字段：total_entries/by_type/avg_confidence/recent_trend）"""
    return {"code": 0, "message": "success", "data": get_meta_ledger(agent_id).record_stats(agent_id)}


@router.get("/{agent_id}/metacognition/state")
async def get_metacognition_state(
    agent_id: str,
    request: Request,
    user: dict = Depends(get_current_user_or_default),
):
    """认知负荷真状态（B 状态机写穿透的台账快照 + 四因子）"""
    state = get_meta_ledger(agent_id).latest_state(agent_id)
    if not state:
        state = {
            "load_level": "low",
            "load_score": 0.0,
            "active_tasks": 0,
            "memory_usage": 0.0,
            "response_time_ms": 0.0,
            "error_rate": 0.0,
            "metadata": {},
            "created_at": None,
        }
    # 四因子提到顶层，前端负荷构成视图直接消费
    state.setdefault("metadata", {})
    state["factors"] = state["metadata"].get("factors", {})
    return {"code": 0, "message": "success", "data": state}


@router.get("/{agent_id}/metacognition/lessons")
async def get_metacognition_lessons(
    agent_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user_or_default),
):
    """结构化洞察列表（kind=lesson，仅活跃期内——与调控门同口径）"""
    result = get_meta_ledger(agent_id).list_records(
        agent_id=agent_id, page=1, size=100, kind="lesson"
    )
    lessons = [
        (it.get("metadata") or {})
        for it in result["items"]
        if _lesson_active(it.get("metadata") or {})
    ][:limit]
    return {"code": 0, "message": "success", "data": {"items": lessons, "total": len(lessons)}}


@router.get("/{agent_id}/metacognition/history")
async def get_metacognition_history(
    agent_id: str,
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user_or_default),
):
    """反思报告时间线（时间线表数据源）"""
    items = get_meta_ledger(agent_id).reflection_history(agent_id, limit=limit)
    return {"code": 0, "message": "success", "data": {"items": items, "total": len(items)}}


@router.post("/{agent_id}/metacognition/reflect")
async def trigger_metacognition_reflect(
    agent_id: str,
    request: Request,
    user: dict = Depends(get_current_user_or_default),
):
    """手动触发真反思（SelfModelEngine 五算子，全确定性零 LLM）"""
    report = get_self_model_engine(agent_id).reflect(trigger="manual")
    return {"code": 0, "message": "反思完成", "data": report}
