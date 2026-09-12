from __future__ import annotations

"""
轨迹追踪接口 - Trace Endpoint

数据源（2026-09-12 台账清剿 P2）：chat 管线真实记录器 TrajectoryRecorder
（neurova/core/trace_recorder.py，trajectories/<user>/<agent>/<session>/<trace>.json）。
本文件此前自带一套进程内 TraceManager 平行假存储（全仓零写入方 → 列表恒空、
详情恒 404），与真实链路完全脱钩，已删除；响应形状对齐前端 api/modules/trace.ts：

1. GET /api/v1/trace          列表 {id,name,status,duration_ms,steps_count,started_at}
2. GET /api/v1/trace/stats    {total,avg_duration_ms,success_rate,avg_steps}
3. GET /api/v1/trace/{id}     详情 + tool_calls/llm_calls/breakdown/events
4. GET /api/v1/trace/{id}/events  事件时间轴（同详情 events 字段，兼容保留）
5. GET /api/v1/trace/{id}/export  JSON 附件（FE exportTrace 原调此路后端缺失）

鉴权（BUG AUDIT S-08 契约保持）：全端点登录即可（非 admin 页面）。
"""

from neurova.core.logger import get_logger
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from neurova.api.deps import get_current_user

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)


class TraceListItem(BaseModel):
    """列表条目（FE TraceItem 契约）"""

    id: str
    name: str = ""
    status: str = "completed"
    duration_ms: float = 0.0
    steps_count: int = 0
    started_at: Optional[str] = None


class TraceStatsOut(BaseModel):
    """统计（FE TraceStats 契约）"""

    total: int = 0
    avg_duration_ms: float = 0.0
    success_rate: float = 0.0
    avg_steps: float = 0.0


def _recorder():
    from neurova.core.trace_recorder import get_trajectory_recorder

    return get_trajectory_recorder()


def _derive_status(stats: Dict[str, Any]) -> str:
    """stats.status 是 span 状态计数 dict，派生轨迹级状态"""
    counts = stats.get("status") or {}
    if isinstance(counts, str):
        return counts
    if counts.get("error") or counts.get("failed"):
        return "failed"
    if counts.get("running"):
        return "running"
    return "completed"


def _entry_to_item(entry: Dict[str, Any]) -> TraceListItem:
    stats = entry.get("stats") or {}
    return TraceListItem(
        id=entry.get("trace_id", ""),
        name=entry.get("session_id", "") or "",
        status=_derive_status(stats),
        duration_ms=float(entry.get("duration_ms", 0.0) or 0.0),
        steps_count=int(stats.get("span_count", 0) or 0),
        started_at=entry.get("created_at"),
    )


def _flatten_events(trace_dict: Dict[str, Any]) -> List[Dict[str, Any]]:
    """展平全部 span 的事件（时间升序）为 FE TraceEvent 形状。

    不能只走 root_span.child_spans 树：Trajectory.add_span 仅对
    parent_span_id 命中的 span 挂树，无父 span 是孤儿（chat 管线多数
    span 即如此），走树会丢工具/LLM 事件。spans dict 才是全量事实源。
    """
    events: List[Dict[str, Any]] = []
    for span_dict in (trace_dict.get("spans") or {}).values():
        for ev in span_dict.get("events") or []:
            data = ev.get("data") or {}
            message = ""
            for key in ("user_input", "error_message", "reply_length", "result", "message"):
                if data.get(key):
                    message = str(data[key])[:200]
                    break
            events.append({
                "type": str(ev.get("event_type", "info")),
                "timestamp": str(ev.get("timestamp", "")),
                "message": message,
                "data": data,
                "duration_ms": float(ev.get("duration_ms", 0.0) or 0.0),
            })
    events.sort(key=lambda e: e["timestamp"] or "")
    return events


