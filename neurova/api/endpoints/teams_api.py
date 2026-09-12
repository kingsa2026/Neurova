"""
团队管理 API

提供以下端点:
- POST   /v1/teams              创建团队
- GET    /v1/teams              列出团队
- GET    /v1/teams/{team_id}    获取团队详情
- PUT    /v1/teams/{team_id}    更新团队（2026-09-12 P5 补，FE 在调后端缺→405）
- DELETE /v1/teams/{team_id}    删除团队
- POST   /v1/teams/{team_id}/members            批量添加成员（FE TeamPage 契约 {members:[...], prompt}）
- DELETE /v1/teams/{team_id}/members/{member_id} 移除成员
- PUT    /v1/teams/{team_id}/members/{member_id}/prompt  更新成员职责
- GET    /v1/teams/{team_id}/members/{member_id}/prompt  获取成员职责
- GET    /v1/teams/{team_id}/prompt-context      获取团队所有成员职责

2026-09-12 台账清剿 P5b：
- 原 _get_tm() 依赖不存在的 neurova.projects.team_manager → 删（假桥恒 None 回退）；
- 纯内存 dict 重启即空 → JSON 落盘（NEUROVA_TEAMS_PATH，默认 data/teams_api.json）；
- 字段对齐前端 teams.ts 契约：id（原 team_id）、members 为 string[]（原对象数组，
  完整成员细节保留在 members_detail）。
"""

from neurova.core.logger import get_logger
import json
import os
import pathlib
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)


# ---------------------------------------------------------------------------
# Pydantic 模型（FE 契约：id + members string[]）
# ---------------------------------------------------------------------------


class TeamInfo(BaseModel):
    """团队信息"""

    id: str
    name: str
    description: str = ""
    project_id: Optional[str] = None
    owner_id: str = ""
    members: List[str] = []
    members_detail: List[Dict[str, Any]] = []
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


class MemberBatchAdd(BaseModel):
    """批量添加成员请求（FE addTeamMembers 契约）"""

    members: List[str] = Field(..., min_length=1, description="成员用户 ID 列表")
    prompt: str = Field(default="", description="共同职责描述")


# ---------------------------------------------------------------------------
# JSON 落盘存储
# ---------------------------------------------------------------------------

_STORE_FILE = os.environ.get("NEUROVA_TEAMS_PATH", "data/teams_api.json")

_teams_store: Dict[str, Dict[str, Any]] = {}


def _team_view(team: Dict[str, Any]) -> TeamInfo:
    members = [m["user_id"] for m in team.get("members_detail", [])]
    return TeamInfo(
        id=team["id"],
        name=team["name"],
        description=team.get("description", ""),
        project_id=team.get("project_id"),
        owner_id=team.get("owner_id", ""),
        members=members,
        members_detail=team.get("members_detail", []),
        created_at=team.get("created_at", 0),
        updated_at=team.get("updated_at", 0),
    )


def _load_store() -> None:
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if isinstance(raw, dict):
            _teams_store.update(raw.get("teams", {}) or {})
    except FileNotFoundError:
        pass
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to load teams store: %s", e)


def _save_store() -> None:
    p = pathlib.Path(_STORE_FILE)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"teams": _teams_store}, f, indent=2, ensure_ascii=False)
    tmp.replace(p)


def _reboot_load() -> None:
    """测试钩子：模拟进程重启（清空内存，从配置路径重载）。"""
    _teams_store.clear()
    global _STORE_FILE
    _STORE_FILE = os.environ.get("NEUROVA_TEAMS_PATH", "data/teams_api.json")
    _load_store()


_load_store()


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=TeamInfo)
async def create_team(body: TeamCreate):
    """创建团队"""
    team = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "project_id": body.project_id,
        "owner_id": "default",
        "members_detail": [],
        "created_at": time.time(),
        "updated_at": time.time(),
    }
    _teams_store[team["id"]] = team
    _save_store()
    return _team_view(team)


@router.get("", response_model=List[TeamInfo])
async def list_teams():
    """列出团队"""
    return [_team_view(t) for t in _teams_store.values()]


@router.get("/{team_id}", response_model=TeamInfo)
async def get_team(team_id: str):
    """获取团队详情"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    return _team_view(team)


@router.put("/{team_id}", response_model=TeamInfo)
async def update_team(team_id: str, body: TeamUpdate):
    """更新团队（FE updateTeam 契约；原缺失恒 405）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    if body.name is not None:
        team["name"] = body.name
    if body.description is not None:
        team["description"] = body.description
    team["updated_at"] = time.time()
    _save_store()
    return _team_view(team)


@router.delete("/{team_id}")
async def delete_team(team_id: str):
    """删除团队"""
    if team_id not in _teams_store:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    del _teams_store[team_id]
    _save_store()
    return {"code": 0, "message": f"Team '{team_id}' deleted"}


@router.post("/{team_id}/members", response_model=TeamInfo)
async def add_members(team_id: str, body: MemberBatchAdd):
    """批量添加成员（FE {members: [...], prompt} 契约；原单成员 user_id 恒 422）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    existing = {m["user_id"] for m in team["members_detail"]}
    for uid in body.members:
        if not uid or uid in existing:
            continue
        team["members_detail"].append({
            "user_id": uid,
            "name": uid,
            "role": "member",
            "prompt": body.prompt,
            "joined_at": time.time(),
        })
    team["updated_at"] = time.time()
    _save_store()
    return _team_view(team)


@router.delete("/{team_id}/members/{member_id}")
async def remove_member(team_id: str, member_id: str):
    """移除成员"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    before = len(team["members_detail"])
    team["members_detail"] = [m for m in team["members_detail"] if m["user_id"] != member_id]
    if len(team["members_detail"]) == before:
        raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")
    team["updated_at"] = time.time()
    _save_store()
    return {"code": 0, "message": f"Member '{member_id}' removed"}


@router.put("/{team_id}/members/{member_id}/prompt")
async def update_member_prompt(team_id: str, member_id: str, body: Dict[str, Any]):
    """更新成员职责描述"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    for m in team["members_detail"]:
        if m["user_id"] == member_id:
            m["prompt"] = str(body.get("prompt", ""))
            team["updated_at"] = time.time()
            _save_store()
            return {"code": 0, "message": "Prompt updated", "data": {"prompt": m["prompt"]}}
    raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")


@router.get("/{team_id}/members/{member_id}/prompt")
async def get_member_prompt(team_id: str, member_id: str):
    """获取成员职责描述"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    for m in team["members_detail"]:
        if m["user_id"] == member_id:
            return {"code": 0, "data": {"prompt": m.get("prompt", "")}}
    raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")


@router.get("/{team_id}/prompt-context")
async def get_team_prompt_context(team_id: str):
    """获取团队所有成员职责上下文"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    context = "\n\n".join(
        f"## {m.get('name', m['user_id'])}\n{m.get('prompt', '')}"
        for m in team["members_detail"] if m.get("prompt")
    )
    return {"code": 0, "data": {"prompt_context": context}}
