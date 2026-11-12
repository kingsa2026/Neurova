# -*- coding: utf-8 -*-
"""Diagnostics API — 只读诊断面（P2-16，拍板：补只读诊断口）。

CrystallizedExperienceManager 的 observe/get_health/add_failure_callback/
clear_cache 此前全仓零消费、_metrics 只写不读（全库断点审计 2026-11-12
P2-16）。本面把健康状态与检索指标暴露成**只读**诊断口（admin 门），
不含任何写动作。
"""
from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from neurova.api.deps import require_admin

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


def _collect() -> List[Dict[str, Any]]:
    """从运行时 Agent 注册表收集各 agent 的结晶管理器诊断读数。"""
    from neurova.api.endpoints import get_app_state

    agents = (get_app_state() or {}).get("agents") or {}
    out: List[Dict[str, Any]] = []
    for agent_id, agent in agents.items():
        pipeline = getattr(agent, "chat_pipeline", None)
        manager = getattr(pipeline, "_crystallized_experience_manager", None)
        if manager is None:
            continue
        out.append(
            {
                "agent_id": agent_id,
                "health": manager.get_health().value,
                "metrics": asdict(manager.metrics),
            }
        )
    return out


@router.get("/crystallized")
async def crystallized_diagnostics(
    _admin: Dict[str, Any] = Depends(require_admin()),
):
    """结晶经验管理器只读诊断（健康状态＋检索指标，按 agent 列出）。"""
    agents = _collect()
    return {
        "code": 0,
        "message": "success",
        "data": {"agents": agents, "total": len(agents)},
    }
