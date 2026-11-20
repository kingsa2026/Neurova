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
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field
from neurova.core.atomic_io import loadJsonStore, saveJsonStore
from neurova.core.data_root import dataPath
from neurova.agent.neuacp.catalog import refuseExecutorSpec

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
    # A5 租户隔离（§6.4）：团队归属租户（部门根），缺省 default（存量数据兼容）
    tenant_id: str = "default"
    members: List[str] = []
    members_detail: List[Dict[str, Any]] = []
    created_at: float = 0
    updated_at: float = 0
    # S10 团队来源：manual（人工创建）/ agent_proposed（蜂群沉淀提议经人批准）
    origin: str = "manual"
    approved_by: str = ""
    promoted_from_run: str = ""


class NeuacpExecutorSpec(BaseModel):
    """外部编码代理执行体配置（设计文档 §4.1）。

    只随名册落盘键名与启动参数；凭据值不经名册（运行时从凭据面按
    租户+agent 作用域取）。
    """

    kind: str = Field(default="acp", description="执行体类型：acp | plugin")
    tool: str = Field(default="", description="工具目录标识（catalog）")
    transport: str = Field(default="stdio", description="stdio | ssh")
    command: List[str] = Field(default_factory=list, description="启动命令 argv")
    cwd: str = Field(default="", description="外部代理工作目录（必填）")
    env_keys: List[str] = Field(default_factory=list, description="凭据键名清单（只录键名不录值）")
    permission_mode: str = Field(default="chain", description="chain（审批链）| auto（仅 L0，admin 专属）")
    remote: Optional[Dict[str, Any]] = Field(default=None, description="transport=ssh 时的连接参数（key_ref 不落明文）")


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
    # P1 移交清偿：成员角色落盘。FE TeamNeuacpMemberForm 上送 coder/reviewer/member；
    # 兼容既有 AgentRole 枚举值；缺省 member 维持既有契约（不传 role 行为不变）
    role: str = Field(default="member", description="成员角色：member/coder/reviewer 或既有协作角色")
    # A5：外部编码代理执行体（整批成员共用一份执行体配置）；仅 admin 可配
    executor: Optional[NeuacpExecutorSpec] = None


def _legalMemberRoles() -> set:
    """名册成员合法角色集：FE 契约三元 + 既有 AgentRole 枚举值（单一事实源对齐）。

    AgentRole 是协作角色枚举单源（neurova/agent/templates/collaboration_template.py）；
    member/coder/reviewer 是名册面（FE TeamNeuacpMemberForm）的契约取值。
    """
    from neurova.agent.templates.collaboration_template import AgentRole

    roles = {"member", "coder", "reviewer"}
    roles.update(str(role.value) for role in AgentRole)
    return roles


# ---------------------------------------------------------------------------
# JSON 落盘存储
# ---------------------------------------------------------------------------

_STORE_FILE = os.environ.get("NEUROVA_TEAMS_PATH") or dataPath("teams_api.json")

_teams_store: Dict[str, Dict[str, Any]] = {}


def _team_view(team: Dict[str, Any]) -> TeamInfo:
    members = [m["user_id"] for m in team.get("members_detail", [])]
    return TeamInfo(
        id=team["id"],
        name=team["name"],
        description=team.get("description", ""),
        project_id=team.get("project_id"),
        owner_id=team.get("owner_id", ""),
        # A5 租户隔离：存量数据无 tenant_id 时回落 default（与身份缺省一致）
        tenant_id=str(team.get("tenant_id") or "default"),
        members=members,
        members_detail=team.get("members_detail", []),
        created_at=team.get("created_at", 0),
        updated_at=team.get("updated_at", 0),
        # S10 来源字段：旧数据缺省回退 manual（JSON 落盘 .get 兼容）
        origin=str(team.get("origin") or "manual"),
        approved_by=str(team.get("approved_by") or ""),
        promoted_from_run=str(team.get("promoted_from_run") or ""),
    )


