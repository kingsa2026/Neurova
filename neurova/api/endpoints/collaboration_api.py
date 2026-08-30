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

from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

logger = get_logger(__name__)

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


@router.get("/sessions")
async def list_collaboration_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """获取协作会话列表（由协作项目派生，data 为 JSON 数组，供前端 store 直接消费）"""
    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()
        projects = manager.list_projects(limit=limit, offset=offset)

        sessions = []
        for project in projects:
            sessions.append(
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

        return {"code": 0, "message": "success", "data": sessions}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error listing collaboration sessions: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list collaboration sessions: {str(e)}")


@router.get("/stats")
async def get_collaboration_stats(request: Request):
    """协作概览统计：项目/模板/进行中会话/工作流 计数"""
    if get_collaboration_manager is None:
        raise HTTPException(status_code=503, detail="Collaboration service not available")

    try:
        manager = get_collaboration_manager()
        projects = manager.list_projects()

        active_sessions = 0
        total_workflows = 0
        for project in projects:
            status_value = (
                project.status.value if hasattr(project.status, "value") else str(project.status)
            )
            if status_value == "active":
                active_sessions += 1
            try:
                workflows = manager.list_project_workflows(project.project_id)
                total_workflows += len(workflows or [])
            except Exception as e:  # noqa: BLE001 - 单项目统计失败不影响整体
                logger.debug("统计项目 %s 工作流失败: %s", project.project_id, e)

        return {
            "code": 0,
            "message": "success",
            "data": {
                "projects": len(projects),
                # 模板与项目同源（见 /templates 的派生逻辑）
                "templates": len(projects),
                # 进行中的协作会话数 = 处于 active 状态的项目数
                "sessions": active_sessions,
                "workflows": total_workflows,
            },
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error getting collaboration stats: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to get collaboration stats: {str(e)}")


# ── 画布（Canvas Designer） ────────────────────────────────────


def _get_canvas_store():
    from neurova.collaboration.canvas_store import get_canvas_store

    return get_canvas_store()


def _get_canvas_op_service():
    from neurova.collaboration.canvas_ops import get_canvas_op_service

    return get_canvas_op_service()


@router.post("/canvas")
async def create_canvas(request: Request, payload: Dict[str, Any] = Body(...)):
    """创建画布快照，返回带 id 的完整记录"""
    try:
        record = _get_canvas_store().create(payload)
        return {"code": 0, "message": "success", "data": record}
    except Exception as e:
        logger.exception("Error creating canvas: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to create canvas: {str(e)}")


@router.get("/canvas")
async def list_canvases(request: Request):
    """画布摘要列表（不含节点数据），按更新时间倒序——前端"我的画布"入口"""
    try:
        items = _get_canvas_store().list()
        return {"code": 0, "message": "success", "data": items}
    except Exception as e:
        logger.exception("Error listing canvases: %s", e)
        raise HTTPException(status_code=500, detail=f"Failed to list canvases: {str(e)}")


@router.get("/canvas/{canvas_id}")
async def get_canvas_detail(request: Request, canvas_id: str):
    """读取画布快照"""
    record = _get_canvas_store().get(canvas_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"画布不存在: {canvas_id}")
    return {"code": 0, "message": "success", "data": record}


@router.put("/canvas/{canvas_id}")
async def update_canvas_detail(
    request: Request,
    canvas_id: str,
    payload: Dict[str, Any] = Body(...),
    base_version: Optional[int] = Query(None),
):
    """更新画布快照（全量保存）

    base_version：可选乐观锁。指定时与服务端版本不一致返回 409
    （detail 含 current_version），不落盘；不指定则后写优先
    （兼容不带版本号的旧前端），版本仍递增。
    """
    from neurova.collaboration.canvas_store import CanvasVersionConflict

    try:
        record = _get_canvas_store().update(canvas_id, payload, base_version=base_version)
    except CanvasVersionConflict as e:
        raise HTTPException(
            status_code=409,
            detail={"error": str(e), "current_version": e.current_version},
        )
    if record is None:
        raise HTTPException(status_code=404, detail=f"画布不存在: {canvas_id}")
    return {"code": 0, "message": "success", "data": record}


@router.post("/canvas/{canvas_id}/ops")
async def apply_canvas_op(request: Request, canvas_id: str, body: Dict[str, Any] = Body(...)):
    """应用单个画布语义 op（agent 工具与前端共用的写入口）

    Body: {"op": "add_node|connect|set_config|move_node|remove_node|remove_edge|layout",
           ...op 参数, "base_version"?: int, "session_id"?: str, "actor"?: str}

    语义：未知画布 → 404；op 业务错误 → 400；版本冲突 → 409
    （detail 含 current_version，调用方重读后重试）。成功时经
    session_id 广播 canvas_op 事件，画布页实时渲染。
    """
    from neurova.collaboration.canvas_ops import CanvasOpError, CanvasVersionConflict

    op = str(body.get("op") or "").strip()
    common = {
        "base_version": body.get("base_version"),
        "session_id": body.get("session_id") or None,
        "actor": str(body.get("actor") or "user"),
    }
    service = _get_canvas_op_service()

    try:
        if op == "add_node":
            result = await service.add_node(
                canvas_id,
                node_type=str(body.get("node_type") or ""),
                config=body.get("config"),
                position=body.get("position"),
                label=body.get("label"),
                **common,
            )
        elif op == "connect":
            result = await service.connect(
                canvas_id,
                source_node=str(body.get("source_node") or ""),
                target_node=str(body.get("target_node") or ""),
                source_port=body.get("source_port"),
                target_port=body.get("target_port"),
                **common,
            )
        elif op == "set_config":
            result = await service.set_config(
                canvas_id,
                str(body.get("node_id") or ""),
                body.get("values") or {},
                **common,
            )
        elif op == "move_node":
            result = await service.move_node(
                canvas_id,
                str(body.get("node_id") or ""),
                float(body.get("x", 0)),
                float(body.get("y", 0)),
                **common,
            )
        elif op == "remove_node":
            result = await service.remove_node(
                canvas_id, str(body.get("node_id") or ""), **common
            )
        elif op == "remove_edge":
            result = await service.remove_edge(
                canvas_id, str(body.get("edge_id") or ""), **common
            )
        elif op == "layout":
            result = await service.apply_layout(canvas_id, **common)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的 op: {op}")
    except HTTPException:
        raise
    except CanvasVersionConflict as e:
        raise HTTPException(
            status_code=409,
            detail={"error": str(e), "current_version": e.current_version},
        )
    except CanvasOpError as e:
        status = 404 if e.code == "not_found" else 400
        raise HTTPException(status_code=status, detail=str(e))
    except (TypeError, ValueError) as e:
        raise HTTPException(status_code=400, detail=f"op 参数无效: {e}")

    record = _get_canvas_store().get(canvas_id)
    version = int(record.get("version", 0)) if record else 0
    return {
        "code": 0,
        "message": "success",
        "data": {"op": op, "version": version, "result": result},
    }


@router.delete("/canvas/{canvas_id}")
async def delete_canvas_detail(request: Request, canvas_id: str):
    """删除画布快照（工作流=画布工作流，删除即删除该工作流）"""
    deleted = _get_canvas_store().delete(canvas_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"画布不存在: {canvas_id}")
    return {"code": 0, "message": "success", "data": {"id": canvas_id, "deleted": True}}


@router.post("/comfyui/import-canvas")
async def import_comfyui_as_canvas(request: Request, payload: Dict[str, Any] = Body(...)):
    """导入 ComfyUI 工作流 JSON 直接落为画布快照

    工作流 = 无限画布工作流：导入结果是一张可编辑画布，
    而非独立的 neurflow 工作流定义（定义只是执行时的内部编译产物）。
    Body: {name, description?, workflow: ComfyUI API JSON}
    """
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="缺少工作流名称")
    comfy_workflow = payload.get("workflow")
    if not isinstance(comfy_workflow, dict) or not comfy_workflow:
        raise HTTPException(status_code=400, detail="缺少 ComfyUI 工作流 JSON")

    try:
        from neurova.collaboration.neurflow.comfyui_importer import import_comfyui_workflow
        from neurova.collaboration.neurflow.node_registry import get_node_registry
        from neurova.collaboration.canvas_bridge import definition_to_canvas

        try:
            from neurova.collaboration.neurflow import comfyui_nodes

            comfyui_nodes.register_comfyui_nodes(get_node_registry())
        except Exception:  # noqa: BLE001 - comfyui 节点注册失败不阻断导入（端口留空）
            logger.warning("comfyui 节点注册失败，导入画布端口为空", exc_info=True)

        definition = import_comfyui_workflow(
            comfy_workflow, name=name, description=str(payload.get("description") or "")
        )
        snapshot = definition_to_canvas(definition, name=name)
        snapshot.pop("metadata", None)
        record = _get_canvas_store().create(snapshot)
        return {"code": 0, "message": "success", "data": record}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        logger.exception("Error importing comfyui canvas: %s", e)
        raise HTTPException(status_code=500, detail=f"导入画布失败: {str(e)}")


@router.post("/canvas/{canvas_id}/run")
async def run_canvas_workflow(request: Request, canvas_id: str, body: Dict[str, Any] = None):
    """执行画布工作流（画布快照 → neurflow WorkflowDefinition → 执行引擎）

    Body（可选）: {"session_id": "聊天会话ID"} —— 工作流内 agent 节点派生的
    子 Agent 事件将广播到该会话（聊天页子 Agent 小窗的数据源）。

    返回: {runId: neurflow execution_id, status}，用
    GET /canvas/{canvas_id}/runs/{run_id} 轮询执行状态。
    """
    record = _get_canvas_store().get(canvas_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"画布不存在: {canvas_id}")

    body = body or {}
    session_id = body.get("session_id")

    try:
        from neurova.collaboration.canvas_bridge import canvas_to_workflow
        from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

        workflow = canvas_to_workflow(record, name=record.get("name") or canvas_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"画布转换失败: {str(e)}")

    executor = get_workflow_executor()
    execution = executor.create_instance(workflow, inputs={}, user_id="canvas")

    # 后台执行（立即返回 execution_id 供前端轮询；session_id 透传给蜂群事件）
    import asyncio

    asyncio.create_task(
        executor.execute(
            workflow,
            inputs={},
            user_id="canvas",
            agent_id=body.get("agent_id"),
            session_id=session_id,
            instance=execution,
        )
    )

    return {
        "code": 0,
        "message": "accepted",
        "data": {
            "runId": execution.id,
            "status": "running",
            "workflow_id": workflow.id,
        },
    }


@router.get("/canvas/{canvas_id}/runs/{run_id}")
async def get_canvas_run_status(canvas_id: str, run_id: str):
    """查询画布运行状态（代理 neurflow execution）"""
    from neurova.collaboration.neurflow.execution_engine import (
        ExecutionStatus,
        get_workflow_executor,
    )

    executor = get_workflow_executor()
    instance = executor._instances.get(run_id)
    if instance is None:
        raise HTTPException(status_code=404, detail=f"运行不存在: {run_id}")

    engine_status = executor.get_status(run_id)
    return {
        "code": 0,
        "message": "success",
        "data": {
            "run_id": run_id,
            "canvas_id": canvas_id,
            "status": engine_status.value if hasattr(engine_status, "value") else str(engine_status),
            "node_results": {
                nid: {
                    "status": r.status,
                    "output": r.output,
                    "error": r.error,
                    "duration": r.duration,
                }
                for nid, r in (instance.node_results or {}).items()
            },
            "outputs": instance.outputs or {},
            "error": instance.error,
            "duration": instance.duration,
        },
    }
