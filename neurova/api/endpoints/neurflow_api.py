"""
Neurflow API — 工作流管理端点
提供工作流 CRUD、执行、节点注册、DAG 验证等 RESTful 接口
"""
import time
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, Body

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowVariable,
    WorkflowStatus, NodeDefinition, SubBlockConfig, NodePort,
    ExecutionInstance, NodeExecutionResult
)
from neurova.collaboration.neurflow.storage import NeurflowStorage
from neurova.collaboration.neurflow.node_registry import get_node_registry
from neurova.collaboration.neurflow.dag import get_dag_validator
from neurova.collaboration.neurflow.execution_engine import get_workflow_executor

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_storage() -> NeurflowStorage:
    """获取存储实例（延迟初始化）"""
    if not hasattr(_get_storage, "_instance"):
        _get_storage._instance = NeurflowStorage()
    return _get_storage._instance


# ==================== 工作流 CRUD ====================

@router.get("/workflows")
async def list_workflows(
    category: Optional[str] = Query(None, description="按分类过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """列出工作流"""
    storage = _get_storage()
    ws_status = WorkflowStatus(status) if status else None
    workflows = storage.list_workflows(
        category=category, status=ws_status, limit=limit, offset=offset
    )
    return {"workflows": [w.to_dict() for w in workflows], "total": len(workflows)}


@router.post("/workflows")
async def create_workflow(data: Dict[str, Any] = Body(...)):
    """创建工作流"""
    storage = _get_storage()
    try:
        workflow = WorkflowDefinition.from_dict(data)
        workflow.created_at = time.time()
        workflow.updated_at = time.time()
        storage.save_workflow(workflow)
        return {"workflow": workflow.to_dict(), "message": "工作流创建成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建工作流失败: {str(e)}")


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str):
    """获取工作流详情"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"workflow": workflow.to_dict()}


@router.put("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, data: Dict[str, Any] = Body(...)):
    """更新工作流"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")
    try:
        workflow = WorkflowDefinition.from_dict(data)
        workflow.id = workflow_id
        workflow.updated_at = time.time()
        storage.save_workflow(workflow)
        return {"workflow": workflow.to_dict(), "message": "工作流更新成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新工作流失败: {str(e)}")


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str):
    """删除工作流"""
    storage = _get_storage()
    result = storage.delete_workflow(workflow_id)
    if not result:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"message": "工作流删除成功"}


@router.get("/workflows/search/{query}")
async def search_workflows(query: str):
    """搜索工作流"""
    storage = _get_storage()
    workflows = storage.search_workflows(query)
    return {"workflows": [w.to_dict() for w in workflows], "total": len(workflows)}


# ==================== 工作流验证 ====================

@router.post("/workflows/{workflow_id}/validate")
async def validate_workflow(workflow_id: str):
    """验证工作流"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    validator = get_dag_validator()
    result = validator.validate(workflow.nodes, workflow.edges)
    return {
        "is_valid": result.is_valid,
        "has_cycle": result.has_cycle,
        "has_start": result.has_start,
        "has_end": result.has_end,
        "errors": result.errors,
        "warnings": result.warnings
    }


# ==================== 工作流执行 ====================

@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    inputs: Dict[str, Any] = Body(default={}),
    user_id: Optional[str] = Body(default=None),
    agent_id: Optional[str] = Body(default=None),
):
    """执行工作流"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    executor = get_workflow_executor()
    instance = await executor.execute(
        workflow=workflow,
        inputs=inputs,
        user_id=user_id,
        agent_id=agent_id
    )
    
    # 保存执行实例
    storage.save_execution(instance)
    
    return {"instance": {
        "id": instance.id,
        "workflow_id": instance.workflow_id,
        "status": instance.status.value,
        "inputs": instance.inputs,
        "outputs": instance.outputs,
        "node_results": {k: v.__dict__ for k, v in instance.node_results.items()},
        "variables": instance.variables,
        "started_at": instance.started_at,
        "finished_at": instance.finished_at,
        "duration": instance.duration,
        "error": instance.error,
    }}


@router.get("/executions")
async def list_executions(
    workflow_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """列出执行记录"""
    storage = _get_storage()
    ws_status = WorkflowStatus(status) if status else None
    executions = storage.list_executions(
        workflow_id=workflow_id, status=ws_status, limit=limit, offset=offset
    )
    return {"executions": [{
        "id": e.id,
        "workflow_id": e.workflow_id,
        "status": e.status.value,
        "started_at": e.started_at,
        "finished_at": e.finished_at,
        "duration": e.duration,
        "error": e.error,
    } for e in executions]}


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    """获取执行详情"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return {"execution": {
        "id": execution.id,
        "workflow_id": execution.workflow_id,
        "status": execution.status.value,
        "inputs": execution.inputs,
        "outputs": execution.outputs,
        "node_results": {k: v.__dict__ for k, v in execution.node_results.items()},
        "variables": execution.variables,
        "started_at": execution.started_at,
        "finished_at": execution.finished_at,
        "duration": execution.duration,
        "error": execution.error,
    }}


