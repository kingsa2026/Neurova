"""
元认知接口 - Metacognition API Endpoint
"""

import datetime
from neurova.core.logger import get_logger
import typing
import uuid

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


# ── Models ─────────────────────────────────────────────


class MetacognitionRecordCreate(BaseModel):
    thought: str
    reflection: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    category: str = "general"
    tags: typing.List[str] = Field(default_factory=list)
    context: typing.Optional[str] = None


# ── In-memory store ────────────────────────────────────

_RECORDS: typing.Dict[str, typing.List[dict]] = {}  # agent_id -> [records]


# ── Endpoints ──────────────────────────────────────────


@router.get("/{agent_id}/metacognition")
async def get_metacognition_records(
    agent_id: str,
    request: Request,
    category: typing.Optional[str] = None,
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
):
    """获取 Agent 的元认知记录列表"""
    records = _RECORDS.get(agent_id, [])
    if category:
        records = [r for r in records if r.get("category") == category]

    records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(records)
    start = (page - 1) * size
    items = records[start : start + size]

    return {"code": 0, "message": "success", "data": {"items": items, "total": total, "page": page, "size": size}}


@router.post("/{agent_id}/metacognition")
async def create_metacognition_record(agent_id: str, body: MetacognitionRecordCreate, request: Request):
    """创建一条元认知记录"""
    record_id = str(uuid.uuid4())[:12]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    record = {
        "id": record_id,
        "agent_id": agent_id,
        "thought": body.thought,
        "reflection": body.reflection,
        "confidence": body.confidence,
        "category": body.category,
        "tags": body.tags,
        "context": body.context,
        "created_at": now,
    }

    _RECORDS.setdefault(agent_id, []).append(record)
    logger.info("Metacognition record created for agent %s: %s", agent_id, record_id)

    return {"code": 0, "message": "Record created", "data": record}


@router.get("/{agent_id}/metacognition/stats")
async def get_metacognition_stats(agent_id: str, request: Request):
    """获取元认知统计信息"""
    records = _RECORDS.get(agent_id, [])
    if not records:
        return {
            "code": 0,
            "message": "success",
            "data": {"total_records": 0, "avg_confidence": 0, "categories": {}, "recent_count": 0},
        }

    total = len(records)
    avg_conf = sum(r.get("confidence", 0) for r in records) / total

    categories: typing.Dict[str, int] = {}
    for r in records:
        cat = r.get("category", "general")
        categories[cat] = categories.get(cat, 0) + 1

    # Recent (last 24h)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).isoformat()
    recent = sum(1 for r in records if r.get("created_at", "") >= cutoff)

    return {
        "code": 0,
        "message": "success",
        "data": {
            "total_records": total,
            "avg_confidence": round(avg_conf, 3),
            "categories": categories,
            "recent_count": recent,
        },
    }
