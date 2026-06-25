"""
技能池管理 API

提供以下端点:
- GET    /v1/skill-pool/public                   公共技能列表
- GET    /v1/skill-pool/public/{skill_id}        公共技能详情
- POST   /v1/skill-pool/public/{skill_id}/install 安装公共技能
- GET    /v1/skill-pool/private                  专属技能列表
- POST   /v1/skill-pool/private                  创建专属技能
- PUT    /v1/skill-pool/private/{skill_id}       更新专属技能
- DELETE /v1/skill-pool/private/{skill_id}       删除专属技能
- POST   /v1/skill-pool/private/{skill_id}/share 共享技能
- POST   /v1/skill-pool/private/{skill_id}/push  推送给Agent
- DELETE /v1/skill-pool/private/{skill_id}/push  取消推送
- GET    /v1/skill-pool/agent/{agent_id}/skills  Agent技能列表
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()


class SkillInfo(BaseModel):
    skill_id: str
    name: str
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    scope: str = "public"
    owner_id: str = ""
    enabled: bool = True
    created_at: float = 0
    updated_at: float = 0


class SkillCreate(BaseModel):
    name: str = Field(..., description="技能名称")
    description: str = Field(default="", description="描述")
    category: str = Field(default="general", description="分类")
    config: Dict[str, Any] = Field(default_factory=dict, description="技能配置")


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    config: Optional[Dict[str, Any]] = None


class SkillShare(BaseModel):
    target_user_id: str = Field(..., description="目标用户 ID")


class SkillPush(BaseModel):
    agent_id: str = Field(default="default", description="Agent ID")


_public_skills: Dict[str, Dict[str, Any]] = {}
_private_skills: Dict[str, Dict[str, Any]] = {}


def _get_spm():
    try:
        from neurova.skill_system.skill_pool_manager import SkillPoolManager

        return SkillPoolManager()
    except Exception:
        return None


@router.get("/public", response_model=List[SkillInfo])
async def list_public_skills(category: Optional[str] = Query(default=None)):
    """列出公共技能"""
    skills = [s for s in _public_skills.values() if s.get("scope") == "public"]
    if category:
        skills = [s for s in skills if s.get("category") == category]
    return [SkillInfo(**s) for s in skills]


@router.get("/public/{skill_id}", response_model=SkillInfo)
async def get_public_skill(skill_id: str):
    """获取公共技能详情"""
    skill = _public_skills.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return SkillInfo(**skill)


@router.post("/public/{skill_id}/install")
async def install_public_skill(skill_id: str, agent_id: str = Query(default="default")):
    """安装公共技能到 Agent"""
    skill = _public_skills.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return {"code": 0, "message": f"Skill '{skill_id}' installed to agent '{agent_id}'"}


@router.get("/private", response_model=List[SkillInfo])
async def list_private_skills(user_id: str = Query(default="default")):
    """列出专属技能"""
    skills = [s for s in _private_skills.values() if s.get("owner_id") == user_id]
    return [SkillInfo(**s) for s in skills]


@router.post("/private", response_model=SkillInfo)
async def create_private_skill(body: SkillCreate, user_id: str = Query(default="default")):
    """创建专属技能"""
    sid = str(uuid.uuid4())
    now = time.time()
    skill = {
        "skill_id": sid,
        "name": body.name,
        "description": body.description,
        "category": body.category,
        "scope": "private",
        "owner_id": user_id,
        "enabled": True,
        "created_at": now,
        "updated_at": now,
    }
    _private_skills[sid] = skill
    return SkillInfo(**skill)


@router.put("/private/{skill_id}", response_model=SkillInfo)
async def update_private_skill(skill_id: str, body: SkillUpdate, user_id: str = Query(default="default")):
    """更新专属技能"""
    skill = _private_skills.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    for k, v in body.model_dump(exclude_none=True).items():
        skill[k] = v
    skill["updated_at"] = time.time()
    return SkillInfo(**skill)


@router.delete("/private/{skill_id}")
async def delete_private_skill(skill_id: str, user_id: str = Query(default="default")):
    """删除专属技能"""
    skill = _private_skills.get(skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    if skill.get("owner_id") != user_id:
        raise HTTPException(status_code=403, detail="Permission denied")
    del _private_skills[skill_id]
    return {"code": 0, "message": "Skill deleted"}


@router.post("/private/{skill_id}/share")
async def share_private_skill(skill_id: str, body: SkillShare):
    """共享专属技能"""
    return {"code": 0, "message": f"Skill shared with {body.target_user_id}"}


@router.post("/private/{skill_id}/push")
async def push_skill_to_agent(skill_id: str, body: SkillPush):
    """推送技能到 Agent"""
    return {"code": 0, "message": f"Skill pushed to agent '{body.agent_id}'"}


@router.delete("/private/{skill_id}/push")
async def unpush_skill_from_agent(skill_id: str, agent_id: str = Query(default="default")):
    """取消推送"""
    return {"code": 0, "message": f"Skill unpushed from agent '{agent_id}'"}


@router.get("/agent/{agent_id}/skills", response_model=List[SkillInfo])
async def get_agent_skills(agent_id: str):
    """获取 Agent 的所有技能"""
    return []
