"""人格端点（GET/PUT /personality、GET /personality/traits、POST /personality/evolve）。

2026-09-16 自 growth.py 拆出；路径与响应契约不变
（envelope 契约见 test_growth_envelope_consistency.py）。
"""
from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from neurova.api.auth import get_current_user, Depends
from neurova.api.endpoints.growth_common import envelope, get_agent, get_request_id
from neurova.api.endpoints.personality_persistence import (
    PersonalityUpdate,
    load_personality_data,
    save_personality_data,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


def _not_found(agent_id: str):
    return HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


@router.get("/personality")
async def get_personality(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取人格信息（traits/values/风格读独立持久源，非 agent.personality md 文本）

    2026-09-16 契约收口：FE growth.ts 按 envelope.data 取 traits，而此端点曾
    response_model=Personality 返回裸对象 → FE .data 恒 undefined，个性档案恒空。
    与 /capabilities、/motivation 同族，统一 {code, message, data} envelope。
    """
    request_id = get_request_id(request)
    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    data = load_personality_data(agent_id)
    return envelope(request_id, {
        "agent_id": agent_id,
        "timestamp": time.time(),
        "traits": data.get("traits", {}),
        "values": data.get("values", []),
        "communication_style": data.get("communication_style", "balanced"),
        "decision_style": data.get("decision_style", "analytical"),
    })


@router.put("/personality")
async def update_personality(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: PersonalityUpdate = PersonalityUpdate(),
):
    """更新人格信息（写独立持久源并回读；envelope 同 GET，见 get_personality）"""
    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    data = load_personality_data(agent_id)
    data.update(body.dict(exclude_unset=True))
    save_personality_data(agent_id, data)
    return await get_personality(request, agent_id)


@router.get("/personality/traits")
async def get_personality_traits(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取人格特质列表"""
    request_id = get_request_id(request)
    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    return envelope(request_id, {"traits": load_personality_data(agent_id).get("traits", {})})


@router.post("/personality/evolve")
async def evolve_personality(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    learning_data: dict = {},
):
    """根据学习数据进化人格

    2026-09-12 诚实化：此前 TODO 未实现却直返成功壳（谎报 code 0）。
    """
    request_id = get_request_id(request)

    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    raise HTTPException(
        status_code=501,
        detail="人格自动进化尚未实现（Personality evolution not implemented）",
    )
