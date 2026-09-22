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

事实源纪律（Issue #128 / F-17）：
本模块**不得**持有任何进程内记忆副本。六条端点一律经
`neurova.api.endpoints.memory.base.get_memory_manager` 读写真 `MemoryManager`
（与 `/v1/memory` 同一装配点、同一请求作用域注入口径）。

历史事故：本模块曾维护模块级 `_memories_store: Dict[str, Dict[str, Any]] = {}`，
它从不被任何生产写入路径填充、读取侧也永不可见 —— 于是「导入成功」「遗忘成功」
「导出为空」全是假成功：返回 200 与计数，真记忆库纹丝不动。该影子字典已整体
删除（不是"接上"，是删掉第二事实源）。
"""

import csv
import datetime
import io
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user
from neurova.core.logger import get_logger
from neurova.interfaces.api_standard import APIError

logger = get_logger(__name__)
router = APIRouter(dependencies=[Depends(get_current_user)],)

# 重要性量纲（唯一事实源，勿在本模块另立）：
# MemoryManager 侧 `Memory.importance` 取 0-100，而本模块对外契约
# （Pydantic 模型默认值 0.3/0.2、前端 `importance_boost = 0.2`）取 0-1 分数。
# 换算是本模块的对外适配职责，两侧都不改量纲。
IMPORTANCE_SCALE = 100.0
IMPORTANCE_MIN = 0.0
IMPORTANCE_MAX = 100.0
# 对外 0-1 合同下的边界
BOOST_MIN = 0.0
BOOST_MAX = 1.0


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
# 装配点与量纲适配
# ---------------------------------------------------------------------------


def _require_memory_manager(request: Request):
    """取真 MemoryManager —— 唯一装配点，禁用影子兜底。

    与 `/v1/memory` 走同一函数：既保证 agent 解析口径一致，也保证
    `set_request_scope` 请求作用域注入生效（跨用户隔离不能靠端点自觉）。

    取不到时**显式 503**，绝不静默回落到任何进程内副本 —— 假成功比报错更有害。
    """
    from neurova.api.endpoints.memory.base import get_memory_manager

    try:
        manager = get_memory_manager(None, getattr(request.state, "user", None))
    except APIError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"记忆系统不可用: {exc}",
        ) from exc
    if manager is None:
        raise HTTPException(status_code=503, detail="记忆系统不可用")
    return manager


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", "") or ""


def _toApiImportance(raw: Any, default: float) -> float:
    """把真库 0-100 量纲的 importance 换成对外 0-1 合同。"""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return round(min(BOOST_MAX, max(BOOST_MIN, value / IMPORTANCE_SCALE)), 4)


def _toStoreImportance(raw: Any, fallback: float) -> float:
    """把对外 0-1 的分数换成真库 0-100 量纲。"""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return fallback
    return min(IMPORTANCE_MAX, max(IMPORTANCE_MIN, value * IMPORTANCE_SCALE))


def _notFound(memory_id: str) -> HTTPException:
    # 真库不存在即 404（含越权视同不存在，与 manager 的归属校验同口径）
    return HTTPException(status_code=404, detail=f"Memory '{memory_id}' not found")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/{memory_id}/forget")
async def forget_memory(
    request: Request,
    memory_id: str,
    body: ForgetMemoryRequest,
):
    """遗忘记忆 - 真库软删（lifecycle_stage → forgotten）"""
    manager = _require_memory_manager(request)

    # 先按管理页口径确认存在，以便区分"不存在"与"落库失败"
    existing = manager.get_memory(memory_id, agent_wide=True)
    if not existing:
        raise _notFound(memory_id)

    if not manager.forget(memory_id, soft=True, agent_wide=True):
        # 存在却在归属校验处被拒 = 越权，对外与不存在同口径，不泄漏归属信息
        logger.warning("forget 被拒绝（归属校验）: id=%s", memory_id)
        raise _notFound(memory_id)

    after = manager.get_memory(memory_id, agent_wide=True) or {}
    return {
        "code": 0,
        "message": f"Memory '{memory_id}' forgotten",
        "data": {
            "memory_id": memory_id,
            "old_importance": _toApiImportance(existing.get("importance"), 0.5),
            "new_importance": _toApiImportance(after.get("importance"), 0.5),
            "lifecycle_stage": after.get("lifecycle_stage", "forgotten"),
            "reason": body.reason,
        },
    }


@router.post("/{memory_id}/strengthen")
async def strengthen_memory(
    request: Request,
    memory_id: str,
    body: StrengthenMemoryRequest,
):
    """强化记忆 - 真库抬高 importance（0-100 量纲）"""
    manager = _require_memory_manager(request)

    existing = manager.get_memory(memory_id, agent_wide=True)
    if not existing:
        raise _notFound(memory_id)

    # 对外 0-1 分数 → 真库 0-100 量纲的增量
    boost = min(BOOST_MAX, max(BOOST_MIN, float(body.importance_boost)))
    before_raw = existing.get("importance")
    before = float(before_raw) if isinstance(before_raw, (int, float)) else 50.0
    after = min(IMPORTANCE_MAX, before + boost * IMPORTANCE_SCALE)

    if not manager.update_memory(memory_id, importance=after):
        logger.warning("strengthen 落库失败: id=%s", memory_id)
        raise _notFound(memory_id)

    return {
        "code": 0,
        "message": f"Memory '{memory_id}' strengthened",
        "data": {
            "memory_id": memory_id,
            "old_importance": _toApiImportance(before, 0.5),
            "new_importance": _toApiImportance(after, 0.5),
            "reason": body.reason,
        },
    }


@router.get("/categories", response_model=List[MemoryCategory])
async def get_memory_categories(request: Request):
    """获取记忆分类列表 —— 真库只读聚合（与 /v1/memory/stats 同源读数）"""
    manager = _require_memory_manager(request)

    stats = manager.get_stats(agent_wide=True)
    by_category: Dict[str, int] = stats.get("by_category") or {}

    # 平均重要性另取一次真库列表：get_stats 只给分布计数，不给均值
    avg_importance: Dict[str, float] = {}
    totals: Dict[str, float] = {}
    for memory in manager.get_memories(agent_wide=True, limit=10000):
        category = str(memory.get("category") or "unknown")
        value = memory.get("importance")
        if isinstance(value, (int, float)):
            totals[category] = totals.get(category, 0.0) + float(value)
    for category, count in by_category.items():
        if count > 0:
            avg_importance[category] = round(
                totals.get(category, 0.0) / count / IMPORTANCE_SCALE, 4
            )

    return [
        MemoryCategory(
            category=category,
            count=count,
            avg_importance=avg_importance.get(category, 0.0),
        )
        for category, count in sorted(by_category.items())
    ]


@router.post("/batch")
async def batch_memory_operation(
    request: Request,
    body: BatchMemoryOperationRequest,
):
    """批量操作记忆 —— 逐条落真库，失败逐条点名（不回退影子副本）"""
    manager = _require_memory_manager(request)
    request_id = _get_request_id(request)

    results = []
    errors = []

    for memory_id in body.memory_ids:
        try:
            if body.operation == "forget":
                if not manager.forget(memory_id, soft=True, agent_wide=True):
                    errors.append({"memory_id": memory_id, "error": "Not found"})
                    continue
                results.append({"memory_id": memory_id, "operation": "forget", "success": True})

            elif body.operation == "strengthen":
                existing = manager.get_memory(memory_id, agent_wide=True)
                if not existing:
                    errors.append({"memory_id": memory_id, "error": "Not found"})
                    continue
                boost = float(body.params.get("importance_boost", 0.2))
                boost = min(BOOST_MAX, max(BOOST_MIN, boost))
                before_raw = existing.get("importance")
                before = float(before_raw) if isinstance(before_raw, (int, float)) else 50.0
                after = min(IMPORTANCE_MAX, before + boost * IMPORTANCE_SCALE)
                if not manager.update_memory(memory_id, importance=after):
                    errors.append({"memory_id": memory_id, "error": "Update failed"})
                    continue
                results.append({"memory_id": memory_id, "operation": "strengthen", "success": True})

            elif body.operation == "delete":
                if not manager.forget(memory_id, soft=False, agent_wide=True):
                    errors.append({"memory_id": memory_id, "error": "Not found"})
                    continue
                results.append({"memory_id": memory_id, "operation": "delete", "success": True})

            else:
                # 操作名说错必须点名失败，不能被当成"这条处理过了"
                errors.append(
                    {"memory_id": memory_id, "error": f"Unknown operation: {body.operation}"}
                )

        except Exception as e:
            logger.exception("批量记忆操作失败: id=%s op=%s", memory_id, body.operation)
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
    """导出记忆数据 —— 回读真库（读路径与 /v1/memory 同源）"""
    manager = _require_memory_manager(request)
    request_id = _get_request_id(request)

    memories = manager.get_memories(category=category, agent_wide=True, limit=10000)

    if min_importance is not None:
        threshold = _toStoreImportance(min_importance, 0.0)
        kept = []
        for memory in memories:
            value = memory.get("importance")
            if isinstance(value, (int, float)) and float(value) >= threshold:
                kept.append(memory)
        memories = kept

    if format == "csv":
        from fastapi.responses import StreamingResponse

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["memory_id", "content", "category", "importance", "created_at"])

        for memory in memories:
            writer.writerow(
                [
                    memory.get("id", ""),
                    memory.get("content", ""),
                    memory.get("category", ""),
                    _toApiImportance(memory.get("importance"), 0.5),
                    str(memory.get("created_at", "")),
                ]
            )

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
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        },
        "request_id": request_id,
    }


@router.post("/import")
async def import_memories(
    request: Request,
    body: ImportMemoriesRequest,
):
    """导入记忆数据 —— 经真 manager 写入路径落库（写入闭环）"""
    manager = _require_memory_manager(request)
    request_id = _get_request_id(request)

    imported = 0
    skipped = 0
    updated = 0
    errors: List[str] = []

    for index, memory_data in enumerate(body.memories):
        content = memory_data.get("content")
        if not content or not isinstance(content, str):
            # 没有正文的条目无法成为记忆：点名失败，不静默跳过
            errors.append(f"[{index}] 缺少 content，已拒绝")
            continue

        memory_type = memory_data.get("memory_type") or memory_data.get("type")
        payload: Dict[str, Any] = {"content": content}
        if isinstance(memory_type, str) and memory_type:
            payload["memory_type"] = memory_type
        if isinstance(memory_data.get("category"), str) and memory_data.get("category"):
            payload["category"] = memory_data["category"]
        origin = memory_data.get("origin")
        payload["origin"] = origin if isinstance(origin, str) and origin else "untrusted"
        if memory_data.get("metadata") is not None:
            payload["metadata"] = memory_data["metadata"]

        importance = memory_data.get("importance")
        if importance is not None:
            payload["importance"] = _toStoreImportance(importance, 50.0)

        existing_id = memory_data.get("memory_id") or memory_data.get("id")
        if existing_id:
            # 带 id 的条目按 merge_mode 处理：真库已有 → 覆盖/合并/跳过
            current = manager.get_memory(str(existing_id), agent_wide=True)
            if current:
                if body.merge_mode == "skip":
                    skipped += 1
                    continue
                if body.merge_mode == "merge":
                    merged = dict(payload)
                    merged.pop("content", None)  # 合并只补缺，不改写正文
                    if not manager.update_memory(str(existing_id), **merged):
                        errors.append(f"[{index}] {existing_id} 合并失败")
                        continue
                    updated += 1
                    continue
                if body.merge_mode == "overwrite":
                    if not manager.update_memory(str(existing_id), **payload):
                        errors.append(f"[{index}] {existing_id} 覆盖失败")
                        continue
                    updated += 1
                    continue

        try:
            manager.remember(**payload)
            imported += 1
        except Exception as exc:
            logger.exception("导入记忆失败: index=%s", index)
            errors.append(f"[{index}] {exc}")

    return {
        "code": 0,
        "message": f"Imported {imported} memories, updated {updated}, skipped {skipped}",
        "data": {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "errors": errors,
        },
        "request_id": request_id,
    }
