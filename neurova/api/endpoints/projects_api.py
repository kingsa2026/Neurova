"""
项目管理系统 API

提供以下端点:
- POST   /v1/projects                创建项目
- GET    /v1/projects                列出项目
- GET    /v1/projects/{project_id}   获取项目详情
- PUT    /v1/projects/{project_id}   更新项目
- DELETE /v1/projects/{project_id}   删除项目
- GET    /v1/projects/{project_id}/stats  获取项目统计
"""

import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

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
            logger.warning(f"ProjectManager.create_project failed: {e}")

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
            logger.warning(f"ProjectManager.list_projects failed: {e}")

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
            logger.warning(f"ProjectManager.get_project failed: {e}")

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
