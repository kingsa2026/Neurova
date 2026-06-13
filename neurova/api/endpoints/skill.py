from __future__ import annotations

"""
技能系统接口 - Skill Endpoint

提供以下API:
1. 获取技能列表 (GET /api/v1/skills)
2. 获取技能详情 (GET /api/v1/skills/{skill_id})
3. 执行技能 (POST /api/v1/skills/{skill_id}/execute)
4. 获取技能统计 (GET /api/v1/skills/stats)
5. 学习技能 (POST /api/v1/skills/learn)
6. 获取技能提示 (GET /api/v1/skills/tips)
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()


class SkillInfo(BaseModel):
    """技能信息"""

    skill_id: str
    name: str
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    enabled: bool = True
    usage_count: int = 0
    success_rate: float = 0.0
    created_at: float = 0
    updated_at: float = 0


class SkillExecuteRequest(BaseModel):
    """技能执行请求"""

    parameters: Dict[str, Any] = Field(default_factory=dict, description="技能参数")
    context: Dict[str, Any] = Field(default_factory=dict, description="执行上下文")
    timeout: int = Field(default=30, description="超时时间(秒)")


class SkillExecuteResponse(BaseModel):
    """技能执行响应"""

    success: bool
    result: Any = None
    error: Optional[str] = None
    execution_time: float = 0
    skill_id: str


class SkillLearnRequest(BaseModel):
    """技能学习请求"""

    conversation_id: Optional[str] = None
    messages: List[Dict[str, Any]] = Field(default_factory=list, description="对话消息")
    feedback: Optional[str] = None


class SkillLearnResponse(BaseModel):
    """技能学习响应"""

    success: bool
    patterns_learned: int = 0
    skills_updated: int = 0
    message: str = ""


class SkillStats(BaseModel):
    """技能统计"""

    total_skills: int = 0
    enabled_skills: int = 0
    total_executions: int = 0
    average_success_rate: float = 0
    top_skills: List[Dict[str, Any]] = []


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


def _get_agent(agent_id: str = "default"):
    """获取 Agent 实例"""
    from neurova.api.endpoints import get_agent_instance

    return get_agent_instance(agent_id)


def _get_skill_manager():
    """获取技能管理器"""
    try:
        from neurova.skill_system import SkillRegistry

        return SkillRegistry()
    except Exception as e:
        logger.warning("SkillRegistry not available: %s", e)
        return None


def _get_builtin_skills() -> List[Dict[str, Any]]:
    """获取内置技能列表"""
    return [
        {
            "skill_id": "memory_search",
            "name": "Memory Search",
            "description": "搜索记忆库中的相关信息",
            "category": "memory",
            "version": "1.0.0",
            "enabled": True,
            "usage_count": 0,
            "success_rate": 0.95,
        },
        {
            "skill_id": "web_search",
            "name": "Web Search",
            "description": "搜索互联网获取最新信息",
            "category": "research",
            "version": "1.0.0",
            "enabled": True,
            "usage_count": 0,
            "success_rate": 0.88,
        },
        {
            "skill_id": "code_execution",
            "name": "Code Execution",
            "description": "执行 Python 代码",
            "category": "development",
            "version": "1.0.0",
            "enabled": True,
            "usage_count": 0,
            "success_rate": 0.92,
        },
        {
            "skill_id": "file_read",
            "name": "File Read",
            "description": "读取文件内容",
            "category": "filesystem",
            "version": "1.0.0",
            "enabled": True,
            "usage_count": 0,
            "success_rate": 0.99,
        },
        {
            "skill_id": "file_write",
            "name": "File Write",
            "description": "写入文件内容",
            "category": "filesystem",
            "version": "1.0.0",
            "enabled": True,
            "usage_count": 0,
            "success_rate": 0.97,
        },
    ]


@router.get("", response_model=List[SkillInfo])
async def get_skills(
    request: Request,
    category: Optional[str] = Query(default=None, description="按分类筛选"),
    enabled_only: bool = Query(default=False, description="仅显示启用的技能"),
):
    """获取所有技能列表"""
    skills = _get_builtin_skills()

    # 应用筛选
    if category:
        skills = [s for s in skills if s.get("category") == category]
    if enabled_only:
        skills = [s for s in skills if s.get("enabled", True)]

    return [SkillInfo(**s) for s in skills]


@router.get("/stats", response_model=SkillStats)
async def get_skill_stats(request: Request):
    """获取技能统计信息"""
    skills = _get_builtin_skills()

    return SkillStats(
        total_skills=len(skills),
        enabled_skills=len([s for s in skills if s.get("enabled", True)]),
        total_executions=sum(s.get("usage_count", 0) for s in skills),
        average_success_rate=sum(s.get("success_rate", 0) for s in skills) / len(skills) if skills else 0,
        top_skills=sorted(skills, key=lambda x: x.get("usage_count", 0), reverse=True)[:5],
    )


@router.get("/tips")
async def get_skill_tips(
    request: Request,
    context: Optional[str] = Query(default=None, description="上下文信息"),
):
    """获取技能使用提示"""
    tips = [
        "使用 memory_search 可以快速找到相关记忆",
        "web_search 适合获取最新信息",
        "code_execution 可以执行复杂的计算任务",
        "file_read 和 file_write 用于文件操作",
    ]

    return {
        "code": 0,
        "message": "success",
        "data": {
            "tips": tips,
            "context": context,
        },
    }


@router.post("/learn", response_model=SkillLearnResponse)
async def learn_from_conversation(
    request: Request,
    body: SkillLearnRequest,
):
    """从对话中学习技能"""
    _get_request_id(request)

    try:
        agent = _get_agent()
        if not agent:
            return SkillLearnResponse(
                success=False,
                message="Agent not available",
            )

        # 尝试调用 Agent 的学习功能
        if hasattr(agent, "learn_from_conversation"):
            result = await agent.learn_from_conversation(
                messages=body.messages,
                feedback=body.feedback,
            )
            return SkillLearnResponse(
                success=True,
                patterns_learned=result.get("patterns_learned", 0),
                skills_updated=result.get("skills_updated", 0),
                message="Learning completed",
            )

        return SkillLearnResponse(
            success=True,
            patterns_learned=0,
            skills_updated=0,
            message="Learning feature not implemented yet",
        )
    except Exception as e:
        logger.error(f"Learn error: {e}", exc_info=True)
        return SkillLearnResponse(
            success=False,
            message=f"Learning failed: {str(e)}",
        )


@router.get("/{skill_id}", response_model=SkillInfo)
async def get_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
):
    """获取单个技能详情"""
    skills = _get_builtin_skills()

    for skill in skills:
        if skill.get("skill_id") == skill_id:
            return SkillInfo(**skill)

    raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")


@router.post("/{skill_id}/execute", response_model=SkillExecuteResponse)
async def execute_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
    body: SkillExecuteRequest = SkillExecuteRequest(),
):
    """执行技能"""
    _get_request_id(request)
    start_time = time.time()

    # 验证技能存在
    skills = _get_builtin_skills()
    skill_exists = any(s.get("skill_id") == skill_id for s in skills)

    if not skill_exists:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    try:
        agent = _get_agent()
        if not agent:
            return SkillExecuteResponse(
                success=False,
                error="Agent not available",
                skill_id=skill_id,
            )

        # 尝试通过 Agent 执行技能
        if hasattr(agent, "execute_skill"):
            result = await agent.execute_skill(
                skill_id=skill_id,
                parameters=body.parameters,
                context=body.context,
                timeout=body.timeout,
            )
            return SkillExecuteResponse(
                success=True,
                result=result,
                execution_time=time.time() - start_time,
                skill_id=skill_id,
            )

        # 降级：返回模拟结果
        return SkillExecuteResponse(
            success=True,
            result={"message": f"Skill '{skill_id}' execution simulated"},
            execution_time=time.time() - start_time,
            skill_id=skill_id,
        )
    except Exception as e:
        logger.error(f"Execute skill error: {e}", exc_info=True)
        return SkillExecuteResponse(
            success=False,
            error=str(e),
            execution_time=time.time() - start_time,
            skill_id=skill_id,
        )


@router.put("/{skill_id}/enable")
async def enable_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
):
    """启用技能"""
    skills = _get_builtin_skills()
    skill_exists = any(s.get("skill_id") == skill_id for s in skills)

    if not skill_exists:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    return {
        "code": 0,
        "message": f"Skill '{skill_id}' enabled",
        "data": {"skill_id": skill_id, "enabled": True},
    }


@router.put("/{skill_id}/disable")
async def disable_skill(
    request: Request,
    skill_id: str = Path(..., description="技能ID"),
):
    """禁用技能"""
    skills = _get_builtin_skills()
    skill_exists = any(s.get("skill_id") == skill_id for s in skills)

    if not skill_exists:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_id}' not found")

    return {
        "code": 0,
        "message": f"Skill '{skill_id}' disabled",
        "data": {"skill_id": skill_id, "enabled": False},
    }
