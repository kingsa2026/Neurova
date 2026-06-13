from __future__ import annotations

"""
记忆增强接口 - Memory Enhancement Endpoint

功能:
1. 遗忘记忆 (POST /api/v1/memories/{id}/forget)
2. 强化记忆 (POST /api/v1/memories/{id}/strengthen)
3. 记忆分类 (GET /api/v1/memories/categories)
4. 批量操作 (POST /api/v1/memories/batch)
5. 记忆导出 (GET /api/v1/memories/export)
6. 记忆导入 (POST /api/v1/memories/import)
"""

import datetime
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic Models
# ---------------------------------------------------------------------------


class ForgetMemoryRequest(BaseModel):
    """遗忘记忆请求"""

    reason: str = Field(default="", description="遗忘原因")
    importance_threshold: float = Field(default=0.3, description="重要性阈值")


class StrengthenMemoryRequest(BaseModel):
    """强化记忆请求"""

    importance_boost: float = Field(default=0.2, description="重要性提升值")
    reason: str = Field(default="", description="强化原因")


class BatchMemoryOperationRequest(BaseModel):
    """批量记忆操作请求"""

    memory_ids: List[str] = Field(..., description="记忆ID列表")
    operation: str = Field(..., description="操作类型: forget/strengthen/delete")
    params: Dict[str, Any] = Field(default_factory=dict, description="操作参数")


class ImportMemoriesRequest(BaseModel):
    """导入记忆请求"""

    memories: List[Dict[str, Any]] = Field(..., description="记忆列表")
    merge_mode: str = Field(default="skip", description="合并模式: skip/overwrite/merge")


class MemoryCategory(BaseModel):
    """记忆分类"""

    category: str
    count: int
    avg_importance: float


# ---------------------------------------------------------------------------
# In-Memory Store
# ---------------------------------------------------------------------------

