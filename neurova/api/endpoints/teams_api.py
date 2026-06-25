"""
团队管理 API

提供以下端点:
- POST   /v1/teams              创建团队
- GET    /v1/teams              列出团队
- GET    /v1/teams/{team_id}    获取团队详情
- DELETE /v1/teams/{team_id}    删除团队
- POST   /v1/teams/{team_id}/members            添加成员
- DELETE /v1/teams/{team_id}/members/{member_id} 移除成员
- PUT    /v1/teams/{team_id}/members/{member_id}/prompt  更新成员职责
- GET    /v1/teams/{team_id}/members/{member_id}/prompt  获取成员职责
- GET    /v1/teams/{team_id}/prompt-context      获取团队所有成员职责
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class TeamInfo(BaseModel):
    """团队信息"""

    team_id: str
    name: str
    description: str = ""
    project_id: Optional[str] = None
    owner_id: str = ""
    members_count: int = 0
    created_at: float = 0
    updated_at: float = 0


class TeamCreate(BaseModel):
    """创建团队请求"""

    name: str = Field(..., description="团队名称")
    description: str = Field(default="", description="团队描述")
    project_id: Optional[str] = Field(default=None, description="所属项目ID")


class TeamUpdate(BaseModel):
    """更新团队请求"""

    name: Optional[str] = None
    description: Optional[str] = None


class MemberInfo(BaseModel):
    """成员信息"""

    member_id: str
    name: str
    role: str = "member"
    prompt: str = ""
    joined_at: float = 0


class MemberAdd(BaseModel):
    """添加成员请求"""

    user_id: str = Field(..., description="用户ID")
    name: str = Field(default="", description="成员名称")
    role: str = Field(default="member", description="角色")
    prompt: str = Field(default="", description="职责描述")


class MemberPromptUpdate(BaseModel):
    """更新成员职责描述"""

    prompt: str = Field(..., description="职责描述")


# ---------------------------------------------------------------------------
# 内存存储（graceful degradation 模式）
# ---------------------------------------------------------------------------

_teams_store: Dict[str, Dict[str, Any]] = {}


def _get_tm():
    """获取 TeamManager（后端模块不可用时使用内存存储）"""
    try:
        from neurova.projects.team_manager import TeamManager

        return TeamManager()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=TeamInfo)
async def create_team(body: TeamCreate):
    """创建团队"""
    team_id = str(uuid.uuid4())
    now = time.time()

    tm = _get_tm()
    if tm and hasattr(tm, "create_team"):
        try:
            result = await tm.create_team(
                name=body.name,
                description=body.description,
                project_id=body.project_id,
            )
            return TeamInfo(**result)
        except Exception as e:
            logger.warning("TeamManager.create_team failed: %s", e)

    team = {
        "team_id": team_id,
        "name": body.name,
        "description": body.description,
        "project_id": body.project_id,
        "owner_id": "default",
        "members_count": 0,
        "created_at": now,
        "updated_at": now,
        "members": {},
    }
    _teams_store[team_id] = team
    return TeamInfo(**{k: v for k, v in team.items() if k != "members"})


@router.get("", response_model=List[TeamInfo])
async def list_teams(
    project_id: Optional[str] = Query(default=None, description="按项目筛选"),
):
    """列出团队"""
    tm = _get_tm()
    if tm and hasattr(tm, "list_teams"):
        try:
            teams = await tm.list_teams(project_id=project_id)
            return [TeamInfo(**t) for t in teams]
        except Exception as e:
            logger.warning("TeamManager.list_teams failed: %s", e)

    teams = list(_teams_store.values())
    if project_id:
        teams = [t for t in teams if t.get("project_id") == project_id]
    return [TeamInfo(**{k: v for k, v in t.items() if k != "members"}) for t in teams]


@router.get("/{team_id}", response_model=TeamInfo)
async def get_team(team_id: str):
    """获取团队详情"""
    tm = _get_tm()
    if tm and hasattr(tm, "get_team"):
        try:
            team = await tm.get_team(team_id)
            if team:
                return TeamInfo(**team)
        except Exception as e:
            logger.warning("TeamManager.get_team failed: %s", e)

    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    return TeamInfo(**{k: v for k, v in team.items() if k != "members"})


@router.delete("/{team_id}")
async def delete_team(team_id: str):
    """删除团队"""
    tm = _get_tm()
    if tm and hasattr(tm, "delete_team"):
        try:
            await tm.delete_team(team_id)
            return {"code": 0, "message": "Team deleted"}
        except Exception as e:
            logger.warning("TeamManager.delete_team failed: %s", e)

    if team_id not in _teams_store:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    del _teams_store[team_id]
    return {"code": 0, "message": "Team deleted"}


@router.post("/{team_id}/members", response_model=MemberInfo)
async def add_member(team_id: str, body: MemberAdd):
    """添加团队成员"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

    member_id = body.user_id or str(uuid.uuid4())
    now = time.time()
    member = {
        "member_id": member_id,
        "name": body.name,
        "role": body.role,
        "prompt": body.prompt,
        "joined_at": now,
    }
    team["members"][member_id] = member
    team["members_count"] = len(team["members"])
    team["updated_at"] = now
    return MemberInfo(**member)


@router.delete("/{team_id}/members/{member_id}")
async def remove_member(team_id: str, member_id: str):
    """移除团队成员"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

    if member_id not in team["members"]:
        raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")

    del team["members"][member_id]
    team["members_count"] = len(team["members"])
    team["updated_at"] = time.time()
    return {"code": 0, "message": "Member removed"}


@router.put("/{team_id}/members/{member_id}/prompt")
async def update_member_prompt(team_id: str, member_id: str, body: MemberPromptUpdate):
    """更新成员职责描述"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

    member = team["members"].get(member_id)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")

    member["prompt"] = body.prompt
    team["updated_at"] = time.time()
    return {"code": 0, "message": "Prompt updated", "data": {"member_id": member_id, "prompt": body.prompt}}


@router.get("/{team_id}/members/{member_id}/prompt")
async def get_member_prompt(team_id: str, member_id: str):
    """获取成员职责描述"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

    member = team["members"].get(member_id)
    if not member:
        raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")

    return {"code": 0, "data": {"member_id": member_id, "prompt": member.get("prompt", "")}}


@router.get("/{team_id}/prompt-context")
async def get_team_prompt_context(team_id: str):
    """获取团队所有成员的职责描述"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")

    context = [
        {"member_id": mid, "name": m.get("name", ""), "role": m.get("role", ""), "prompt": m.get("prompt", "")}
        for mid, m in team.get("members", {}).items()
    ]
    return {"code": 0, "data": {"team_id": team_id, "members": context}}
