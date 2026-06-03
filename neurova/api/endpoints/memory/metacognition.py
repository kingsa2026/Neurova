"""
记忆接口 - 元认知 (Meta-cognition)
"""

from typing import Optional, List, Dict, Any

from fastapi import Request, Depends
from pydantic import BaseModel, Field

from neurova.interfaces.api_standard import (
    APIResponse,
    APIError,
)
from neurova.api.auth import get_current_user

from .base import (
    router, logger, _get_request_id, get_memory_manager, _get_user_ids_from_token,
)


class AutoGenerateSkillRequest(BaseModel):
    """自动生成技能请求"""
    description: str = Field(..., min_length=1, max_length=2000, description="技能描述")
    category: Optional[str] = Field(default=None, description="技能分类")


class MatchSkillsRequest(BaseModel):
    """匹配技能请求"""
    query: str = Field(..., min_length=1, max_length=500, description="查询内容")
    top_k: int = Field(default=5, ge=1, le=20, description="返回数量")


# ============================================================
# 元认知核心操作
# ============================================================


@router.post("/meta/monitor", summary="执行元认知监控")
async def meta_monitor(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    执行元认知系统监控
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_monitor()
        return APIResponse.ok(
            data=result,
            message="监控完成",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"元认知监控失败: {e}")
        raise APIError.internal(f"元认知监控失败: {str(e)}")


@router.post("/meta/reflect", summary="执行元认知反思")
async def meta_reflect(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user),
):
    """
    执行元认知系统反思
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_reflect()
        return APIResponse.ok(
            data=result,
            message="反思完成",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"元认知反思失败: {e}")
        raise APIError.internal(f"元认知反思失败: {str(e)}")


@router.post("/meta/optimize", summary="执行元认知优化")
async def meta_optimize(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    执行元认知系统优化
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_optimize()
        return APIResponse.ok(
            data=result,
            message="优化完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"元认知优化失败: {e}")
        raise APIError.internal(f"元认知优化失败: {str(e)}")


@router.post("/meta/evolve-skills", summary="执行技能进化")
async def meta_evolve_skills(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    执行技能进化分析
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_evolve_skills()
        return APIResponse.ok(
            data=result,
            message="技能进化完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"技能进化失败: {e}")
        raise APIError.internal(f"技能进化失败: {str(e)}")


# ============================================================
# 元认知报告
# ============================================================


@router.get("/meta/health", summary="获取元认知健康报告")
async def meta_get_health(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    获取元认知系统健康报告
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_get_health_report()
        return APIResponse.ok(
            data=result,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"获取健康报告失败: {e}")
        raise APIError.internal(f"获取健康报告失败: {str(e)}")


@router.get("/meta/reflection", summary="获取元认知反思报告")
async def meta_get_reflection(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    获取元认知系统反思报告
    """
    try:
        # 从Token中获取用户ID
        neuser_id, user_id = _get_user_ids_from_token(req)

        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_get_reflection_report()
        return APIResponse.ok(
            data=result,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"获取反思报告失败: {e}")
        raise APIError.internal(f"获取反思报告失败: {str(e)}")


# ============================================================
# 元认知条件检查
# ============================================================


