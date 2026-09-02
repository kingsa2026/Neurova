"""
项目管理系统 API

提供以下端点:
- POST   /v1/projects                创建项目
- GET    /v1/projects                列出项目
- GET    /v1/projects/{project_id}   获取项目详情
- PUT    /v1/projects/{project_id}   更新项目
- DELETE /v1/projects/{project_id}   删除项目
- GET    /v1/projects/{project_id}/stats  获取项目统计

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
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()

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
):
    """列出所有项目（不含已删除）"""
    iso = _get_iso_manager()
    projects = iso.list_projects()
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
            project.archive()
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
    )


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
