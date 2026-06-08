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