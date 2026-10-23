"""会话质量事件与指标 API。"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_service
from neurova.quality import get_quality_store

router = APIRouter()


class TurnOutcomeRequest(BaseModel):
    turn_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    agent_id: str = ""
    channel: str = ""
    outcome: Literal[
        "answered", "safety_refusal", "insufficient_evidence",
        "tool_failure", "handoff", "unknown",
    ]
    occurred_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class QualityEventRequest(BaseModel):
    event_type: Literal["human_takeover_started", "human_takeover_ended"]
    session_id: str = Field(..., min_length=1)
    agent_id: str = ""
    channel: str = ""
    source: Literal["channel_event", "console_mark", "api"] = "console_mark"
    source_event_id: str = ""
    actor_id: str = ""
    reason_code: str = ""
    occurred_at: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


@router.post("/outcomes")
async def record_quality_event(
    body: QualityEventRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """写一条人工接管事件；管理员/服务身份，幂等键 (source, source_event_id)。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="质量事件写入仅限管理员/服务身份")
    try:
        event = get_quality_store().recordEvent(
            body.event_type, body.session_id,
            agentId=body.agent_id, channel=body.channel, source=body.source,
            sourceEventId=body.source_event_id,
            actorId=body.actor_id or str(
                current_user.get("username") or current_user.get("user_id") or ""
            ),
            reasonCode=body.reason_code, occurredAt=body.occurred_at,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "ok", "data": event}


@router.post("/turn-outcomes")
async def record_turn_outcome(
    body: TurnOutcomeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """显式写一轮 TurnOutcome（tool_failure/handoff 等只认这条通道）。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="完成态写入仅限管理员/服务身份")
    try:
        event = get_quality_store().recordTurnOutcome(
            body.turn_id, body.session_id,
            agentId=body.agent_id, channel=body.channel,
            outcome=body.outcome, source="explicit_api",
            occurredAt=body.occurred_at, metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"code": 0, "message": "ok", "data": event}


@router.get("/sessions/{session_id}/takeover")
async def get_session_takeover_state(
    session_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """控制台恢复按钮状态：最近一次接管事件是开始还是结束。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="接管状态仅限管理员")
    return {
        "code": 0,
        "message": "ok",
        "data": get_quality_store().takeoverState(session_id),
    }


@router.get("/metrics")
async def get_quality_metrics(
    window_seconds: int = Query(default=7 * 86400, ge=60, le=90 * 86400),
    current_user: Dict[str, Any] = Depends(get_current_user_or_service),
):
    """会话质量 + token 归因读数；没有分母的率返回 None，不伪造 0。"""
    if str(current_user.get("role") or "") != "admin":
        raise HTTPException(status_code=403, detail="质量指标仅限管理员")
    data = get_quality_store().metrics(window_seconds)
    data["token_usage"] = None
    try:
        from neurova.knowledge.foundation import get_knowledge_fact_store

        data["token_usage"] = get_knowledge_fact_store().tokenUsageMetrics()
    except Exception as exc:  # noqa: BLE001 — 指标读取失败不阻断端点，但要点名
        data["token_usage_missing_reason"] = str(exc)
    # 渠道能力位是「为什么某些渠道没有接管事件」的读面：有原生事件的
    # 渠道进 supported，其余进 unsupported；空清单也只说明未注册，不是全渠道不支持。
    try:
        from neurova.channels.manager import get_channel_manager

        adapters = get_channel_manager().list_adapters()
        data["takeover_channel_capability"] = {
            "supported": sorted(
                key for key, info in adapters.items()
                if info.get("human_takeover_events")
            ),
            "unsupported": sorted(
                key for key, info in adapters.items()
                if not info.get("human_takeover_events")
            ),
            "reasons": {
                key: str(info.get("human_takeover_reason") or "")
                for key, info in adapters.items()
            },
        }
    except Exception as exc:  # noqa: BLE001 — 渠道状态读不到不阻断质量读数，但要点名
        data["takeover_channel_capability_missing_reason"] = str(exc)
    return {"code": 0, "message": "ok", "data": data}