# ---------------------------------------------------------------------------
# A5 租户隔离（§6.4 强制红线）：读限同租户；写限同租户且（属主或平台 admin）。
# 团队租户取自团队 dict 的 tenant_id（存量数据缺省 default）；请求者租户取
# JWT 身份字典的 tenant_id（buildIdentityClaims 部门根，缺省 default）。
# ---------------------------------------------------------------------------


def _userTenant(user: Dict[str, Any]) -> str:
    return str((user or {}).get("tenant_id") or "default")


def _isPlatformAdmin(user: Dict[str, Any]) -> bool:
    return str((user or {}).get("role") or "") == "admin"


def _teamReadable(team: Dict[str, Any], user: Dict[str, Any]) -> bool:
    return _userTenant(team) == _userTenant(user)


def _teamWritable(team: Dict[str, Any], user: Dict[str, Any]) -> bool:
    if _userTenant(team) != _userTenant(user):
        return False
    return _isPlatformAdmin(user) or str(team.get("owner_id") or "") == str(user.get("user_id") or "")


def _requireReadable(team: Dict[str, Any], user: Dict[str, Any]) -> None:
    if not _teamReadable(team, user):
        # 404 而非 403：不向其他租户泄露团队存在性
        raise HTTPException(status_code=404, detail=f"Team '{team.get('id')}' not found")


def _requireWritable(team: Dict[str, Any], user: Dict[str, Any]) -> None:
    if not _teamReadable(team, user):
        raise HTTPException(status_code=404, detail=f"Team '{team.get('id')}' not found")
    if not _teamWritable(team, user):
        raise HTTPException(status_code=403, detail="无权修改该团队（需同租户且为属主或平台 admin）")


def _load_store() -> None:
    raw = loadJsonStore(_STORE_FILE, {})
    _teams_store.update(raw.get("teams", {}) or {})


def _save_store() -> None:
    saveJsonStore(_STORE_FILE, {"teams": _teams_store})


def _reboot_load() -> None:
    """测试钩子：模拟进程重启（清空内存，从配置路径重载）。"""
    _teams_store.clear()
    global _STORE_FILE
    _STORE_FILE = os.environ.get("NEUROVA_TEAMS_PATH") or dataPath("teams_api.json")
    _load_store()


_load_store()


def getTeamRoster(team_id: str) -> Optional[Dict[str, Any]]:
    """只读读取团队名册（S9 蜂群动态组队消费；不改字段、不加写点）。

    Returns:
        团队 dict 的浅拷贝（members_detail 原样引用只读）；团队不存在返回 None。
    """
    team = _teams_store.get(str(team_id or "").strip())
    return dict(team) if team else None


def currentUserTenant() -> str:
    """当前请求租户（内部复用面用；HTTP 面走依赖注入的身份字典）。

    单源已收敛至 user_group_model.currentUserTenantId（A9 收敛），本函数
    保留为兼容转调。
    """
    from neurova.auth.user_group_model import currentUserTenantId

    return currentUserTenantId()


# ---------------------------------------------------------------------------
# S10 临时团队沉淀（agent 提议 → 人批准 → 写入本单源）
# 团队是用户资产，agent 不得自行立队：提议先挂审批链（L1），批准前只进
# _pendingTeamProposals 进程内登记表，批准动作的调用方（decide 工具/房间裁决端点）
# 经 applyTeamProposalDecision 回灌——写入点只有 createAgentProposedTeam 一处。
# ---------------------------------------------------------------------------

_pendingTeamProposals: Dict[str, Dict[str, Any]] = {}


def registerTeamProposal(request_id: str, snapshot: Dict[str, Any]) -> None:
    """登记一笔待批团队沉淀提议（request_id → 成员+职责快照）。"""
    rid = str(request_id or "").strip()
    if rid:
        _pendingTeamProposals[rid] = dict(snapshot or {})


def popTeamProposal(request_id: str) -> Optional[Dict[str, Any]]:
    """取出并移除待批提议（幂等：二次取出返回 None）。"""
    return _pendingTeamProposals.pop(str(request_id or "").strip(), None)


