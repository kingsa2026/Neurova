"""
项目管理系统 API

提供以下端点:
- POST   /v1/projects                创建项目
- GET    /v1/projects                列出项目
- GET    /v1/projects/{project_id}   获取项目详情
- PUT    /v1/projects/{project_id}   更新项目
- DELETE /v1/projects/{project_id}   删除项目
- GET    /v1/projects/{project_id}/stats  获取项目统计
- GET    /v1/projects/{project_id}/collaboration  项目协作档案（S12：留底+可观测）

团队与任务（轻量脚手架，数据持久化在 collaboration_isolation.Project）:
- POST/GET /v1/projects/{project_id}/teams
- POST /v1/projects/{project_id}/teams/{team_id}/members
- GET  /v1/projects/{project_id}/teams/{team_id}/agents
- POST /v1/projects/{project_id}/tasks            （注册 Workflow 定时作业）
- POST /v1/projects/{project_id}/tasks/{task_id}/pause|resume

数据源说明：项目 CRUD 与团队/任务统一走 collaboration_isolation 管理器
（单一数据源 + 落盘持久化）。历史上这里曾用内存 dict / 不存在的
ProjectManager 做兜底，与团队任务的存储不同源，导致建完项目后
/teams、/tasks 恒 404 且重启丢数据 —— 该路径已删除。
"""

from neurova.core.logger import get_logger
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from neurova.api.auth import get_current_user, Depends
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter(dependencies=[Depends(get_current_user)],)

# 无鉴权上下文时的默认所有者（API 层暂无用户会话，权限校验在 manager 内按成员角色执行）
_DEFAULT_OWNER = "default"


class ProjectInfo(BaseModel):
    """项目信息"""

    project_id: str
    name: str
    description: str = ""
    status: str = "active"
    owner_id: str = ""
    teams_count: int = 0
    tasks_count: int = 0
    created_at: float = 0
    updated_at: float = 0


class ProjectCreate(BaseModel):
    """创建项目请求"""

    name: str = Field(..., description="项目名称")
    description: str = Field(default="", description="项目描述")


class ProjectUpdate(BaseModel):
    """更新项目请求"""

    name: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None


class ProjectStats(BaseModel):
    """项目统计"""

    project_id: str
    teams_count: int = 0
    tasks_count: int = 0
    completed_tasks: int = 0
    active_tasks: int = 0
    workflows_count: int = 0
    # S12：协作 run 数（台账按项目标；向后兼容新增字段，缺省 0）
    runs_count: int = 0


# ---------------------------------------------------------------------------
# 数据源：collaboration_isolation（单一存储）
# ---------------------------------------------------------------------------


def _get_iso_manager():
    """获取协作隔离管理器（项目持久化存储）"""
    from neurova.collaboration.collaboration_isolation import get_collaboration_manager

    return get_collaboration_manager()


def _get_scheduler():
    """获取 TaskScheduler 单例（不可用时返回 None，任务仅落库不调度）"""
    try:
        from neurova.agent.scheduler import get_scheduler

        return get_scheduler()
    except Exception as e:  # noqa: BLE001
        logger.warning("TaskScheduler 不可用，任务将不会定时执行: %s", e)
        return None


