"""
Experience Knowledge Base API - 经验知识库接口（真实 SQLite 存储）

2026-09-02 重构：原实现为内存 stub（进程级 _RECORDS 空 dict、无写入方、
无持久化），导致前端 /agent/:id/experience-knowledge 页面恒空数据。
现桥接 neurova.skills.experience_knowledge_base.ExperienceKnowledgeBase
（data/experience_knowledge.db，post_chat_pipeline 反思与 meta_cognition
真实写入），契约对齐前端 NeurUI/src/api/modules/experience.ts：
- POST /records          手动结晶写入经验记录
- GET  /ranking?agent_id 分页列表（前端 list/ranking/recommendations 共用）
- GET  /stats?agent_id   统计卡（total_experiences/success_rate/…）
- POST /similar         相似经验检索（关键词重叠 60% + 话题 30% + 成功加权 10%）
- GET  /{id} / DELETE /{id}  单条查看/删除
- PUT  /{id}/disposition  人工处置（审核/降权/隐藏/恢复，工单 015）

处置与删除是两条通路（工单 015）：PUT 只改 `operator_disposition`，可逆、不删行、
不写采纳证据列；要让条目永久不存在仍然走 DELETE。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

from neurova.core.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)


class AddExperienceRecordRequest(BaseModel):
    agent_id: str
    task_type: str
    context: str
    outcome: str = "success"
    lessons: Optional[List[str]] = None
    metadata: Optional[Dict[str, Any]] = None


class FindSimilarExperiencesRequest(BaseModel):
    agent_id: Optional[str] = None
    query: str
    limit: int = Field(default=5, ge=1, le=20)


class ExperienceDispositionRequest(BaseModel):
    """人工处置态（工单 015）：审核通过 / 降权 / 隐藏 / null=恢复未处置。

    刻意不给 "deleted"：删除是另一个动作（DELETE /{id}），不可逆。
    刻意不给 confidence/成功位：采纳证据由 006 的回写通路独占，人的判断写进
    那一格就是把审核洗成执行成功。
    """

    disposition: Optional[Literal["endorsed", "demoted", "suppressed"]] = None


# ─────────────────────────────────────────────────────────────────────────────
# 单例工厂（sqlite 连接线程安全在 EKB 内部持锁）
# ─────────────────────────────────────────────────────────────────────────────

_kb: Optional[Any] = None
_kb_lock = threading.Lock()


def get_experience_kb():
    """全局 ExperienceKnowledgeBase 单例（测试可 monkeypatch）。"""
    global _kb
    if _kb is None:
        with _kb_lock:
            if _kb is None:
                from neurova.skills.experience_knowledge_base import ExperienceKnowledgeBase

                _kb = ExperienceKnowledgeBase()
    return _kb


def reset_experience_kb() -> None:
    """重置单例（测试用）。"""
    global _kb
    with _kb_lock:
        if _kb is not None:
            try:
                _kb.close()
            except Exception:
                pass
        _kb = None


# ─────────────────────────────────────────────────────────────────────────────
# 记录映射（EKB 行 → 前端 ExperienceRecord 契约）
# ─────────────────────────────────────────────────────────────────────────────


def _to_contract(row: Dict[str, Any], experience_count: int) -> Dict[str, Any]:
    """EKB 行 → 前端 ExperienceRecord 契约（工单 015 起不再自造读数）。

    `experience_count` 必须由调用方给出真实聚合值：这里曾硬编码 1，同一技能在生产
    库里攒到 7 条，界面仍然显示 1。
    置信度缺失保持 None，不再回落成 `1.0/0.0` 二值——二值喂给五格星级，等于把
    "没测到"演成"满级/零级"。
    """
    ctx = row.get("context") or {}
    if isinstance(ctx, dict):
        ctx_text = str(ctx.get("user_input", "") or "")
    else:
        ctx_text = str(ctx)
    confidence = row.get("confidence_score")
    rating = round(float(confidence), 4) if confidence is not None else None
    feedback = row.get("feedback") or ""
    lessons = [l for l in str(feedback).splitlines() if l.strip()] if feedback else []
    return {
        "id": str(row["id"]),
        "agent_id": row.get("agent_id") or "",
        "task_type": row.get("skill_name", ""),
        "skill_name": row.get("skill_name", ""),
        "context": ctx_text,
        "outcome": "success" if row.get("success") else "failure",
        "success_rate": rating,
        "proficiency": rating,
        "experience_count": experience_count,
        "lessons": lessons,
        # 工单 006/008/015 的运营读数来源：证据态与处置态原样给到界面，
        # 界面自己不做二次推断（008 已删掉那批"零调用方的假聚合"）
        "adoption_outcome": row.get("adoption_outcome"),
        "evidence_state": row.get("evidence_state"),
        "injected_count": row.get("injected_count"),
        "seen_count": row.get("seen_count"),
        "operator_disposition": row.get("operator_disposition"),
        "metadata": {
            "result": row.get("result"),
            "tags": row.get("tags") or [],
            "timestamp": row.get("timestamp") or "",
        },
        "created_at": row.get("created_at") or "",
        "updated_at": row.get("created_at") or "",
    }


def _to_contracts(kb, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量映射：一次 GROUP BY 拿到全部 (agent_id, skill_name) 的真实条数。

    计数键直接从行里取，与 `experience_counts_by_skill` 同源，所以不做兜底默认——
    键对不上就是聚合口径裂了，得炸出来而不是显示 1。
    """
    counts = kb.experience_counts_by_skill()
    return [
        _to_contract(r, counts[(r.get("agent_id"), r.get("skill_name"))]) for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Endpoints
# ─────────────────────────────────────────────────────────────────────────────


@router.post("/records")
async def add_experience_record(body: AddExperienceRecordRequest):
    """添加经验记录（手动结晶：写入真实 SQLite 库，供后续检索/统计）"""
    from neurova.skills.models import ExperienceRecord

    exp = ExperienceRecord(
        skill_name=body.task_type,
        context={"user_input": body.context, "task_type": body.task_type},
        result=body.metadata or {},
        success=body.outcome != "failure",
        timestamp="",
        feedback="\n".join(body.lessons or []),
    )
    try:
        rid = get_experience_kb().add_experience_record(
            skill_name=body.task_type,
            exp=exp,
            agent_id=body.agent_id,
            confidence_score=1.0 if exp.success else 0.0,
            tags=list((body.metadata or {}).get("tags", [])) or None,
        )
    except Exception as e:
        logger.exception("add experience record failed: %s", e)
        raise HTTPException(status_code=500, detail=f"add experience record failed: {e}")

    # 回读落库后的真实行：命中内容门合并时返回的是既有行，手拼一份"看起来对"的
    # 字典只会让契约与库里不一致（experience_count 就是这么变成假的）
    kb = get_experience_kb()
    return {
        "code": 0,
        "message": "Record added",
        "data": _to_contracts(kb, [kb.get_record_by_id(rid)])[0],
    }


@router.get("/ranking")
async def get_experience_ranking(
    agent_id: str = Query(default="", description="Agent ID"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    task_type: Optional[str] = Query(default=None),
):
    """经验记录分页列表（skill_name 侧按 task_type 过滤）"""
    try:
        kb = get_experience_kb()
        records = kb.get_experience_records(
            skill_name=task_type or "",
            agent_id=agent_id or None,
        )
        total = len(records)
        start = (page - 1) * size
        items = _to_contracts(kb, records[start : start + size])
        return {
            "code": 0,
            "message": "success",
            "data": {"items": items, "total": total, "page": page, "size": size},
        }
    except Exception as e:
        logger.exception("get experience ranking failed: %s", e)
        raise HTTPException(status_code=500, detail=f"get experience ranking failed: {e}")


@router.get("/stats")
async def get_experience_stats(agent_id: str = Query(default="")):
    """经验库统计（前端 ExperienceStats 契约）"""
    try:
        kb = get_experience_kb()
        records = kb.get_experience_records(agent_id=agent_id or None)
        total = len(records)
        successes = sum(1 for r in records if r.get("success"))
        proficiency_values = [
            float(r.get("confidence_score") or 0) for r in records if r.get("confidence_score") is not None
        ]
        avg_proficiency = round(sum(proficiency_values) / len(proficiency_values), 4) if proficiency_values else 0.0
        counts: Dict[str, int] = {}
        for r in records:
            key = r.get("skill_name") or "unknown"
            counts[key] = counts.get(key, 0) + 1
        top_categories = sorted(
            [{"category": k, "count": v} for k, v in counts.items()],
            key=lambda c: c["count"], reverse=True,
        )[:8]
        return {
            "code": 0,
            "message": "success",
            "data": {
                "total_experiences": total,
                "success_rate": round(successes / total, 4) if total else 0.0,
                "avg_proficiency": avg_proficiency,
                "top_categories": top_categories,
            },
        }
    except Exception as e:
        logger.exception("get experience stats failed: %s", e)
        raise HTTPException(status_code=500, detail=f"get experience stats failed: {e}")


@router.post("/similar")
async def find_similar_experiences(body: FindSimilarExperiencesRequest):
    """查找与查询文本相似的经验记录（EKB 关键词/话题/成功加权算法）"""
    try:
        kb = get_experience_kb()
        results = kb.find_similar_experiences(
            context={"user_input": body.query},
            limit=body.limit,
            agent_id=body.agent_id or None,
        )
        return {
            "code": 0,
            "message": "success",
            "data": {"results": _to_contracts(kb, results), "total": len(results)},
        }
    except Exception as e:
        logger.exception("find similar experiences failed: %s", e)
        raise HTTPException(status_code=500, detail=f"find similar experiences failed: {e}")


@router.get("/{record_id}")
async def get_experience(record_id: str):
    """单条经验记录"""
    kb = get_experience_kb()
    try:
        record = kb.get_record_by_id(int(record_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid record id")
    except Exception as e:
        logger.exception("get experience failed: %s", e)
        raise HTTPException(status_code=500, detail=f"get experience failed: {e}")
    if record is None:
        raise HTTPException(status_code=404, detail="experience record not found")
    return {"code": 0, "message": "success", "data": _to_contracts(kb, [record])[0]}


@router.put("/{record_id}/disposition")
async def set_experience_disposition(record_id: str, body: ExperienceDispositionRequest):
    """人工处置单条经验（工单 015）：审核通过 / 降权 / 隐藏 / 恢复未处置。

    处置走 EKB 的 `operator_disposition` 列，与检索排序、注入优先级同一条链
    （`find_similar_experiences` / `dedupe_experience_sources`），不是在响应里
    编一个态。全程可逆、不删行、不写采纳证据列。
    """
    kb = get_experience_kb()
    try:
        rid = int(record_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid record id")
    record = kb.get_record_by_id(rid)
    if record is None:
        raise HTTPException(status_code=404, detail="experience record not found")
    try:
        kb.set_operator_disposition([rid], body.disposition)
    except Exception as e:
        logger.exception("set experience disposition failed: %s", e)
        raise HTTPException(status_code=500, detail=f"set experience disposition failed: {e}")
    return {
        "code": 0,
        "message": "Disposition updated",
        "data": _to_contracts(kb, [kb.get_record_by_id(rid)])[0],
    }


@router.delete("/{record_id}")
async def delete_experience(record_id: str):
    """删除经验记录"""
    try:
        deleted = get_experience_kb().delete_record(int(record_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid record id")
    except Exception as e:
        logger.exception("delete experience failed: %s", e)
        raise HTTPException(status_code=500, detail=f"delete experience failed: {e}")
    if not deleted:
        raise HTTPException(status_code=404, detail="experience record not found")
    return {"code": 0, "message": "deleted", "data": None}