def createAgentProposedTeam(
    name: str,
    description: str,
    membersDetail: List[Dict[str, Any]],
    promotedFromRun: str = "",
    approvedBy: str = "",
    tenantId: str = "default",
    ownerId: str = "default",
) -> Dict[str, Any]:
    """agent 沉淀提议经人批准后写入团队单源（origin=agent_proposed）。

    tenantId/ownerId：A5 租户隔离——调用方（裁决入口有请求上下文）应传入
    裁决者租户/ID；未传时落 default（关联缺口：approval_chain 传参接线另批）。
    """
    now = time.time()
    team = {
        "id": str(uuid.uuid4()),
        "name": str(name or "").strip() or "未命名团队",
        "description": str(description or ""),
        "project_id": None,
        "owner_id": str(ownerId or "default"),
        "tenant_id": str(tenantId or "default"),
        "members_detail": [dict(m) for m in (membersDetail or [])],
        "created_at": now,
        "updated_at": now,
        "origin": "agent_proposed",
        "approved_by": str(approvedBy or ""),
        "promoted_from_run": str(promotedFromRun or ""),
    }
    _teams_store[team["id"]] = team
    _save_store()
    return dict(team)


def applyTeamProposalDecision(
    request_id: str, decision: str, decidedBy: str = "",
) -> Dict[str, Any]:
    """审批裁决回灌：批准 → 把登记的成员+职责快照落成固定团队。

    两个裁决入口（decide_subagent_approval 工具 / 房间裁决端点）共用本函数；
    驳回/无登记 → 不写 teams_api（幂等：登记表 pop 一次即清）。
    """
    snapshot = popTeamProposal(request_id)
    if snapshot is None:
        return {"applied": False, "reason": "no_pending_proposal"}
    if str(decision or "").strip().lower() != "approve":
        return {"applied": False, "reason": "rejected"}
    team = createAgentProposedTeam(
        name=snapshot.get("name", ""),
        description=snapshot.get("description", ""),
        membersDetail=snapshot.get("members_detail") or [],
        promotedFromRun=snapshot.get("promoted_from_run", ""),
        approvedBy=decidedBy,
    )
    return {"applied": True, "team": team}


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=TeamInfo)
async def create_team(body: TeamCreate, current_user: Dict[str, Any] = Depends(get_current_user)):
    """创建团队（租户戳印：tenant_id=创建者租户，owner_id=创建者）"""
    team = {
        "id": str(uuid.uuid4()),
        "name": body.name,
        "description": body.description,
        "project_id": body.project_id,
        "owner_id": str(current_user.get("user_id") or "default"),
        "tenant_id": str(current_user.get("tenant_id") or "default"),
        "members_detail": [],
        "created_at": time.time(),
        "updated_at": time.time(),
        "origin": "manual",
        "approved_by": "",
        "promoted_from_run": "",
    }
    _teams_store[team["id"]] = team
    _save_store()
    return _team_view(team)


@router.get("", response_model=List[TeamInfo])
async def list_teams(current_user: Dict[str, Any] = Depends(get_current_user)):
    """列出团队（A5：仅本租户）"""
    tenant = _userTenant(current_user)
    return [_team_view(t) for t in _teams_store.values() if _userTenant(t) == tenant]


