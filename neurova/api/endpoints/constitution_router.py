"""宪法端点（GET/PUT /constitution、GET/POST /constitution/rules、PUT/DELETE /constitution/rules/{id}）。

2026-09-16 自 growth.py 拆出；路径与响应契约不变
（envelope 契约见 test_growth_envelope_consistency.py）。
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from neurova.api.auth import get_current_user, Depends
from neurova.api.endpoints._pydantic_compat import safe_model_dump
from neurova.api.endpoints.constitution_persistence import (
    ConstitutionRuleCreate,
    ConstitutionRuleUpdate,
    load_constitution_rules,
    rule_to_model,
    save_constitution_rules,
)
from neurova.api.endpoints.growth_common import envelope, get_agent, get_request_id

router = APIRouter(dependencies=[Depends(get_current_user)])


def _not_found(agent_id: str):
    return HTTPException(status_code=404, detail=f"Agent '{agent_id}' not found")


@router.get("/constitution")
async def get_constitution(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取宪法信息（overview，读持久源）"""
    request_id = get_request_id(request)
    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    return envelope(request_id, {"constitution": load_constitution_rules(agent_id)})


@router.put("/constitution")
async def update_constitution(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    constitution: List[Dict[str, Any]] = [],
):
    """整表更新宪法（落盘）"""
    request_id = get_request_id(request)

    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    save_constitution_rules(agent_id, constitution)
    return envelope(request_id, {"constitution": constitution}, message="Constitution updated")


@router.get("/constitution/rules")
async def get_constitution_rules(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
):
    """获取宪法规则列表（envelope.data 为列表，与 /reflection /questions /proactive 同族契约）"""
    request_id = get_request_id(request)
    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    return envelope(request_id, [safe_model_dump(rule_to_model(agent_id, r)) for r in load_constitution_rules(agent_id)])


@router.post("/constitution/rules")
async def add_constitution_rule(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    body: ConstitutionRuleCreate = ConstitutionRuleCreate(content=""),
):
    """添加宪法规则（envelope.data 为创建后的 ConstitutionRule dict）"""
    request_id = get_request_id(request)

    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    rule = {
        "rule_id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "rule_type": body.rule_type,
        "content": body.content,
        "priority": body.priority,
        "enabled": body.enabled if body.enabled is not None else True,
    }
    rules = load_constitution_rules(agent_id)
    rules.append(rule)
    save_constitution_rules(agent_id, rules)

    return envelope(request_id, safe_model_dump(rule_to_model(agent_id, rule)))


@router.put("/constitution/rules/{rule_id}")
async def update_constitution_rule(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    rule_id: str = Path(..., description="规则ID"),
    body: ConstitutionRuleUpdate = ConstitutionRuleUpdate(),
):
    """更新宪法规则（局部：只改请求里出现的键）"""
    request_id = get_request_id(request)

    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    updates = {k: v for k, v in safe_model_dump(body).items() if v is not None}
    rules = load_constitution_rules(agent_id)
    for rule in rules:
        if rule.get("rule_id") == rule_id:
            rule.update(updates)
            save_constitution_rules(agent_id, rules)
            return envelope(request_id, safe_model_dump(rule_to_model(agent_id, rule)))

    raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")


@router.delete("/constitution/rules/{rule_id}")
async def delete_constitution_rule(
    request: Request,
    agent_id: str = Query(default="default", description="Agent ID"),
    rule_id: str = Path(..., description="规则ID"),
):
    """删除宪法规则"""
    request_id = get_request_id(request)

    agent = get_agent(agent_id)
    if not agent:
        raise _not_found(agent_id)

    rules = load_constitution_rules(agent_id)
    remaining = [r for r in rules if r.get("rule_id") != rule_id]
    if len(remaining) == len(rules):
        raise HTTPException(status_code=404, detail=f"Rule '{rule_id}' not found")
    save_constitution_rules(agent_id, remaining)
    return envelope(request_id, {"rule_id": rule_id}, message=f"Rule '{rule_id}' deleted")