# ==================== 节点注册表 ====================

@router.get("/nodes")
async def list_nodes(
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    """列出所有已注册节点"""
    registry = get_node_registry()
    
    if category:
        nodes = registry.list_by_category(category)
    elif source:
        nodes = registry.list_by_source(source)
    else:
        nodes = registry.list_all()
    
    return {"nodes": [{
        "type": n.type,
        "label": n.label,
        "icon": n.icon,
        "category": n.category,
        "description": n.description,
        "source": n.source,
        "version": n.version,
        "tags": n.tags,
    } for n in nodes], "total": len(nodes)}


@router.get("/nodes/search/{query}")
async def search_nodes(query: str):
    """搜索节点"""
    registry = get_node_registry()
    results = registry.search(query)
    return {"nodes": [{
        "type": n.type,
        "label": n.label,
        "icon": n.icon,
        "category": n.category,
        "description": n.description,
        "source": n.source,
        "tags": n.tags,
    } for n in results], "total": len(results)}


@router.post("/nodes/sync")
async def sync_nodes():
    """同步所有节点（工具/技能/MCP）"""
    registry = get_node_registry()
    result = registry.sync_all()
    return {"sync_result": result, "message": "节点同步完成"}


@router.get("/nodes/stats")
async def get_node_stats():
    """获取节点统计"""
    registry = get_node_registry()
    registry.ensure_builtin()
    return {"summary": registry.get_summary()}


@router.get("/nodes/{node_type:path}")
async def get_node(node_type: str):
    """获取节点定义"""
    registry = get_node_registry()
    node = registry.get(node_type)
    if not node:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"node": {
        "type": node.type,
        "label": node.label,
        "icon": node.icon,
        "category": node.category,
        "description": node.description,
        "sub_blocks": [s.__dict__ for s in node.sub_blocks],
        "inputs": [i.__dict__ for i in node.inputs],
        "outputs": [o.__dict__ for o in node.outputs],
        "source": node.source,
        "version": node.version,
        "tags": node.tags,
    }}


# ==================== 工作流扩展 API ====================

@router.post("/workflows/{workflow_id}/duplicate")
async def duplicate_workflow(workflow_id: str):
    """复制工作流"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    try:
        # 创建副本
        new_workflow = WorkflowDefinition(
            id=f"{workflow_id}_copy_{int(time.time())}",
            name=f"{existing.name} (副本)",
            description=existing.description,
            version=existing.version,
            nodes=existing.nodes.copy(),
            edges=existing.edges.copy(),
            variables=existing.variables.copy(),
            tags=existing.tags.copy(),
            category=existing.category,
            author=existing.author,
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT,  # 副本总是草稿状态
            template=existing.template,
            public=False,  # 副本默认不公开
            metadata=existing.metadata.copy()
        )
        storage.save_workflow(new_workflow)
        return {"workflow": new_workflow.to_dict(), "message": "工作流复制成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"复制工作流失败: {str(e)}")


@router.get("/workflows/{workflow_id}/definition")
async def get_workflow_definition(workflow_id: str):
    """获取工作流定义"""
    storage = _get_storage()
    workflow = storage.get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    return {
        "nodes": [n.__dict__ for n in workflow.nodes],
        "edges": [e.__dict__ for e in workflow.edges],
        "variables": [v.__dict__ for v in workflow.variables],
    }


@router.put("/workflows/{workflow_id}/definition")
async def update_workflow_definition(workflow_id: str, data: Dict[str, Any] = Body(...)):
    """更新工作流定义（节点/边/变量）"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    try:
        # 更新节点
        if "nodes" in data:
            existing.nodes = [WorkflowNode(**n) for n in data["nodes"]]
        
        # 更新边
        if "edges" in data:
            existing.edges = [WorkflowEdge(**e) for e in data["edges"]]
        
        # 更新变量
        if "variables" in data:
            existing.variables = [WorkflowVariable(**v) for v in data["variables"]]
        
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {"message": "工作流定义更新成功", "workflow": existing.to_dict()}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新工作流定义失败: {str(e)}")