@router.get("/{team_id}", response_model=TeamInfo)
async def get_team(team_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取团队详情（A5：跨租户 404 不泄露存在性）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireReadable(team, current_user)
    return _team_view(team)


@router.put("/{team_id}", response_model=TeamInfo)
async def update_team(team_id: str, body: TeamUpdate, current_user: Dict[str, Any] = Depends(get_current_user)):
    """更新团队（FE updateTeam 契约；原缺失恒 405；A5：同租户+属主/admin）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireWritable(team, current_user)
    if body.name is not None:
        team["name"] = body.name
    if body.description is not None:
        team["description"] = body.description
    team["updated_at"] = time.time()
    _save_store()
    return _team_view(team)


@router.delete("/{team_id}")
async def delete_team(team_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """删除团队（A5：同租户+属主/admin）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireWritable(team, current_user)
    del _teams_store[team_id]
    _save_store()
    return {"code": 0, "message": f"Team '{team_id}' deleted"}


@router.post("/{team_id}/members", response_model=TeamInfo)
async def add_members(team_id: str, body: MemberBatchAdd, current_user: Dict[str, Any] = Depends(get_current_user)):
    """批量添加成员（FE {members: [...], prompt} 契约；A5：executor 外部成员仅 admin）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireWritable(team, current_user)
    # P1 移交清偿：role 校验（FE 三元 + 既有 AgentRole 取值），非法值 422 诚实拒绝
    member_role = str(body.role or "member")
    if member_role not in _legalMemberRoles():
        raise HTTPException(status_code=422, detail="role 仅支持 member/coder/reviewer 或既有协作角色")
    executor_spec = None
    if body.executor is not None:
        if not _isPlatformAdmin(current_user):
            raise HTTPException(status_code=403, detail="外部编码代理成员仅平台 admin 可配置")
        if str(body.executor.permission_mode or "chain") not in ("chain", "auto"):
            raise HTTPException(status_code=422, detail="executor.permission_mode 仅支持 chain/auto")
        executor_spec = body.executor.model_dump()
        # F1 配置期闸（双闸之一）：能力违规在名册写入前结构化拒绝（422），
        # 判据单源 catalog.refuseExecutorSpec（与派活期闸同函数）
        capability_reasons = refuseExecutorSpec(executor_spec)
        if capability_reasons:
            raise HTTPException(status_code=422, detail="; ".join(capability_reasons))
    existing = {m["user_id"] for m in team["members_detail"]}
    for uid in body.members:
        if not uid or uid in existing:
            continue
        entry = {
            "user_id": uid,
            "name": uid,
            "role": member_role,
            "prompt": body.prompt,
            "joined_at": time.time(),
        }
        if executor_spec is not None:
            entry["executor"] = dict(executor_spec)
        team["members_detail"].append(entry)
    team["updated_at"] = time.time()
    _save_store()
    return _team_view(team)


@router.delete("/{team_id}/members/{member_id}")
async def remove_member(team_id: str, member_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """移除成员（A5：同租户+属主/admin）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireWritable(team, current_user)
    before = len(team["members_detail"])
    team["members_detail"] = [m for m in team["members_detail"] if m["user_id"] != member_id]
    if len(team["members_detail"]) == before:
        raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")
    team["updated_at"] = time.time()
    _save_store()
    return {"code": 0, "message": f"Member '{member_id}' removed"}


@router.put("/{team_id}/members/{member_id}/prompt")
async def update_member_prompt(team_id: str, member_id: str, body: Dict[str, Any], current_user: Dict[str, Any] = Depends(get_current_user)):
    """更新成员职责描述（A5：同租户+属主/admin）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireWritable(team, current_user)
    for m in team["members_detail"]:
        if m["user_id"] == member_id:
            m["prompt"] = str(body.get("prompt", ""))
            team["updated_at"] = time.time()
            _save_store()
            return {"code": 0, "message": "Prompt updated", "data": {"prompt": m["prompt"]}}
    raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")


@router.get("/{team_id}/members/{member_id}/prompt")
async def get_member_prompt(team_id: str, member_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取成员职责描述（A5：同租户可读）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireReadable(team, current_user)
    for m in team["members_detail"]:
        if m["user_id"] == member_id:
            return {"code": 0, "data": {"prompt": m.get("prompt", "")}}
    raise HTTPException(status_code=404, detail=f"Member '{member_id}' not found")


@router.get("/{team_id}/prompt-context")
async def get_team_prompt_context(team_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    """获取团队所有成员职责上下文（A5：同租户可读）"""
    team = _teams_store.get(team_id)
    if not team:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    _requireReadable(team, current_user)
    context = "\n\n".join(
        f"## {m.get('name', m['user_id'])}\n{m.get('prompt', '')}"
        for m in team["members_detail"] if m.get("prompt")
    )
    return {"code": 0, "data": {"prompt_context": context}}