def _project_to_info(project) -> ProjectInfo:
    """Project → ProjectInfo（对外 API 形状）"""
    return ProjectInfo(
        project_id=project.project_id,
        name=project.name,
        description=project.description,
        status=project.status.value,
        owner_id=project.owner_id,
        teams_count=len(project.teams),
        tasks_count=len(project.tasks),
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _require_project(iso, project_id: str):
    """取项目；不存在或已软删除 → 404"""
    project = iso.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    from neurova.collaboration.collaboration_isolation import ProjectStatus

    if project.status == ProjectStatus.DELETED:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project


# ---------------------------------------------------------------------------
# 路由：项目 CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=ProjectInfo)
async def create_project(body: ProjectCreate):
    """创建新项目（持久化到 collaboration/projects 目录）"""
    iso = _get_iso_manager()
    project = iso.create_project(name=body.name, description=body.description, owner_id=_DEFAULT_OWNER)
    if project is None:
        raise HTTPException(status_code=500, detail="项目创建失败")
    return _project_to_info(project)


@router.get("", response_model=List[ProjectInfo])
async def list_projects(
    status: Optional[str] = Query(default=None, description="按状态筛选"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出项目（不含已删除）。

    审计 §3.4-2（R6 接线最后一公里）：isolation 层 R4 已落地 requester 过滤，
    此处此前漏传——普通用户按「成员或公开可见」过滤，admin 全量。
    """
    iso = _get_iso_manager()
    requester_id = str(current_user.get("user_id") or "default")
    is_admin = str(current_user.get("role") or "") == "admin"
    projects = iso.list_projects(requester_id=None if is_admin else requester_id)
    if status:
        projects = [p for p in projects if p.status.value == status]
    return [_project_to_info(p) for p in projects]


@router.get("/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str):
    """获取项目详情"""
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    return _project_to_info(project)


@router.put("/{project_id}", response_model=ProjectInfo)
async def update_project(project_id: str, body: ProjectUpdate):
    """更新项目（名称/描述经 manager 权限校验；状态映射 archive/restore）"""
    from neurova.collaboration.collaboration_isolation import ProjectStatus

    iso = _get_iso_manager()
    project = _require_project(iso, project_id)

    updates: Dict[str, Any] = {}
    if body.name is not None:
        updates["name"] = body.name
    if body.description is not None:
        updates["description"] = body.description

    if updates:
        updated = iso.update_project(project_id, _DEFAULT_OWNER, updates)
        if updated is None:
            raise HTTPException(status_code=403, detail="无权限更新项目")
        project = updated

    if body.status is not None:
        if body.status == "deleted":
            raise HTTPException(status_code=400, detail="请使用 DELETE 端点删除项目")
        try:
            new_status = ProjectStatus(body.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"无效的项目状态: {body.status}")

        if new_status == ProjectStatus.ARCHIVED:
            wasArchived = project.status == ProjectStatus.ARCHIVED
            project.archive()
            # S12 封卷钩子：active → archived 的真实迁移才封卷（重复归档不重算）
            if not wasArchived:
                _sealCollaborationDossier(project, iso)
        elif new_status == ProjectStatus.ACTIVE:
            project.restore()
        else:
            project.status = new_status
            project.updated_at = time.time()
        iso._save_project(project)

    return _project_to_info(project)


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """删除项目（软删除，数据保留在磁盘）"""
    iso = _get_iso_manager()
    _require_project(iso, project_id)

    if not iso.delete_project(project_id, _DEFAULT_OWNER):
        raise HTTPException(status_code=403, detail="无权限删除项目")
    return {"code": 0, "message": "Project deleted"}


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def get_project_stats(project_id: str):
    """获取项目统计（团队/任务来自项目存储；工作流计数=画布快照按 project_id 归属）"""
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)

    return ProjectStats(
        project_id=project_id,
        teams_count=len(project.teams),
        tasks_count=len(project.tasks),
        completed_tasks=0,
        active_tasks=sum(1 for t in project.tasks.values() if t.status == "active"),
        workflows_count=_count_project_workflows(project_id),
        runs_count=_count_project_runs(project_id),
    )


def _count_project_runs(project_id: str) -> int:
    """项目标协作 run 数（台账单源计数；台账不可用回退 0，不阻断统计面）。"""
    try:
        return _get_run_store().count_runs_by_project(project_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("项目 run 计数不可用 (project=%s): %s", project_id, e)
        return 0


def _count_project_workflows(project_id: str) -> int:
    """项目下工作流数（画布快照归属，真实统计；异常回退 0）。"""
    try:
        from neurova.collaboration.canvas_store import get_canvas_store

        return sum(1 for w in get_canvas_store().list() if w.get("project_id") == project_id)
    except Exception:
        return 0


@router.get("/{project_id}/workflows")
async def list_project_workflows(project_id: str):
    """项目下工作流列表（画布快照按 project_id 归属）——项目顶层模型：

    项目包含 协作（画布）/ 团队 / 工作流，本端点供项目详情页展示工作流归属。
    """
    iso = _get_iso_manager()
    _require_project(iso, project_id)

    try:
        from neurova.collaboration.canvas_store import get_canvas_store

        items = [w for w in get_canvas_store().list() if w.get("project_id") == project_id]
        return {"code": 0, "message": "success", "data": items}
    except Exception as e:
        logger.exception("list project workflows failed: %s", e)
        raise HTTPException(status_code=500, detail=f"list project workflows failed: {e}")


# ---------------------------------------------------------------------------
# S12 项目协作档案：留底 + 可观测（读时 join 既有持久面，不建第二本账）
# ---------------------------------------------------------------------------

#: 档案脱敏纪律（与账本同源）：正文不进档案投影——消息/候选/任务只出摘要与句柄。
#: 截断上限一律具名常量（"正文不得按字面量砍长度"钉子）。
DOSSIER_MESSAGE_SUMMARY_CHARS = 200
DOSSIER_CANDIDATE_SUMMARY_CHARS = 200
DOSSIER_RUN_LIMIT = 100
DOSSIER_ROOM_MESSAGE_LIMIT = 100
DOSSIER_EVENTS_PER_RUN_LIMIT = 50
DOSSIER_APPROVAL_LIMIT_PER_RUN = 50
#: 封卷总结在 project.metadata 里的留底键（随项目 JSON 落盘，重启可回读）
DOSSIER_SUMMARY_META_KEY = "collaborationSummary"
#: 封卷总结收录的关键事件类型（H-4 账本事件名的既有词表子集）
DOSSIER_SUMMARY_KEY_EVENT_TYPES = frozenset({
    "spawned", "started", "terminal", "cancelled", "escalated",
    "candidate_submitted", "candidate_merged", "candidate_conflict",
    "candidate_rejected", "status_corrected",
})


def _get_run_store():
    """run 台账单例（依赖注入点，测试可换桩）。"""
    from neurova.core.agent_run_store import get_agent_run_store

    return get_agent_run_store()


def _get_swarm_manager():
    """蜂群管理器单例（候选板读面入口；依赖注入点，测试可换桩）。"""
    from neurova.agent.swarm import get_swarm_manager

    return get_swarm_manager()


def _get_room_store():
    """房间消息存储单例（依赖注入点，测试可换桩）。"""
    from neurova.collaboration.room_store import get_room_store

    return get_room_store()


def _get_audit_logger():
    """审计单源（S8 审批审计查询；依赖注入点，测试可换桩）。"""
    from neurova.security.audit_logger import get_audit_logger

    return get_audit_logger()


def _summarizeText(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    return value[:limit] if len(value) > limit else value


def _runProjection(row: Dict[str, Any]) -> Dict[str, Any]:
    """台账行 → 档案 run 投影（状态/归属/句柄 + 任务摘要，不搬运任务正文）。"""
    return {
        "run_id": row.get("run_id", ""),
        "subagent_id": row.get("subagent_id", ""),
        "agent_id": row.get("agent_id", ""),
        "user_id": row.get("user_id", ""),
        "parent_session_id": row.get("parent_session_id") or "",
        "status": row.get("status", ""),
        "error_type": row.get("error_type") or "",
        "project_id": row.get("project_id") or "",
        "team_id": row.get("team_id") or "",
        "task_summary": _summarizeText(row.get("message_digest") or "",
                                       DOSSIER_MESSAGE_SUMMARY_CHARS),
        "created_at": row.get("created_at"),
        "started_at": row.get("started_at"),
        "finished_at": row.get("finished_at"),
    }


def _eventProjection(event: Dict[str, Any]) -> Dict[str, Any]:
    """H-4 账本事件 → 档案时间线投影（账本本身只存摘要，原样透传 payload）。"""
    return {
        "event_id": event.get("event_id", ""),
        "subagent_id": event.get("subagent_id", ""),
        "type": event.get("type", ""),
        "causation_id": event.get("causation_id", ""),
        "occurred_at": event.get("occurred_at"),
        "payload": event.get("payload") or {},
    }


def _candidateProjection(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """候选 → 档案投影：状态/裁决句柄 + 内容摘要（全文仍在 member 会话）。"""
    return {
        "candidate_id": candidate.get("candidate_id", ""),
        "run_id": candidate.get("run_id", ""),
        "status": candidate.get("status", ""),
        "artifact_keys": candidate.get("artifact_keys") or [],
        "base_revision": candidate.get("base_revision"),
        "conflict_with": candidate.get("conflict_with") or [],
        "note": candidate.get("note") or "",
        "created_at": candidate.get("created_at"),
        "decided_at": candidate.get("decided_at"),
        "content_summary": _summarizeText(candidate.get("content") or "",
                                          DOSSIER_CANDIDATE_SUMMARY_CHARS),
    }


def _roomMessageProjection(message: Dict[str, Any]) -> Dict[str, Any]:
    """房间消息 → 档案投影：发送者归属 + 系统消息 kind + 内容摘要。"""
    meta = message.get("meta") or {}
    return {
        "sender_type": message.get("sender_type", ""),
        "sender_id": message.get("sender_id", ""),
        "kind": meta.get("kind", "") if isinstance(meta, dict) else "",
        "ts": message.get("ts"),
        "content_summary": _summarizeText(message.get("content") or "",
                                          DOSSIER_MESSAGE_SUMMARY_CHARS),
    }


def _approvalTrajectory(runId: str, limit: int) -> List[Dict[str, Any]]:
    """S8 审批审计单源查询：按 run 拉请求+决定成对轨迹（审计面不可用返回空）。"""
    try:
        from neurova.security.audit_logger import AuditEventType

        entries = _get_audit_logger().query(
            event_type=AuditEventType.APPROVAL, resource_id=runId, limit=limit)
    except Exception as e:  # noqa: BLE001 - 审计面故障不阻断档案主体
        logger.debug("档案审批审计查询失败 (run=%s): %s", runId, e)
        return []
    entries = sorted(entries, key=lambda e: e.timestamp)
    paired: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for entry in entries:
        details = entry.details or {}
        requestId = str(details.get("request_id") or "")
        if not requestId:
            continue
        if requestId not in paired:
            paired[requestId] = {"request": None, "decision": None}
            order.append(requestId)
        shape = {
            "timestamp": entry.timestamp,
            "phase": details.get("phase"),
            "level": details.get("level"),
            "effective_level": details.get("effective_level"),
            "operation": details.get("operation"),
            "reason": details.get("reason"),
            "decision": details.get("decision"),
            "decided_by": details.get("decided_by"),
            "user_id": entry.user_id,
        }
        if details.get("phase") == "decide":
            if paired[requestId]["decision"] is None:
                paired[requestId]["decision"] = shape
        elif paired[requestId]["request"] is None:
            paired[requestId]["request"] = shape
    items: List[Dict[str, Any]] = []
    for requestId in order:
        requestShape = paired[requestId]["request"] or {}
        decideShape = paired[requestId]["decision"] or {}
        items.append({
            "request_id": requestId,
            "run_id": runId,
            "level": requestShape.get("level") or decideShape.get("level"),
            "operation": requestShape.get("operation") or decideShape.get("operation"),
            "reason": requestShape.get("reason"),
            "status": "decided" if paired[requestId]["decision"] else "pending",
            "decision": decideShape.get("decision"),
            "decided_by": decideShape.get("decided_by"),
            "requested_at": requestShape.get("timestamp"),
            "decided_at": decideShape.get("timestamp"),
        })
    return items


def build_collaboration_dossier(project_id: str) -> Dict[str, Any]:
    """项目协作档案聚合（S12 核心）：五类记录**读时 join**，全部走既有单源 API。

    - 房间消息：RoomStore（``room_id = project_id`` 既有等式）
    - run 列表：agent_runs 台账按 project_id 标（无标 run 不归属任何项目）
    - 事件时间线：H-4 账本按 run 归属拉取（readRunEvents）
    - 候选记录：S4 候选板（SwarmManager.candidateRecordsForRuns）
    - 审批审计：S8 审计单源（APPROVAL 事件按 resource_id=run 成对）

    不建第二本账、不直接翻文件；任一账本不可用时该类记录为空（fail-open），
    档案主体仍可读。
    """
    try:
        runRows = _get_run_store().list_runs_by_project(project_id, limit=DOSSIER_RUN_LIMIT)
    except Exception as e:  # noqa: BLE001
        logger.debug("档案台账读取失败 (project=%s): %s", project_id, e)
        runRows = []
    runs = [_runProjection(r) for r in runRows]
    subagentIds = [str(r.get("subagent_id") or "") for r in runRows if r.get("subagent_id")]

    from neurova.agent.swarm_event_log import readRunEvents

    events: List[Dict[str, Any]] = []
    for sid in subagentIds:
        try:
            runEvents = readRunEvents(sid)[:DOSSIER_EVENTS_PER_RUN_LIMIT]
        except Exception as e:  # noqa: BLE001
            logger.debug("档案事件读取失败 (run=%s): %s", sid, e)
            runEvents = []
        events.extend(_eventProjection(e) for e in runEvents)
    events.sort(key=lambda e: str(e.get("occurred_at") or ""))

    try:
        candidates = [_candidateProjection(c)
                      for c in _get_swarm_manager().candidateRecordsForRuns(subagentIds)]
    except Exception as e:  # noqa: BLE001
        logger.debug("档案候选读取失败 (project=%s): %s", project_id, e)
        candidates = []

    approvals: List[Dict[str, Any]] = []
    for sid in subagentIds:
        approvals.extend(_approvalTrajectory(sid, DOSSIER_APPROVAL_LIMIT_PER_RUN))

    try:
        roomMessages = [_roomMessageProjection(m)
                        for m in _get_room_store().history(project_id,
                                                           limit=DOSSIER_ROOM_MESSAGE_LIMIT)]
    except Exception as e:  # noqa: BLE001
        logger.debug("档案房间消息读取失败 (project=%s): %s", project_id, e)
        roomMessages = []

    return {
        "project_id": project_id,
        "generated_at": time.time(),
        "runs": runs,
        "events": events,
        "candidates": candidates,
        "approvals": approvals,
        "room_messages": roomMessages,
        "counts": {
            "runs": len(runs),
            "events": len(events),
            "candidates": len(candidates),
            "approvals": len(approvals),
            "room_messages": len(roomMessages),
        },
    }


def build_collaboration_summary(project_id: str) -> Dict[str, Any]:
    """封卷总结：从档案聚合中提炼协作留底（参与 run/候选收驳/审批/关键事件链）。"""
    dossier = build_collaboration_dossier(project_id)
    keyEvents = [
        {"subagent_id": e["subagent_id"], "type": e["type"],
         "occurred_at": e["occurred_at"]}
        for e in dossier["events"] if e["type"] in DOSSIER_SUMMARY_KEY_EVENT_TYPES
    ]
    return {
        "closed_at": time.time(),
        "runs_count": dossier["counts"]["runs"],
        "events_count": dossier["counts"]["events"],
        "candidates_total": len(dossier["candidates"]),
        "candidates_accepted": sum(1 for c in dossier["candidates"] if c["status"] == "accepted"),
        "candidates_rejected": sum(1 for c in dossier["candidates"] if c["status"] == "rejected"),
        "approvals_total": len(dossier["approvals"]),
        "approvals_decided": sum(1 for a in dossier["approvals"] if a["status"] == "decided"),
        "key_events": keyEvents,
    }


def _sealCollaborationDossier(project, iso) -> None:
    """封卷钩子：项目归档时从账本生成协作总结，落项目档案（metadata）留底。

    fail-open：总结生成失败不阻断归档——档案读面随时可重算，留底失败只记日志。
    """
    try:
        summary = build_collaboration_summary(project.project_id)
        metadata = getattr(project, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            project.metadata = metadata
        metadata[DOSSIER_SUMMARY_META_KEY] = summary
        iso._save_project(project)
        logger.info("项目 %s 已封卷：协作总结留底（runs=%s）",
                    project.project_id, summary.get("runs_count"))
    except Exception as e:  # noqa: BLE001
        logger.warning("项目 %s 封卷总结生成失败（归档不受影响）: %s", project.project_id, e)


@router.get("/{project_id}/collaboration")
async def get_project_collaboration(project_id: str):
    """项目协作档案（S12）：五类记录聚合读面——留底 + 可观测。

    聚合房间消息 / run 台账 / H-4 事件时间线 / S4 候选 / S8 审批审计，全部读
    既有持久面读时 join（不建第二本账）；正文按账本纪律只出摘要与句柄。
    已封卷项目的协作总结（留底）随档案一并返回。
    """
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    data = build_collaboration_dossier(project_id)
    data["summary"] = (getattr(project, "metadata", {}) or {}).get(DOSSIER_SUMMARY_META_KEY)
    return {"code": 0, "message": "success", "data": data}


# ---------------------------------------------------------------------------
# 团队与任务（轻量脚手架：复用 collaboration_isolation.Project 持久化 +
# agent/scheduler.TaskScheduler 的 WorkflowTaskExecutor 定时执行）
# ---------------------------------------------------------------------------


class TeamCreate(BaseModel):
    name: str = Field(..., description="团队名称")
    description: str = ""


class TeamMemberAdd(BaseModel):
    agent_id: str = Field(..., description="Agent ID")
    agent_name: str = ""
    role: str = "member"


class ProjectTaskCreate(BaseModel):
    name: str = Field(..., description="任务名称")
    workflow_id: str = Field(..., description="画布工作流 ID")
    description: str = ""
    # {type: cron|interval, cron?, interval_seconds?, timezone?, start_date?, end_date?}
    schedule_config: Dict[str, Any] = Field(default_factory=dict)


@router.post("/{project_id}/teams")
async def create_project_team(project_id: str, body: TeamCreate):
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)

    from neurova.collaboration.collaboration_isolation import ProjectTeam

    team = ProjectTeam(name=body.name, description=body.description)
    project.add_team(team)
    iso._save_project(project)
    return {"code": 0, "message": "success", "data": team.to_dict()}


@router.get("/{project_id}/teams")
async def list_project_teams(project_id: str):
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    return {"code": 0, "message": "success", "data": {"teams": [t.to_dict() for t in project.teams.values()]}}


def _require_team(project, team_id: str):
    team = project.get_team(team_id)
    if team is None:
        raise HTTPException(status_code=404, detail=f"Team '{team_id}' not found")
    return team


@router.post("/{project_id}/teams/{team_id}/members")
async def add_team_member(project_id: str, team_id: str, body: TeamMemberAdd):
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    team = _require_team(project, team_id)

    team.members[body.agent_id] = {"agent_name": body.agent_name, "role": body.role}
    iso._save_project(project)
    return {"code": 0, "message": "success", "data": team.to_dict()}


@router.get("/{project_id}/teams/{team_id}/agents")
async def list_team_agents(project_id: str, team_id: str):
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    team = _require_team(project, team_id)
    agents = [{"agent_id": aid, **info} for aid, info in team.members.items()]
    return {"code": 0, "message": "success", "data": {"agents": agents}}


@router.get("/{project_id}/tasks")
async def list_project_tasks(project_id: str):
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    return {"code": 0, "message": "success", "data": {"tasks": [t.to_dict() for t in project.tasks.values()]}}


def _parse_schedule_datetime(value: Any, field: str) -> Optional[datetime]:
    """解析 ISO 8601 日期边界（start_date/end_date）；非法值 → 400"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"无效的 {field}: {value!r}（需 ISO 8601 格式，如 2026-09-01T09:30:00）",
        )


@router.post("/{project_id}/tasks")
async def create_project_task(project_id: str, body: ProjectTaskCreate):
    if not body.workflow_id.strip():
        raise HTTPException(status_code=400, detail="workflow_id 不能为空")

    sched_type = str(body.schedule_config.get("type", "cron"))
    if sched_type not in ("cron", "interval"):
        raise HTTPException(status_code=400, detail=f"不支持的调度类型: {sched_type}（仅 cron/interval）")

    # 日期边界（一次性任务靠 end_date 防止 cron 周年重复触发）
    start_dt = _parse_schedule_datetime(body.schedule_config.get("start_date"), "start_date")
    end_dt = _parse_schedule_datetime(body.schedule_config.get("end_date"), "end_date")

    iso = _get_iso_manager()
    project = _require_project(iso, project_id)

    from neurova.collaboration.collaboration_isolation import ProjectTask

    task = ProjectTask(
        name=body.name,
        workflow_id=body.workflow_id,
        schedule_config=dict(body.schedule_config),
        metadata={"description": body.description, "project_id": project_id},
    )
    project.add_task(task)
    iso._save_project(project)

    # 注册到调度器（WorkflowTaskExecutor 按 target.workflow_id 执行画布工作流）
    scheduler = _get_scheduler()
    if scheduler is not None:
        try:
            from neurova.agent.scheduler import (
                AutomationTask,
                ScheduleConfig,
                TaskRequest,
                TaskType,
                TriggerType,
            )

            automation_task = AutomationTask(
                id=task.task_id,
                name=task.name,
                description=body.description or None,
                type=TaskType.WORKFLOW,
                schedule=ScheduleConfig(
                    type=TriggerType(sched_type),
                    cron=body.schedule_config.get("cron"),
                    interval_seconds=body.schedule_config.get("interval_seconds"),
                    timezone=str(body.schedule_config.get("timezone", "Asia/Shanghai")),
                    start_date=start_dt,
                    end_date=end_dt,
                ),
                request=TaskRequest(
                    type=TaskType.WORKFLOW,
                    workflow_id=task.workflow_id,
                    input={"project_id": project_id},
                ),
                tags=[f"project:{project_id}"],
            )
            scheduler.add_task(automation_task)
        except Exception as e:  # noqa: BLE001
            logger.warning("注册定时作业失败（任务已保存）: %s", e)

    return {"code": 0, "message": "success", "data": task.to_dict()}


def _set_task_status(project_id: str, task_id: str, status: str) -> Dict[str, Any]:
    iso = _get_iso_manager()
    project = _require_project(iso, project_id)
    task = project.get_task(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    task.status = status
    iso._save_project(project)

    scheduler = _get_scheduler()
    if scheduler is not None:
        try:
            if status == "paused":
                scheduler.disable_task(task_id)
            else:
                scheduler.enable_task(task_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("更新调度器作业状态失败: %s", e)

    return task.to_dict()


@router.post("/{project_id}/tasks/{task_id}/pause")
async def pause_project_task(project_id: str, task_id: str):
    return {"code": 0, "message": "success", "data": _set_task_status(project_id, task_id, "paused")}


@router.post("/{project_id}/tasks/{task_id}/resume")
async def resume_project_task(project_id: str, task_id: str):
    return {"code": 0, "message": "success", "data": _set_task_status(project_id, task_id, "active")}