@router.get("/meta/should-monitor", summary="检查是否需要监控")
async def meta_should_monitor(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    检查当前是否需要执行监控
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_should_monitor()
        return APIResponse.ok(
            data={"should_monitor": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"检查监控条件失败: {e}")
        raise APIError.internal(f"检查监控条件失败: {str(e)}")


@router.get("/meta/should-reflect", summary="检查是否需要反思")
async def meta_should_reflect(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    检查当前是否需要执行反思
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_should_reflect()
        return APIResponse.ok(
            data={"should_reflect": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"检查反思条件失败: {e}")
        raise APIError.internal(f"检查反思条件失败: {str(e)}")


@router.get("/meta/should-optimize", summary="检查是否需要优化")
async def meta_should_optimize(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    检查当前是否需要执行优化
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_should_optimize()
        return APIResponse.ok(
            data={"should_optimize": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"检查优化条件失败: {e}")
        raise APIError.internal(f"检查优化条件失败: {str(e)}")


@router.get("/meta/should-evolve", summary="检查是否需要技能进化")
async def meta_should_evolve(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    检查当前是否需要执行技能进化
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_should_evolve_skills()
        return APIResponse.ok(
            data={"should_evolve": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"检查进化条件失败: {e}")
        raise APIError.internal(f"检查进化条件失败: {str(e)}")


# ============================================================
# 技能管理
# ============================================================


@router.get("/meta/skills", summary="获取所有技能")
async def meta_get_all_skills(
    agent_id: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    req: Request = None,
):
    """
    获取所有技能，支持按分类和状态筛选
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        skills = manager.meta_get_all_skills(category=category, status=status)

        return APIResponse.ok(
            data={
                "count": len(skills),
                "skills": skills,
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"获取技能列表失败: {e}")
        raise APIError.internal(f"获取技能列表失败: {str(e)}")


@router.get("/meta/skills/stats", summary="获取技能统计")
async def meta_get_skill_stats(
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    获取技能系统统计信息
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        stats = manager.meta_get_skill_stats()

        return APIResponse.ok(
            data=stats,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"获取技能统计失败: {e}")
        raise APIError.internal(f"获取技能统计失败: {str(e)}")


@router.post("/meta/skills/generate", summary="自动生成技能")
async def meta_generate_skill(
    request: AutoGenerateSkillRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    根据描述自动生成新技能
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        skill = manager.meta_generate_skill(request.description, category=request.category)

        return APIResponse.ok(
            data=skill,
            message="技能生成成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"生成技能失败: {e}")
        raise APIError.internal(f"生成技能失败: {str(e)}")


@router.post("/meta/skills/match", summary="匹配技能")
async def meta_match_skills(
    request: MatchSkillsRequest,
    agent_id: Optional[str] = None,
    req: Request = None,
):
    """
    根据查询内容匹配合适的技能
    """
    try:
        neuser_id, user_id = _get_user_ids_from_token(req)
        user = {"neuser_id": neuser_id, "user_id": user_id}
        manager = get_memory_manager(agent_id, user)
        matched = manager.meta_match_skills(request.query, top_k=request.top_k)

        return APIResponse.ok(
            data={
                "count": len(matched),
                "matched_skills": matched,
            },
            message="匹配完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception(f"匹配技能失败: {e}")
        raise APIError.internal(f"匹配技能失败: {str(e)}")


# ============================================================
# Agent 级路由（兼容前端 /agents/{agent_id}/metacognition 路径）
# ============================================================

@router.get("/{agent_id}/metacognition", summary="获取 Agent 元认知记录")
async def get_agent_metacognition(
    agent_id: str,
    limit: int = 20,
    offset: int = 0,
    req: Request = None,
):
    """获取 Agent 的元认知记录（前端 MetacognitionPage.vue 调用）"""
    try:
        from neurova.agent_registry import AgentRegistry
        registry = AgentRegistry()
        agent = registry.get_agent(agent_id)
        if not agent:
            return APIResponse.ok(
                data={"items": [], "total": 0, "stats": {"total": 0, "evaluations": 0, "suggestions": 0}},
                request_id=_get_request_id(req),
            )

        manager = getattr(agent, "metacog_manager", None)
        records = getattr(manager, "records", []) if manager else []
        total = len(records)
        items = records[offset:offset + limit]

        evals = len([r for r in records if getattr(r, "thought_type", "") == "evaluation"])
        opts = len([r for r in records if getattr(r, "thought_type", "") == "optimization"])

        return APIResponse.ok(
            data={
                "agent_id": agent_id,
                "total": total,
                "items": [
                    {
                        "id": getattr(r, "id", str(i)),
                        "title": getattr(r, "content", "")[:50],
                        "type": getattr(r, "thought_type", ""),
                        "time": getattr(r, "created_at", ""),
                    }
                    for i, r in enumerate(items)
                ],
                "stats": {
                    "total": total,
                    "evaluations": evals,
                    "suggestions": opts,
                },
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except Exception as e:
        logger.exception(f"获取元认知记录失败: {e}")
        return APIResponse.ok(
            data={"items": [], "total": 0, "stats": {"total": 0, "evaluations": 0, "suggestions": 0}},
            request_id=_get_request_id(req),
        )


@router.get("/{agent_id}/metacognition/stats", summary="获取 Agent 元认知统计")
async def get_agent_metacognition_stats(
    agent_id: str,
    req: Request = None,
):
    """获取 Agent 元认知统计（前端 MetacognitionPage.vue 调用）"""
    try:
        from neurova.agent_registry import AgentRegistry
        registry = AgentRegistry()
        agent = registry.get_agent(agent_id)
        if not agent:
            return APIResponse.ok(
                data={"agent_id": agent_id, "total": 0, "by_type": {}},
                request_id=_get_request_id(req),
            )

        manager = getattr(agent, "metacog_manager", None)
        records = getattr(manager, "records", []) if manager else []
        by_type = {}
        for r in records:
            tt = getattr(r, "thought_type", "")
            by_type[tt] = by_type.get(tt, 0) + 1

        evals = by_type.get("evaluation", 0)
        opts = by_type.get("optimization", 0)

        return APIResponse.ok(
            data={
                "agent_id": agent_id,
                "total": len(records),
                "evaluations": evals,
                "suggestions": opts,
                "by_type": by_type,
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except Exception as e:
        logger.exception(f"获取元认知统计失败: {e}")
        return APIResponse.ok(
            data={"agent_id": agent_id, "total": 0, "by_type": {}},
            request_id=_get_request_id(req),
        )
