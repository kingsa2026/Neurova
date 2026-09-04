"""
记忆接口 - 元认知 (Meta-cognition)
"""

from typing import Any, Dict, Optional

from fastapi import Depends, Request
from pydantic import BaseModel, Field

from neurova.api.auth import get_current_user_or_default
from neurova.cognitive_layers.meta_cognition_layer.ledger import get_meta_ledger
from neurova.interfaces.api_standard import (
    APIError,
    APIResponse,
    success_response,
)

from .base import (
    _get_request_id,
    _get_user_ids_from_token,
    get_memory_manager,
    logger,
    router,
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
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    执行元认知系统监控
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_monitor()
        return success_response(
            data=result,
            message="监控完成",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("元认知监控失败: %s", e)
        raise APIError.internal(f"元认知监控失败: {str(e)}")


@router.post("/meta/reflect", summary="执行元认知反思")
async def meta_reflect(
    agent_id: Optional[str] = None,
    user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """
    执行元认知系统反思
    """
    try:
        manager = get_memory_manager(agent_id, user)
        result = manager.meta_reflect()
        return success_response(
            data=result,
            message="反思完成",
            request_id=_get_request_id(None),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("元认知反思失败: %s", e)
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
        return success_response(
            data=result,
            message="优化完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("元认知优化失败: %s", e)
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
        return success_response(
            data=result,
            message="技能进化完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("技能进化失败: %s", e)
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
        return success_response(
            data=result,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取健康报告失败: %s", e)
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
        return success_response(
            data=result,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取反思报告失败: %s", e)
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
        return success_response(
            data={"should_monitor": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("检查监控条件失败: %s", e)
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
        return success_response(
            data={"should_reflect": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("检查反思条件失败: %s", e)
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
        return success_response(
            data={"should_optimize": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("检查优化条件失败: %s", e)
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
        return success_response(
            data={"should_evolve": result},
            message="检查完成",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("检查进化条件失败: %s", e)
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

        return success_response(
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
        logger.exception("获取技能列表失败: %s", e)
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

        return success_response(
            data=stats,
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("获取技能统计失败: %s", e)
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

        return success_response(
            data=skill,
            message="技能生成成功",
            request_id=_get_request_id(req),
        )
    except APIError:
        raise
    except Exception as e:
        logger.exception("生成技能失败: %s", e)
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

        return success_response(
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
        logger.exception("匹配技能失败: %s", e)
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
    """获取 Agent 的元认知记录（前端 MetacognitionPage.vue 调用）

    V3 收口：原实现读 agent.metacog_manager（全仓无此属性，恒返回空），
    现与 /v1/metacognition 端点同源——统一台账 MetaLedger。
    """
    try:
        ledger = get_meta_ledger(agent_id)
        page = offset // limit + 1 if limit else 1
        result = ledger.list_records(agent_id=agent_id, page=page, size=limit)
        items = [
            {
                "id": it["id"],
                "type": it["type"],
                "content": it["content"],
                "context": it["context"],
                "confidence": it["confidence"],
                "created_at": it["created_at"],
            }
            for it in result["items"]
        ]
        stats = ledger.record_stats(agent_id)
        return success_response(
            data={
                "agent_id": agent_id,
                "total": result["total"],
                "items": items,
                "stats": {
                    "total": stats["total_entries"],
                    "evaluations": sum(
                        t["count"] for t in stats["by_type"] if t["type"] == "self_assessment"
                    ),
                    "suggestions": sum(
                        t["count"] for t in stats["by_type"] if t["type"] == "strategy"
                    ),
                },
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except Exception as e:
        logger.exception("获取元认知记录失败: %s", e)
        return success_response(
            data={"items": [], "total": 0, "stats": {"total": 0, "evaluations": 0, "suggestions": 0}},
            request_id=_get_request_id(req),
        )


@router.get("/{agent_id}/metacognition/stats", summary="获取 Agent 元认知统计")
async def get_agent_metacognition_stats(
    agent_id: str,
    req: Request = None,
):
    """获取 Agent 元认知统计（V3 收口：同源台账）"""
    try:
        stats = get_meta_ledger(agent_id).record_stats(agent_id)
        by_type = {t["type"]: t["count"] for t in stats["by_type"]}
        return success_response(
            data={
                "agent_id": agent_id,
                "total": stats["total_entries"],
                "evaluations": by_type.get("self_assessment", 0),
                "suggestions": by_type.get("strategy", 0),
                "by_type": by_type,
            },
            message="获取成功",
            request_id=_get_request_id(req),
        )
    except Exception as e:
        logger.exception("获取元认知统计失败: %s", e)
        return success_response(
            data={"agent_id": agent_id, "total": 0, "by_type": {}},
            request_id=_get_request_id(req),
        )