def _build_detail(trace_dict: Dict[str, Any], trace_id: str) -> Dict[str, Any]:
    stats = trace_dict.get("stats") or {}
    events = _flatten_events(trace_dict)

    tool_calls = [
        {
            "tool": e["data"].get("tool_name", "unknown"),
            "name": e["data"].get("tool_name", "unknown"),
            "duration_ms": float(e["data"].get("execution_time", e.get("duration_ms", 0.0)) or 0.0),
            "success": bool(e["data"].get("success", e["type"] != "tool_call_error")),
        }
        for e in events
        if e["type"] in ("tool_call_end", "tool_call_error")
    ]
    llm_calls = [
        {
            "model": e["data"].get("model", e["data"].get("model_name", "")),
            "tokens_in": int(e["data"].get("input_tokens", 0) or 0),
            "tokens_out": int(e["data"].get("output_tokens", 0) or 0),
            "duration_ms": float(e["data"].get("duration_ms", 0.0) or 0.0),
        }
        for e in events
        if e["type"] == "llm_call_end"
    ]
    return {
        "id": trace_id,
        "name": trace_dict.get("session_id", "") or "",
        "status": _derive_status(stats),
        "duration_ms": float(trace_dict.get("total_duration_ms", 0.0) or 0.0),
        "steps_count": int(stats.get("span_count", 0) or 0),
        "started_at": trace_dict.get("start_time"),
        "agent_id": trace_dict.get("agent_id", ""),
        "session_id": trace_dict.get("session_id", ""),
        "tool_calls": tool_calls,
        "llm_calls": llm_calls,
        "breakdown": {
            "tool_ms": round(sum(t["duration_ms"] for t in tool_calls), 2),
            "llm_ms": round(sum(l["duration_ms"] for l in llm_calls), 2),
            "total": float(trace_dict.get("total_duration_ms", 0.0) or 0.0),
        },
        "events": events,
    }


@router.get("", response_model=List[TraceListItem])
async def get_traces(
    agent_id: str = Query(default="default", description="Agent ID"),
    limit: int = Query(default=50, ge=1, le=200, description="数量限制"),
):
    """获取轨迹列表（真实数据源：TrajectoryRecorder 落盘轨迹）"""
    try:
        entries = _recorder().list_traces(agent_id=agent_id, limit=limit)
        items = [_entry_to_item(e) for e in entries]
        items.sort(key=lambda i: i.started_at or "", reverse=True)
        return items
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to get traces: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get traces: {str(e)}")


@router.get("/stats", response_model=TraceStatsOut)
async def get_trace_stats(
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取轨迹统计（聚合真实轨迹）"""
    try:
        items = [_entry_to_item(e) for e in _recorder().list_traces(agent_id=agent_id, limit=1000)]
        if not items:
            return TraceStatsOut()
        total = len(items)
        completed = sum(1 for i in items if i.status == "completed")
        return TraceStatsOut(
            total=total,
            avg_duration_ms=round(sum(i.duration_ms for i in items) / total, 2),
            success_rate=round(completed / total, 4),
            avg_steps=round(sum(i.steps_count for i in items) / total, 2),
        )
    except Exception as e:  # noqa: BLE001
        logger.exception("Failed to get trace stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get trace stats: {str(e)}")


@router.get("/{trace_id}")
async def get_trace(trace_id: str = Path(..., description="轨迹ID")):
    """获取单个轨迹详情（tool_calls/llm_calls/breakdown/events 按 FE TraceDetail 契约）"""
    trace = _recorder().load_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return _build_detail(trace.to_dict(), trace_id)


@router.get("/{trace_id}/events")
async def get_trace_events(trace_id: str = Path(..., description="轨迹ID")):
    """获取轨迹事件时间轴（S-08 契约路由保留；数据源同详情 events）"""
    trace = _recorder().load_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return _build_detail(trace.to_dict(), trace_id)["events"]


@router.get("/{trace_id}/export")
async def export_trace(trace_id: str = Path(..., description="轨迹ID")):
    """导出完整轨迹 JSON（FE exportTrace 按钮；原后端无此路由恒 404）"""
    trace = _recorder().load_trace(trace_id)
    if trace is None:
        raise HTTPException(status_code=404, detail=f"Trace '{trace_id}' not found")
    return JSONResponse(
        content=trace.to_dict(),
        headers={"Content-Disposition": f"attachment; filename=trace_{trace_id}.json"},
    )
