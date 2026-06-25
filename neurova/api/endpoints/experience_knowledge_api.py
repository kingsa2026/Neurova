"""
Experience Knowledge Base API - 经验知识库接口
"""

import datetime
from neurova.core.logger import get_logger
import typing
import uuid

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


class AddExperienceRecordRequest(BaseModel):
    skill_name: str
    input_context: str
    output_result: str
    success: bool = True
    execution_time_ms: float = 0
    metadata: typing.Optional[dict] = None
    tags: typing.List[str] = Field(default_factory=list)


class FindSimilarExperiencesRequest(BaseModel):
    context: str
    skill_name: typing.Optional[str] = None
    top_k: int = Field(default=5, ge=1, le=20)


_RECORDS: typing.Dict[str, typing.List[dict]] = {}  # skill_name -> [records]


@router.post("/records")
async def add_experience_record(body: AddExperienceRecordRequest, request: Request):
    """添加经验记录到经验知识库"""
    record_id = str(uuid.uuid4())[:12]
    now = datetime.datetime.utcnow().isoformat()
    record = {
        "id": record_id,
        "skill_name": body.skill_name,
        "input_context": body.input_context,
        "output_result": body.output_result,
        "success": body.success,
        "execution_time_ms": body.execution_time_ms,
        "metadata": body.metadata or {},
        "tags": body.tags,
        "created_at": now,
    }
    _RECORDS.setdefault(body.skill_name, []).append(record)
    return {"code": 0, "message": "Record added", "data": record}


@router.get("/records/{skill_name}")
async def get_experience_records(skill_name: str, page: int = 1, size: int = 20):
    """获取指定技能的经验记录"""
    records = _RECORDS.get(skill_name, [])
    records.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    total = len(records)
    start = (page - 1) * size
    return {
        "code": 0,
        "message": "success",
        "data": {"items": records[start : start + size], "total": total, "page": page, "size": size},
    }


@router.post("/similar")
async def find_similar_experiences(body: FindSimilarExperiencesRequest):
    """查找与给定上下文相似的经验记录"""
    all_records = []
    for records in _RECORDS.values():
        all_records.extend(records)

    # Simple keyword matching as fallback
    query_lower = body.context.lower()
    scored = []
    for r in all_records:
        score = sum(1 for word in query_lower.split() if word in r.get("input_context", "").lower())
        if score > 0:
            scored.append((score, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [r for _, r in scored[: body.top_k]]

    return {"code": 0, "message": "success", "data": {"results": results, "total": len(results)}}


@router.get("/evaluate/{skill_name}")
async def evaluate_skill(skill_name: str):
    """评估指定技能的效果"""
    records = _RECORDS.get(skill_name, [])
    if not records:
        return {"code": 0, "message": "No records found", "data": {"skill_name": skill_name, "total_executions": 0}}

    total = len(records)
    successes = sum(1 for r in records if r.get("success"))
    avg_time = sum(r.get("execution_time_ms", 0) for r in records) / total

    return {
        "code": 0,
        "message": "success",
        "data": {
            "skill_name": skill_name,
            "total_executions": total,
            "success_rate": round(successes / total, 3),
            "avg_execution_time_ms": round(avg_time, 2),
            "recent_trend": "stable",
        },
    }


@router.get("/recommendations/{skill_name}")
async def get_recommendations(skill_name: str):
    """获取指定技能的最佳实践推荐"""
    records = _RECORDS.get(skill_name, [])
    successful = [r for r in records if r.get("success")]
    successful.sort(key=lambda x: x.get("execution_time_ms", float("inf")))
    best = successful[:3]

    return {
        "code": 0,
        "message": "success",
        "data": {"skill_name": skill_name, "recommendations": best, "based_on": len(successful)},
    }


@router.get("/stats")
async def get_stats():
    """获取经验知识库的统计信息"""
    total_records = sum(len(v) for v in _RECORDS.values())
    total_skills = len(_RECORDS)
    return {
        "code": 0,
        "message": "success",
        "data": {"total_records": total_records, "total_skills": total_skills, "skills": list(_RECORDS.keys())},
    }


@router.get("/ranking")
async def get_skill_ranking():
    """获取技能排名"""
    rankings = []
    for skill, records in _RECORDS.items():
        if not records:
            continue
        total = len(records)
        successes = sum(1 for r in records if r.get("success"))
        avg_time = sum(r.get("execution_time_ms", 0) for r in records) / total
        rankings.append(
            {
                "skill_name": skill,
                "total_executions": total,
                "success_rate": round(successes / total, 3),
                "avg_execution_time_ms": round(avg_time, 2),
            }
        )
    rankings.sort(key=lambda x: x["success_rate"], reverse=True)
    return {"code": 0, "message": "success", "data": {"rankings": rankings}}


@router.get("/health")
async def health_check():
    """经验知识库健康检查"""
    return {"code": 0, "message": "healthy", "data": {"status": "ok", "skills_count": len(_RECORDS)}}
