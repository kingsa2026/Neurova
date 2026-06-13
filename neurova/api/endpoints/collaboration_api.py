from __future__ import annotations

"""
协作接口 - Collaboration Endpoint

功能:
1. 获取协作模板 (GET /api/v1/collaboration/templates)
2. 创建协作模板 (POST /api/v1/collaboration/templates)
3. 更新协作模板 (PUT /api/v1/collaboration/templates/{id})
4. 删除协作模板 (DELETE /api/v1/collaboration/templates/{id})
5. 启动协作 (POST /api/v1/collaboration/start)
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter()

# 导入协作服务
try:
    from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager, get_collaboration_manager
except ImportError:
    logger.warning("Collaboration service not available")
    get_collaboration_manager = None
    CollaborationIsolationManager = None


class CollaborationTemplate(BaseModel):
    """协作模板"""

    template_id: str
    name: str
    description: str = ""
    workflow: Dict[str, Any] = {}
    participants: List[str] = []
    created_at: float = 0
    updated_at: float = 0


class CollaborationTemplateCreate(BaseModel):
    """创建协作模板请求"""

    name: str = Field(..., description="模板名称")
    description: str = Field(default="", description="模板描述")
    workflow: Dict[str, Any] = Field(default_factory=dict, description="工作流")
    participants: List[str] = Field(default_factory=list, description="参与者")


class CollaborationStart(BaseModel):
    """启动协作请求"""

    template_id: Optional[str] = None
    participants: List[str] = Field(default_factory=list, description="参与者")
    context: Dict[str, Any] = Field(default_factory=dict, description="上下文")


def _get_request_id(request: Request) -> str:
    """获取请求ID"""
    return getattr(request.state, "request_id", str(uuid.uuid4()))


@router.get("/templates", response_model=List[CollaborationTemplate])
async def get_collaboration_templates(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100, description="数量限制"),
):
    """获取协作模板"""
    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()

        # 获取所有项目作为模板
        projects = manager.list_projects(limit=limit)

        # 转换为模板格式
        templates = []
        for project in projects:
            templates.append(
                CollaborationTemplate(
                    template_id=project.project_id,
                    name=project.name,
                    description=project.description,
                    workflow=project.metadata.get("workflow", {}),
                    participants=list(project.members.keys()),
                    created_at=project.created_at,
                    updated_at=project.updated_at,
                )
            )

        return templates
    except Exception as e:
        logger.exception("Error getting collaboration templates: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get collaboration templates: {str(e)}")


@router.post("/templates", response_model=CollaborationTemplate)
async def create_collaboration_template(
    request: Request,
    body: CollaborationTemplateCreate,
):
    """创建协作模板"""
    _get_request_id(request)

    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()

        # 创建项目作为模板
        project = manager.create_project(
            name=body.name, description=body.description, metadata={"workflow": body.workflow}
        )

        if project is None:
            raise HTTPException(status_code=500, detail="Failed to create collaboration template")

        # 添加参与者
        for participant_id in body.participants:
            manager.add_member(project.project_id, participant_id)

        return CollaborationTemplate(
            template_id=project.project_id,
            name=project.name,
            description=project.description,
            workflow=body.workflow,
            participants=list(project.members.keys()),
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error creating collaboration template: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create collaboration template: {str(e)}")


@router.get("/templates/{template_id}", response_model=CollaborationTemplate)
async def get_collaboration_template(
    request: Request,
    template_id: str = Path(..., description="模板ID"),
):
    """获取协作模板详情"""
    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()
        project = manager.get_project(template_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

        return CollaborationTemplate(
            template_id=project.project_id,
            name=project.name,
            description=project.description,
            workflow=project.metadata.get("workflow", {}),
            participants=list(project.members.keys()),
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting collaboration template %s: %s", template_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to get collaboration template: {str(e)}")


@router.put("/templates/{template_id}", response_model=CollaborationTemplate)
async def update_collaboration_template(
    request: Request,
    template_id: str = Path(..., description="模板ID"),
    body: CollaborationTemplateCreate = CollaborationTemplateCreate(name=""),
):
    """更新协作模板"""
    _get_request_id(request)

    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()
        project = manager.get_project(template_id)

        if project is None:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

        # 更新项目信息
        if body.name:
            project.name = body.name
        if body.description:
            project.description = body.description

        # 更新工作流
        if body.workflow:
            project.metadata["workflow"] = body.workflow

        # 更新参与者
        if body.participants:
            # 移除现有成员（除了所有者）
            current_members = list(project.members.keys())
            for member_id in current_members:
                if member_id != project.owner_id and member_id not in body.participants:
                    manager.remove_member(template_id, member_id)

            # 添加新成员
            for participant_id in body.participants:
                if participant_id not in project.members:
                    manager.add_member(template_id, participant_id)

        # 保存更新
        manager._save_project(project)

        return CollaborationTemplate(
            template_id=project.project_id,
            name=project.name,
            description=project.description,
            workflow=project.metadata.get("workflow", {}),
            participants=list(project.members.keys()),
            created_at=project.created_at,
            updated_at=project.updated_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error updating collaboration template %s: %s", template_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to update collaboration template: {str(e)}")


@router.delete("/templates/{template_id}")
async def delete_collaboration_template(
    request: Request,
    template_id: str = Path(..., description="模板ID"),
):
    """删除协作模板"""
    request_id = _get_request_id(request)

    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()
        success = manager.delete_project(template_id)

        if not success:
            raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")

        return {
            "code": 0,
            "message": f"Template '{template_id}' deleted",
            "data": {"template_id": template_id},
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting collaboration template %s: %s", template_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to delete collaboration template: {str(e)}")


@router.post("/start")
async def start_collaboration(
    request: Request,
    body: CollaborationStart,
):
    """启动协作"""
    request_id = _get_request_id(request)

    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()

        # 如果指定了模板，使用模板创建新项目
        if body.template_id:
            template_project = manager.get_project(body.template_id)
            if template_project is None:
                raise HTTPException(status_code=404, detail=f"Template '{body.template_id}' not found")

            # 基于模板创建新项目
            new_project = manager.create_project(
                name=f"Collaboration from {template_project.name}",
                description=template_project.description,
                metadata={
                    "workflow": template_project.metadata.get("workflow", {}),
                    "context": body.context,
                    "template_id": body.template_id,
                },
            )
        else:
            # 创建新项目
            new_project = manager.create_project(
                name="New Collaboration", description="Started from API", metadata={"context": body.context}
            )

        if new_project is None:
            raise HTTPException(status_code=500, detail="Failed to create collaboration")

        # 添加参与者
        for participant_id in body.participants:
            manager.add_member(new_project.project_id, participant_id)

        return {
            "code": 0,
            "message": "Collaboration started",
            "data": {
                "collaboration_id": new_project.project_id,
                "template_id": body.template_id,
                "participants": list(new_project.members.keys()),
            },
            "request_id": request_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error starting collaboration: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to start collaboration: {str(e)}")


@router.get("/history")
async def get_collaboration_history(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """获取协作历史"""
    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()

        # 获取所有项目作为历史记录
        projects = manager.list_projects(limit=limit, offset=offset)

        # 转换为历史记录格式
        history = []
        for project in projects:
            history.append(
                {
                    "id": project.project_id,
                    "name": project.name,
                    "description": project.description,
                    "status": project.status.value if hasattr(project.status, "value") else str(project.status),
                    "created_at": project.created_at,
                    "updated_at": project.updated_at,
                    "members": list(project.members.keys()),
                    "owner_id": project.owner_id,
                }
            )

        return {
            "code": 0,
            "message": "success",
            "data": {
                "history": history,
                "total": len(history),
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting collaboration history: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get collaboration history: {str(e)}")