_memories_store: Dict[str, Dict[str, Any]] = {}


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_memory_manager():
    """获取记忆管理器"""
    try:
        from neurova.api.endpoints import get_agent_instance

        agent = get_agent_instance()
        if agent and hasattr(agent, "memory_manager"):
            return agent.memory_manager
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/{memory_id}/forget")
async def forget_memory(
    request: Request,
    memory_id: str,
    body: ForgetMemoryRequest,
):
    """遗忘记忆 - 降低记忆的重要性，使其更容易被遗忘"""
    request_id = _get_request_id(request)

    # 尝试使用记忆管理器
    mm = _get_memory_manager()
    if mm and hasattr(mm, "forget_memory"):
        try:
            result = await mm.forget_memory(memory_id, reason=body.reason)
            return {
                "code": 0,
                "message": f"Memory '{memory_id}' forgotten",
                "data": result,
                "request_id": request_id,
            }
        except Exception as e:
            logger.warning("MemoryManager.forget_memory failed: %s", e)

    # 使用内存存储
    memory = _memories_store.get(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")

    # 降低重要性
    current_importance = memory.get("importance", 0.5)
    new_importance = max(0.0, current_importance - 0.3)
    memory["importance"] = new_importance
    memory["forget_count"] = memory.get("forget_count", 0) + 1
    memory["last_forgotten"] = time.time()

    return {
        "code": 0,
        "message": f"Memory '{memory_id}' importance reduced to {new_importance}",
        "data": {
            "memory_id": memory_id,
            "old_importance": current_importance,
            "new_importance": new_importance,
        },
        "request_id": request_id,
    }


@router.post("/{memory_id}/strengthen")
async def strengthen_memory(
    request: Request,
    memory_id: str,
    body: StrengthenMemoryRequest,
):
    """强化记忆 - 提高记忆的重要性，使其更难被遗忘"""
    request_id = _get_request_id(request)

    # 尝试使用记忆管理器
    mm = _get_memory_manager()
    if mm and hasattr(mm, "strengthen_memory"):
        try:
            result = await mm.strengthen_memory(memory_id, boost=body.importance_boost)
            return {
                "code": 0,
                "message": f"Memory '{memory_id}' strengthened",
                "data": result,
                "request_id": request_id,
            }
        except Exception as e:
            logger.warning("MemoryManager.strengthen_memory failed: %s", e)

    # 使用内存存储
    memory = _memories_store.get(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")

    # 提高重要性
    current_importance = memory.get("importance", 0.5)
    new_importance = min(1.0, current_importance + body.importance_boost)
    memory["importance"] = new_importance
    memory["strengthen_count"] = memory.get("strengthen_count", 0) + 1
    memory["last_strengthened"] = time.time()

    return {
        "code": 0,
        "message": f"Memory '{memory_id}' importance increased to {new_importance}",
        "data": {
            "memory_id": memory_id,
            "old_importance": current_importance,
            "new_importance": new_importance,
        },
        "request_id": request_id,
    }


@router.get("/categories", response_model=List[MemoryCategory])
async def get_memory_categories(
    request: Request,
):
    """获取记忆分类列表"""
    _get_request_id(request)

    # 统计分类
    categories: Dict[str, Dict[str, Any]] = {}
    for memory in _memories_store.values():
        category = memory.get("category", "general")
        if category not in categories:
            categories[category] = {"count": 0, "total_importance": 0.0}
        categories[category]["count"] += 1
        categories[category]["total_importance"] += memory.get("importance", 0.5)

    result = []
    for category, stats in categories.items():
        avg_importance = stats["total_importance"] / stats["count"] if stats["count"] > 0 else 0.0
        result.append(
            MemoryCategory(
                category=category,
                count=stats["count"],
                avg_importance=round(avg_importance, 2),
            )
        )

    return result


@router.post("/batch")
async def batch_memory_operation(
    request: Request,
    body: BatchMemoryOperationRequest,
):
    """批量操作记忆"""
    request_id = _get_request_id(request)

    results = []
    errors = []

    for memory_id in body.memory_ids:
        memory = _memories_store.get(memory_id)
        if not memory:
            errors.append({"memory_id": memory_id, "error": "Not found"})
            continue

        try:
            if body.operation == "forget":
                body.params.get("importance_threshold", 0.3)
                memory["importance"] = max(0.0, memory.get("importance", 0.5) - 0.3)
                results.append({"memory_id": memory_id, "operation": "forget", "success": True})

            elif body.operation == "strengthen":
                boost = body.params.get("importance_boost", 0.2)
                memory["importance"] = min(1.0, memory.get("importance", 0.5) + boost)
                results.append({"memory_id": memory_id, "operation": "strengthen", "success": True})

            elif body.operation == "delete":
                del _memories_store[memory_id]
                results.append({"memory_id": memory_id, "operation": "delete", "success": True})

            else:
                errors.append({"memory_id": memory_id, "error": f"Unknown operation: {body.operation}"})

        except Exception as e:
            errors.append({"memory_id": memory_id, "error": str(e)})

    return {
        "code": 0,
        "message": f"Processed {len(results)} memories, {len(errors)} errors",
        "data": {
            "results": results,
            "errors": errors,
        },
        "request_id": request_id,
    }


@router.get("/export")
async def export_memories(
    request: Request,
    format: str = Query(default="json", description="导出格式: json/csv"),
    category: Optional[str] = Query(default=None, description="按分类筛选"),
    min_importance: Optional[float] = Query(default=None, description="最小重要性"),
):
    """导出记忆数据"""
    request_id = _get_request_id(request)

    memories = list(_memories_store.values())

    if category:
        memories = [m for m in memories if m.get("category") == category]
    if min_importance is not None:
        memories = [m for m in memories if m.get("importance", 0) >= min_importance]

    if format == "csv":
        import csv
        import io

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["memory_id", "content", "category", "importance", "created_at"])

        for memory in memories:
            writer.writerow(
                [
                    memory.get("memory_id", ""),
                    memory.get("content", ""),
                    memory.get("category", ""),
                    memory.get("importance", ""),
                    datetime.datetime.fromtimestamp(memory.get("created_at", 0)).isoformat(),
                ]
            )

        from fastapi.responses import StreamingResponse

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=memories.csv"},
        )

    return {
        "code": 0,
        "data": {
            "memories": memories,
            "total": len(memories),
        },
        "request_id": request_id,
    }


@router.post("/import")
async def import_memories(
    request: Request,
    body: ImportMemoriesRequest,
):
    """导入记忆数据"""
    request_id = _get_request_id(request)

    imported = 0
    skipped = 0
    errors = []

    for memory_data in body.memories:
        memory_id = memory_data.get("memory_id") or str(uuid.uuid4())

        if memory_id in _memories_store:
            if body.merge_mode == "skip":
                skipped += 1
                continue
            elif body.merge_mode == "overwrite":
                pass  # 继续导入，覆盖现有
            elif body.merge_mode == "merge":
                # 合并现有记忆
                existing = _memories_store[memory_id]
                existing.update(memory_data)
                imported += 1
                continue

        memory_data["memory_id"] = memory_id
        memory_data["imported_at"] = time.time()
        _memories_store[memory_id] = memory_data
        imported += 1

    return {
        "code": 0,
        "message": f"Imported {imported} memories, skipped {skipped}",
        "data": {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
        },
        "request_id": request_id,
    }
