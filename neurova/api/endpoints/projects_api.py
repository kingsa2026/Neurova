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
"""

from neurova.core.logger import get_logger
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = get_logger(__name__)

router = APIRouter()


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
# 内存存储
# ---------------------------------------------------------------------------

_projects_store: Dict[str, Dict[str, Any]] = {}


def _get_pm():
    """获取 ProjectManager"""
    try:
        from neurova.projects.project_manager import ProjectManager

        return ProjectManager()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("", response_model=ProjectInfo)
async def create_project(body: ProjectCreate):
    """创建新项目"""
    project_id = str(uuid.uuid4())
    now = time.time()

    pm = _get_pm()
    if pm and hasattr(pm, "create_project"):
        try:
            result = await pm.create_project(name=body.name, description=body.description)
            return ProjectInfo(**result)
        except Exception as e:
            logger.warning("ProjectManager.create_project failed: %s", e)

    project = {
        "project_id": project_id,
        "name": body.name,
        "description": body.description,
        "status": "active",
        "owner_id": "default",
        "teams_count": 0,
        "tasks_count": 0,
        "created_at": now,
        "updated_at": now,
    }
    _projects_store[project_id] = project
    return ProjectInfo(**project)


@router.get("", response_model=List[ProjectInfo])
async def list_projects(
    status: Optional[str] = Query(default=None, description="按状态筛选"),
):
    """列出所有项目"""
    pm = _get_pm()
    if pm and hasattr(pm, "list_projects"):
        try:
            projects = await pm.list_projects(status=status)
            return [ProjectInfo(**p) for p in projects]
        except Exception as e:
            logger.warning("ProjectManager.list_projects failed: %s", e)

    projects = list(_projects_store.values())
    if status:
        projects = [p for p in projects if p.get("status") == status]
    return [ProjectInfo(**p) for p in projects]


@router.get("/{project_id}", response_model=ProjectInfo)
async def get_project(project_id: str):
    """获取项目详情"""
    pm = _get_pm()
    if pm and hasattr(pm, "get_project"):
        try:
            project = await pm.get_project(project_id)
            if project:
                return ProjectInfo(**project)
        except Exception as e:
            logger.warning("ProjectManager.get_project failed: %s", e)

    project = _projects_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return ProjectInfo(**project)


@router.put("/{project_id}", response_model=ProjectInfo)
async def update_project(project_id: str, body: ProjectUpdate):
    """更新项目"""
    project = _projects_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    if body.name is not None:
        project["name"] = body.name
    if body.description is not None:
        project["description"] = body.description
    if body.status is not None:
        project["status"] = body.status
    project["updated_at"] = time.time()

    return ProjectInfo(**project)


@router.delete("/{project_id}")
async def delete_project(project_id: str):
    """删除项目"""
    if project_id not in _projects_store:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    del _projects_store[project_id]
    return {"code": 0, "message": "Project deleted"}


@router.get("/{project_id}/stats", response_model=ProjectStats)
async def get_project_stats(project_id: str):
    """获取项目统计"""
    project = _projects_store.get(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")

    return ProjectStats(
        project_id=project_id,
        teams_count=project.get("teams_count", 0),
        tasks_count=project.get("tasks_count", 0),
        completed_tasks=0,
        active_tasks=0,
        workflows_count=0,
    )


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
    # {type: cron|interval, cron?, interval_seconds?, timezone?}
    schedule_config: Dict[str, Any] = Field(default_factory=dict)


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


def _require_project(iso, project_id: str):
    project = iso.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail=f"Project '{project_id}' not found")
    return project


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


@router.post("/{project_id}/tasks")
async def create_project_task(project_id: str, body: ProjectTaskCreate):
    if not body.workflow_id.strip():
        raise HTTPException(status_code=400, detail="workflow_id 不能为空")

    sched_type = str(body.schedule_config.get("type", "cron"))
    if sched_type not in ("cron", "interval"):
        raise HTTPException(status_code=400, detail=f"不支持的调度类型: {sched_type}（仅 cron/interval）")

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