@router.put("/workflows/{workflow_id}/viewport")
async def save_workflow_viewport(workflow_id: str, data: Dict[str, Any] = Body(...)):
    """保存工作流视口状态"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    try:
        # 保存视口状态到 metadata
        existing.metadata["viewport"] = {
            "x": data.get("x", 0),
            "y": data.get("y", 0),
            "zoom": data.get("zoom", 1)
        }
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {"message": "视口状态保存成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保存视口状态失败: {str(e)}")


@router.post("/workflows/{workflow_id}/publish")
async def publish_workflow(workflow_id: str):
    """发布工作流"""
    storage = _get_storage()
    existing = storage.get_workflow(workflow_id)
    if not existing:
        raise HTTPException(status_code=404, detail="工作流不存在")
    
    try:
        # 验证工作流
        validator = get_dag_validator()
        validation_result = validator.validate(existing.nodes, existing.edges)
        
        if not validation_result.is_valid:
            raise HTTPException(
                status_code=400, 
                detail=f"工作流验证失败: {', '.join(validation_result.errors)}"
            )
        
        # 更新状态为已发布
        existing.status = WorkflowStatus.PUBLISHED
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {"message": "工作流发布成功", "workflow": existing.to_dict()}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"发布工作流失败: {str(e)}")


# ==================== 执行控制 API ====================

@router.post("/executions/{execution_id}/cancel")
async def cancel_execution(execution_id: str):
    """取消执行"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    
    try:
        executor = get_workflow_executor()
        success = executor.cancel(execution_id)
        if success:
            # 更新执行状态
            execution.status = WorkflowStatus.CANCELLED
            execution.finished_at = time.time()
            execution.duration = execution.finished_at - execution.started_at
            storage.save_execution(execution)
            return {"message": "执行已取消"}
        else:
            raise HTTPException(status_code=400, detail="取消执行失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"取消执行失败: {str(e)}")


@router.post("/executions/{execution_id}/resume")
async def resume_execution(execution_id: str):
    """恢复执行（人工审批后）"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    
    if execution.status != WorkflowStatus.PAUSED:
        raise HTTPException(status_code=400, detail="只能恢复暂停的执行")
    
    try:
        executor = get_workflow_executor()
        success = executor.resume(execution_id)
        if success:
            # 更新执行状态
            execution.status = WorkflowStatus.RUNNING
            storage.save_execution(execution)
            return {"message": "执行已恢复"}
        else:
            raise HTTPException(status_code=400, detail="恢复执行失败")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"恢复执行失败: {str(e)}")


# ==================== 团队 Agent API ====================

@router.get("/agents")
async def list_agents(
    flow_id: Optional[str] = Query(None, description="按工作流过滤"),
    include_archived: bool = Query(False, description="是否包含已归档"),
):
    """列出团队 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager
        manager = get_agent_manager()
        agents = manager.list_agents(flow_id=flow_id, include_archived=include_archived)
        return {"agents": [a.__dict__ for a in agents], "total": len(agents)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取 Agent 列表失败: {str(e)}")


@router.post("/agents")
async def create_agent(data: Dict[str, Any] = Body(...)):
    """创建临时团队 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager
        manager = get_agent_manager()
        
        name = data.get("name")
        role = data.get("role")
        if not name or not role:
            raise HTTPException(status_code=400, detail="名称和角色是必填字段")
        
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"DEBUG: name={name}, role={role}, manager={manager}")
        
        agent = manager.create_agent(
            name=name,
            role=role,
            config=data.get("config", {}),
            flow_id=data.get("flow_id")
        )
        from starlette.responses import JSONResponse
        # 构建响应数据
        agent_data = {
            "id": str(agent.agent_id) if hasattr(agent, 'agent_id') else None,
            "name": str(agent.name) if hasattr(agent, 'name') else name,
            "role": str(agent.role) if hasattr(agent, 'role') else role,
            "config": dict(agent.config) if hasattr(agent, 'config') else data.get("config", {}),
            "flow_id": str(agent.flow_id) if hasattr(agent, 'flow_id') else data.get("flow_id"),
            "status": str(agent.status) if hasattr(agent, 'status') else "active",
            "created_at": float(agent.created_at) if hasattr(agent, 'created_at') else None
        }
        return JSONResponse(content={"agent": agent_data, "message": "Agent 创建成功"}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建 Agent 失败: {str(e)}")


@router.post("/agents/{agent_id}/archive")
async def archive_agent(agent_id: str):
    """归档 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager
        manager = get_agent_manager()
        success = manager.archive_agent(agent_id)
        if success:
            return {"message": "Agent 已归档"}
        else:
            raise HTTPException(status_code=404, detail="Agent 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"归档 Agent 失败: {str(e)}")


@router.post("/agents/{agent_id}/restore")
async def restore_agent(agent_id: str):
    """恢复 Agent"""
    try:
        from neurova.collaboration.neurflow.agent_manager import get_agent_manager
        manager = get_agent_manager()
        success = manager.restore_agent(agent_id)
        if success:
            return {"message": "Agent 已恢复"}
        else:
            raise HTTPException(status_code=404, detail="Agent 不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"恢复 Agent 失败: {str(e)}")


# ==================== 模板 API ====================

@router.get("/templates")
async def list_templates(
    category: Optional[str] = Query(None, description="按分类过滤"),
):
    """列出工作流模板"""
    storage = _get_storage()
    try:
        templates = storage.list_templates(category=category)
        return {"templates": [t.to_dict() for t in templates], "total": len(templates)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取模板列表失败: {str(e)}")


@router.post("/templates")
async def create_template(data: Dict[str, Any] = Body(...)):
    """创建工作流模板"""
    storage = _get_storage()
    try:
        # 基于现有工作流创建模板
        workflow_id = data.get("workflow_id")
        if not workflow_id:
            raise HTTPException(status_code=400, detail="workflow_id 是必填字段")
        
        existing = storage.get_workflow(workflow_id)
        if not existing:
            raise HTTPException(status_code=404, detail="工作流不存在")
        
        # 创建模板
        template = WorkflowDefinition(
            id=f"tmpl_{int(time.time())}",
            name=data.get("name", existing.name),
            description=data.get("description", existing.description),
            version=existing.version,
            nodes=existing.nodes.copy(),
            edges=existing.edges.copy(),
            variables=existing.variables.copy(),
            tags=data.get("tags", existing.tags),
            category=data.get("category", existing.category),
            author=data.get("author", existing.author),
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.PUBLISHED,
            template=True,  # 标记为模板
            public=data.get("public", False),
            metadata=existing.metadata.copy()
        )
        storage.save_workflow(template)
        from starlette.responses import JSONResponse
        return JSONResponse(content={"template": template.to_dict(), "message": "模板创建成功"}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建模板失败: {str(e)}")


@router.post("/templates/{template_id}/instantiate")
async def instantiate_template(template_id: str, data: Dict[str, Any] = Body(...)):
    """从模板创建工作流"""
    storage = _get_storage()
    try:
        # 获取模板
        template = storage.get_workflow(template_id)
        if not template or not template.template:
            raise HTTPException(status_code=404, detail="模板不存在")
        
        # 创建新工作流
        new_workflow = WorkflowDefinition(
            id=f"wf_{int(time.time())}",
            name=data.get("name", f"{template.name} - 实例"),
            description=template.description,
            version=template.version,
            nodes=template.nodes.copy(),
            edges=template.edges.copy(),
            variables=template.variables.copy(),
            tags=template.tags.copy(),
            category=template.category,
            author=data.get("author", "user"),
            created_at=time.time(),
            updated_at=time.time(),
            status=WorkflowStatus.DRAFT,
            template=False,
            public=False,
            metadata=template.metadata.copy()
        )
        
        # 应用变量覆盖
        if "variables" in data:
            for var in new_workflow.variables:
                if var.name in data["variables"]:
                    var.default_value = data["variables"][var.name]
        
        storage.save_workflow(new_workflow)
        from starlette.responses import JSONResponse
        return JSONResponse(content={"workflow": new_workflow.to_dict(), "message": "从模板创建工作流成功"}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"从模板创建工作流失败: {str(e)}")


# ==================== 统计 ====================

@router.get("/stats")
async def get_stats():
    """获取 Neurflow 统计信息"""
    storage = _get_storage()
    registry = get_node_registry()
    registry.ensure_builtin()
    return {
        "storage": storage.get_statistics(),
        "nodes": registry.get_summary()
    }