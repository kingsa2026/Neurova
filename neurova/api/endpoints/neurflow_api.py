"""
Neurflow API — 工作流管理端点
提供工作流 CRUD、执行、节点注册、DAG 验证等 RESTful 接口
"""

from neurova.core.logger import get_logger
import asyncio
import json
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.api.endpoints import get_agent_instance
from neurova.collaboration.neurflow.dag import get_dag_validator
from neurova.collaboration.neurflow.event_recorder import (
    attach_event_recorder,
    get_execution_event_recorder,
)
from neurova.collaboration.neurflow.execution_engine import get_workflow_executor
from neurova.collaboration.neurflow.models import (
    TriggerType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
    WorkflowTrigger,
    WorkflowVariable,
)
from neurova.collaboration.neurflow.node_registry import get_node_registry
from neurova.collaboration.neurflow.storage import NeurflowStorage

logger = get_logger(__name__)

router = APIRouter()

# P2-6: fire-and-forget 后台任务必须持强引用并挂 done_callback 回收——
# 否则任务可能被 GC 中途回收、异常无人收割（对照 multi_model_client._pending_tasks）
_background_tasks: set = set()

# P0-1 生产装配：事件录制器挂上引擎事件总线（幂等；转发到全局单例，
# 画布 run / API execute / 调度器触发的执行统一入流）
attach_event_recorder(get_workflow_executor())


def _port_to_dict(p) -> Dict[str, Any]:
    """
    将端口（input/output）序列化为字典。

    兼容两种存储格式：NodePort 对象或 dict。
    """
    if isinstance(p, dict):
        return {"id": p.get("id", ""), "label": p.get("label", "")}
    return {"id": getattr(p, "id", ""), "label": getattr(p, "label", "")}


def _sub_block_to_dict(b) -> Dict[str, Any]:
    """
    将 sub_block 序列化为前端画布可用的完整字典。

    兼容两种存储格式：
    - SubBlockConfig 对象（属性访问）
    - dict（注册表实际存储格式，键名可能有 id/name、title/label、default_value/default 之分）

    返回包含 default_value/options/min/max/placeholder 等完整字段，
    供前端画布节点库渲染 select/slider/textarea 等配置表单。
    """
    if isinstance(b, dict):
        return {
            "id": b.get("id") or b.get("name") or "",
            "title": b.get("title") or b.get("label") or "",
            "type": b.get("type", "input"),
            "required": bool(b.get("required", False)),
            "default_value": b.get("default_value", b.get("default")),
            "options": b.get("options") or [],
            "placeholder": b.get("placeholder", ""),
            "description": b.get("description", ""),
            "min": b.get("min"),
            "max": b.get("max"),
            "language": b.get("language"),
            # model-selector 能力过滤声明（image_generation/video_generation——
            # 图/视生成节点下拉按能力筛+仅已配置联通；用户口径 2026-09-14）
            "provider_capability": b.get("provider_capability"),
            # 条件可见（联动下拉）：{field, operator, value}，前端按当前 config 过滤字段显隐
            "condition": b.get("condition"),
        }
    # SubBlockConfig / 其他对象
    return {
        "id": getattr(b, "id", ""),
        "title": getattr(b, "title", ""),
        "type": getattr(b, "type", "input"),
        "required": bool(getattr(b, "required", False)),
        "default_value": getattr(b, "default_value", None),
        "options": getattr(b, "options", None) or [],
        "placeholder": getattr(b, "placeholder", ""),
        "description": getattr(b, "description", ""),
        "min": getattr(b, "min", None),
        "max": getattr(b, "max", None),
        "language": getattr(b, "language", None),
        "provider_capability": getattr(b, "provider_capability", None),
        "condition": getattr(b, "condition", None),
    }


def _get_storage() -> NeurflowStorage:
    """获取存储实例（延迟初始化）"""
    if not hasattr(_get_storage, "_instance"):
        from neurova.collaboration.neurflow import storage

        _get_storage._instance = storage.NeurflowStorage()
    return _get_storage._instance


# ── B1 归属模型 v2：项目归属 helper（单源 project_access）──


def _requester_project_ids(user_id: str) -> set:
    from neurova.api.project_access import requester_project_ids

    return requester_project_ids(user_id)


def _is_project_member(user_id: str, project_id: str) -> bool:
    from neurova.api.project_access import is_project_member

    return is_project_member(user_id, project_id)


def _check_ownership_fields(workflow: "WorkflowDefinition", current_user: Dict[str, Any]) -> None:
    """创建/更新时的归属列校验（B1）。

    - project_id 非空需项目成员（admin/default 放行）；
    - agent_id 非空需对该 agent 有访问权（防污染他人 agent 资产池）。
    违规 → HTTPException 400。
    """
    user_id = str(current_user.get("user_id") or "")
    is_admin = current_user.get("role") == "admin"
    if workflow.project_id and not is_admin and not _is_project_member(user_id, workflow.project_id):
        raise HTTPException(status_code=400, detail=f"无权将工作流归属到项目: {workflow.project_id}")
    if workflow.agent_id and not is_admin and user_id not in ("", "default"):
        from neurova.api.endpoints.chat import _user_can_access_agent

        if not _user_can_access_agent(user_id, workflow.agent_id, str(current_user.get("role") or "user")):
            raise HTTPException(status_code=400, detail=f"无权归属到 agent: {workflow.agent_id}")


from .neurflow_stores import (  # noqa: F401,E402 — compatibility exports
    _STORE_FIELD_KEYS,
    _get_store_manager,
    list_stores,
    create_store,
    get_store,
    update_store,
    delete_store,
    test_store_connection,
    refresh_store_token,
    _OAUTH_SUPPORTED,
    _OAUTH_STATE_TTL_SECONDS,
    _oauth_callback_uri,
    _oauth_authorize_url,
    _oauth_exchange_token,
    oauth_authorize,
    oauth_callback,
    router as _stores_router,
)

router.include_router(_stores_router)


# ==================== 工作流 CRUD ====================


@router.get("/workflows")
async def list_workflows(
    category: Optional[str] = Query(None, description="按分类过滤"),
    status: Optional[str] = Query(None, description="按状态过滤"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    view: Optional[str] = Query(None, pattern="^(personal|project|agent)$",
                                description="B1 三视图：personal|project|agent"),
    project_id: Optional[str] = Query(None, description="视图细化：指定项目"),
    agent_id: Optional[str] = Query(None, description="视图细化：指定 agent"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出工作流（P0-1 属主隔离：自己的 + public + B1 项目成员行；admin 全量）"""
    storage = _get_storage()
    ws_status = WorkflowStatus(status) if status else None
    requester = str(current_user.get("user_id") or "")
    workflows = storage.list_workflows(
        category=category, status=ws_status, limit=limit, offset=offset,
        requester_id=requester,
        is_admin=current_user.get("role") == "admin",
        view=view, project_id=project_id, agent_id=agent_id,
        project_ids=_requester_project_ids(requester),
    )
    return {"workflows": [w.to_dict() for w in workflows], "total": len(workflows)}


@router.post("/workflows")
async def create_workflow(
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """创建工作流（P0-1：属主=当前登录用户；B1：归属列校验）"""
    storage = _get_storage()
    try:
        # 如果前端没有提供 id，则生成一个新的 UUID
        if "id" not in data or not data["id"]:
            import uuid

            data["id"] = str(uuid.uuid4())

        workflow = WorkflowDefinition.from_dict(data)
        workflow.created_at = time.time()
        workflow.updated_at = time.time()
        _check_ownership_fields(workflow, current_user)
        storage.save_workflow(workflow, user_id=str(current_user.get("user_id") or "") or None)
        return {"workflow": workflow.to_dict(), "message": "工作流创建成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建工作流失败: {str(e)}")


def _owned_workflow_or_404(storage, workflow_id: str, current_user: Dict[str, Any],
                           writable: bool = False):
    """P0-1 属主判定单点：owner/admin 全通过；非 owner 仅 public 或 B1 项目成员可读；
    写操作（writable=True）要求 owner/admin（成员只读）。deny 与不存在同构 → 404。"""
    requester_id = str(current_user.get("user_id") or "")
    is_admin = current_user.get("role") == "admin"
    workflow = storage.get_workflow(
        workflow_id, requester_id=requester_id, is_admin=is_admin,
        project_ids=_requester_project_ids(requester_id),
    )
    if workflow is None:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if writable:
        if requester_id != (workflow.user_id or "default") and not is_admin:
            raise HTTPException(status_code=404, detail="工作流不存在")
    return workflow


@router.get("/workflows/{workflow_id}")
async def get_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取工作流详情"""
    storage = _get_storage()
    workflow = _owned_workflow_or_404(storage, workflow_id, current_user)
    return {"workflow": workflow.to_dict()}


@router.put("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新工作流（P0-1：属主保留既有行；B1：归属列 payload 缺失时以存量为准——
    旧前端全量 PUT 不得抹除 project_id/agent_id/origin）"""
    storage = _get_storage()
    existing = _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)
    try:
        workflow = WorkflowDefinition.from_dict(data)
        workflow.id = workflow_id
        workflow.updated_at = time.time()
        if "project_id" not in data:
            workflow.project_id = existing.project_id
        if "agent_id" not in data:
            workflow.agent_id = existing.agent_id
        if not data.get("origin"):
            workflow.origin = existing.origin or "manual"
        _check_ownership_fields(workflow, current_user)
        storage.save_workflow(workflow)
        return {"workflow": workflow.to_dict(), "message": "工作流更新成功"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新工作流失败: {str(e)}")


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除工作流（B1：先写校验 → subflow 引用守卫 → 删除）"""
    storage = _get_storage()
    # 属主写校验（deny 同构 404，不向无关用户泄露引用关系）
    _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)
    refs = storage.find_subflow_references(workflow_id)
    if refs:
        raise HTTPException(
            status_code=400,
            detail=f"该工作流被以下工作流的 subflow 节点引用，无法删除: {', '.join(refs)}",
        )
    result = storage.delete_workflow(
        workflow_id,
        requester_id=str(current_user.get("user_id") or ""),
        is_admin=current_user.get("role") == "admin",
    )
    if not result:
        raise HTTPException(status_code=404, detail="工作流不存在")
    return {"message": "工作流删除成功"}


@router.get("/workflows/search/{query}")
async def search_workflows(
    query: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """搜索工作流（P0-1 属主过滤 + B1 项目成员行）"""
    storage = _get_storage()
    requester = str(current_user.get("user_id") or "")
    workflows = storage.search_workflows(
        query,
        requester_id=requester,
        is_admin=current_user.get("role") == "admin",
        project_ids=_requester_project_ids(requester),
    )
    return {"workflows": [w.to_dict() for w in workflows], "total": len(workflows)}


# ==================== 工作流验证 ====================


@router.post("/workflows/{workflow_id}/validate")
async def validate_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """验证工作流"""
    storage = _get_storage()
    workflow = _owned_workflow_or_404(storage, workflow_id, current_user)

    validator = get_dag_validator()
    result = validator.validate(workflow.nodes, workflow.edges)
    return {
        "is_valid": result.is_valid,
        "has_cycle": result.has_cycle,
        "has_start": result.has_start,
        "has_end": result.has_end,
        "errors": result.errors,
        "warnings": result.warnings,
    }


# ==================== 工作流执行 ====================


@router.post("/workflows/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    inputs: Dict[str, Any] = Body(default={}),
    user_id: Optional[str] = Body(default=None),
    agent_id: Optional[str] = Body(default=None),
    wait: bool = Body(default=True),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """执行工作流

    用户隔离：执行实例的 user_id 取 JWT 实名（未认证回退 default），
    不再信任请求体——知识库节点引用用户级远程配置（默认私有）时按此校验属主。

    wait=false（P0-1 run/stream 分离）：立即返回 runId/events_url，
    后台执行并落库；默认 wait=true 同步返回终态实例（行为不变）。
    """
    storage = _get_storage()
    workflow = _owned_workflow_or_404(storage, workflow_id, current_user)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    # JWT 实名优先；已认证用户不可冒用他人身份
    user_id = str(current_user.get("user_id") or "") or None

    # 获取外部系统引用（从 Agent 实例）
    memory_manager = None
    context_pool = None
    emotion_module = None
    crystallizer = None

    # 尝试获取 Agent 实例：优先使用指定的 agent_id，否则尝试默认
    agent = None
    if agent_id:
        agent = get_agent_instance(agent_id)
    if agent is None:
        # 尝试获取默认 Agent
        agent = get_agent_instance("default")

    if agent:
        memory_manager = getattr(agent, "memory_manager", None)
        # context_pool: 尝试从 context_orchestrator 获取，或使用 Agent 的 context_pool 属性
        context_pool = getattr(agent, "context_pool", None)
        if context_pool is None and hasattr(agent, "context_orchestrator"):
            # context_orchestrator 可能有 pool 属性
            context_pool = getattr(agent.context_orchestrator, "pool", None)
        # emotion_module: 从 memory_manager 获取
        if memory_manager:
            emotion_module = getattr(memory_manager, "_emotion_module", None)
        crystallizer = getattr(agent, "crystallizer", None)

    # 降级机制：当 Agent 不可用时，创建默认实例
    # memory_manager
    if memory_manager is None:
        try:
            from neurova.cognitive_layers.memory_layer.manager import MemoryManager

            memory_manager = MemoryManager(agent_id=agent_id or "default", user_id=user_id or "default")
            logger.info("Agent 不可用，已创建默认 MemoryManager 用于 $memory 变量解析")
        except Exception as e:
            logger.warning("创建默认 MemoryManager 失败: %s", e)

    # emotion_module: 优先从 memory_manager 提取，否则创建独立实例
    if emotion_module is None:
        if memory_manager and hasattr(memory_manager, "_emotion_module"):
            emotion_module = memory_manager._emotion_module
        if emotion_module is None:
            try:
                from neurova.cognitive_layers.memory_layer.modules.emotion_module import EmotionModule

                emotion_module = EmotionModule(db_path=None)  # 纯内存模式
                logger.info("Agent 不可用，已创建默认 EmotionModule 用于 $emotion 变量解析")
            except Exception as e:
                logger.warning("创建默认 EmotionModule 失败: %s", e)

    # crystallizer: 尝试创建带默认存储引擎的结晶器
    if crystallizer is None:
        try:
            from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import CognitiveStorageEngine
            from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

            engine = CognitiveStorageEngine(agent_id=agent_id or "default")
            crystallizer = PatternCrystallizer(engine=engine)
            logger.info("Agent 不可用，已创建默认 PatternCrystallizer 用于 $crystal 变量解析")
        except Exception as e:
            logger.warning("创建默认 PatternCrystallizer 失败: %s", e)

    # context_pool: 保持原有降级逻辑
    if context_pool is None:
        try:
            from neurova.context_pool import ContextPool

            context_pool = ContextPool(user_id=user_id or "default", agent_id=agent_id or "default")
            logger.info("Agent 不可用，已创建默认 ContextPool 用于 $context 变量解析")
        except Exception as e:
            logger.warning("创建默认 ContextPool 失败: %s", e)

    executor = get_workflow_executor()

    # P0-1 run/stream 分离：wait=false 预创建实例立即返回，后台执行+落库；
    # 客户端凭 events_url 订阅节点级事件流（画布/页面实时点亮节点）。
    if not wait:
        instance = executor.create_instance(
            workflow, inputs=inputs, user_id=user_id, agent_id=agent_id
        )

        async def _run_and_save():
            result = await executor.execute(
                workflow=workflow,
                inputs=inputs,
                user_id=user_id,
                agent_id=agent_id,
                memory_manager=memory_manager,
                context_pool=context_pool,
                emotion_module=emotion_module,
                crystallizer=crystallizer,
                instance=instance,
            )
            try:
                storage.save_execution(result)
            except Exception as exc:  # noqa: BLE001
                logger.warning("后台执行落库失败 %s: %s", result.id, exc)

        task = asyncio.create_task(_run_and_save())
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return {
            "runId": instance.id,
            "status": "pending",
            "workflow_id": workflow.id,
            "events_url": f"/api/v1/neurflow/executions/{instance.id}/events",
        }

    instance = await executor.execute(
        workflow=workflow,
        inputs=inputs,
        user_id=user_id,
        agent_id=agent_id,
        memory_manager=memory_manager,
        context_pool=context_pool,
        emotion_module=emotion_module,
        crystallizer=crystallizer,
    )

    # 保存执行实例
    storage.save_execution(instance)

    return {
        "instance": {
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
        }
    }


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
    executions = storage.list_executions(workflow_id=workflow_id, status=ws_status, limit=limit, offset=offset)
    return {
        "executions": [
            {
                "id": e.id,
                "workflow_id": e.workflow_id,
                "status": e.status.value,
                "started_at": e.started_at,
                "finished_at": e.finished_at,
                "duration": e.duration,
                "error": e.error,
            }
            for e in executions
        ]
    }


@router.get("/executions/{execution_id}")
async def get_execution(execution_id: str):
    """获取执行详情"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行记录不存在")
    return {
        "execution": {
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
        }
    }


@router.get("/executions/{execution_id}/events")
async def stream_execution_events(
    execution_id: str,
    after: int = Query(0, ge=0),
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """执行事件 SSE 流。

    帧格式 data: {seq,type,workflow_id,execution_id,node_id,data,timestamp}；
    回放 seq>after 历史帧 + 实时推送，终态帧（workflow_completed/failed）后收尾；
    keep-alive 注释行防代理超时。用户隔离：仅属主（或未认证 default）可订阅。
    """
    recorder = get_execution_event_recorder()
    executor = get_workflow_executor()
    user_id = str(current_user.get("user_id") or "")

    instance = executor._instances.get(execution_id)
    if instance is None:
        instance = _get_storage().get_execution(execution_id)

    if instance is None and not recorder.is_tracked(execution_id):
        raise HTTPException(status_code=404, detail=f"执行不存在: {execution_id}")

    owner = str(getattr(instance, "user_id", "") or "") if instance is not None else ""
    if owner and user_id and owner != user_id:
        raise HTTPException(status_code=403, detail="无权访问该执行")

    async def event_generator():
        import json as _json

        status_value = ""
        if instance is not None:
            raw_status = getattr(instance, "status", None)
            status_value = getattr(raw_status, "value", str(raw_status or ""))
        is_live = status_value in ("pending", "running", "paused")

        # 竞态兜底：wait=false 返回与客户端连接之间首帧可能未发（引擎刚起跑）
        waited = 0.0
        while not recorder.snapshot(execution_id) and is_live and waited < 5.0:
            await asyncio.sleep(0.05)
            waited += 0.05

        if not recorder.snapshot(execution_id):
            if is_live:
                return  # 仍在执行但无事件可回放（不应发生；由轮询端点兜底）
            # 重启兜底：缓冲为空但已落库 → 合成终态帧收尾（不进 recorder）
            stored = _get_storage().get_execution(execution_id)
            if stored is not None:
                raw = getattr(stored, "status", None)
                stored_status = getattr(raw, "value", str(raw or ""))
                terminal = {
                    "completed": "workflow_completed",
                    "failed": "workflow_failed",
                    "cancelled": "workflow_failed",
                }.get(stored_status)
                if terminal:
                    frame = {
                        "seq": 0,
                        "type": terminal,
                        "workflow_id": stored.workflow_id,
                        "execution_id": execution_id,
                        "node_id": None,
                        "data": {"outputs": stored.outputs or {}, "error": stored.error},
                        "timestamp": stored.finished_at or 0.0,
                    }
                    yield f"data: {_json.dumps(frame, ensure_ascii=False)}\n\n"
            return

        it = recorder.subscribe(execution_id, after=after).__aiter__()
        while True:
            try:
                frame = await asyncio.wait_for(it.__anext__(), timeout=15.0)
            except asyncio.TimeoutError:
                yield ": keep-alive\n\n"
                continue
            except StopAsyncIteration:
                break
            yield f"data: {_json.dumps(frame, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


# ==================== 节点注册表 ====================


@router.get("/nodes")
async def list_nodes(
    category: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    """列出所有已注册节点"""
    registry = get_node_registry()
    # 确保内置节点 + 适配器节点（工具/技能/MCP/ComfyUI/电商/短剧视频）均已注册
    registry.ensure_builtin()
    registry.sync_all()

    if category:
        nodes = registry.list_by_category(category)
    elif source:
        nodes = registry.list_by_source(source)
    else:
        nodes = registry.list_all()

    return {
        "nodes": [
            {
                "type": n.type,
                "label": n.label,
                "icon": n.icon,
                "category": n.category,
                "description": n.description,
                "source": n.source,
                "version": n.version,
                "tags": n.tags,
                # 端口与配置表单（画布动态节点库渲染用）
                "inputs": [_port_to_dict(p) for p in (n.inputs or [])],
                "outputs": [_port_to_dict(p) for p in (n.outputs or [])],
                "sub_blocks": [_sub_block_to_dict(b) for b in (n.sub_blocks or [])],
            }
            for n in nodes
        ],
        "total": len(nodes),
    }


# ── B5 自定义节点类型 CRUD（CustomNodeService 首次暴露 HTTP 面）────────
# 注册顺序硬约束：/nodes/custom 必须先于 /nodes/{node_type:path} 声明。


def _get_custom_node_service():
    from neurova.collaboration.neurflow.custom_nodes import get_custom_node_service

    return get_custom_node_service()


def _custom_node_to_dict(node) -> Dict[str, Any]:
    return {
        "type": node.type,
        "label": node.label,
        "icon": node.icon,
        "category": node.category,
        "description": node.description,
        "source": node.source,
        "version": node.version,
        "tags": node.tags,
        "inputs": [_port_to_dict(p) for p in (node.inputs or [])],
        "outputs": [_port_to_dict(p) for p in (node.outputs or [])],
        "sub_blocks": [_sub_block_to_dict(b) for b in (node.sub_blocks or [])],
        "tier": node.tier,
        "executor_body": node.executor_body,
        "status": node.status,
        "created_by": node.created_by,
    }


def _custom_node_error_http(e) -> HTTPException:
    """CustomNodeError.code → HTTP 语义映射。"""
    from neurova.collaboration.neurflow.custom_nodes import CustomNodeError

    if isinstance(e, CustomNodeError):
        status = {"exists": 409, "not_found": 404}.get(e.code, 400)
        return HTTPException(status_code=status, detail=str(e))
    return HTTPException(status_code=400, detail=f"自定义节点操作失败: {e}")


def _custom_node_writable_or_404(service, node_type: str, current_user: Dict[str, Any]):
    """PUT/DELETE 守卫。

    - 类型在注册表（builtin/tool/skill 等非 custom 来源）但库内无自定义行 → 400
      （明确"不可改非自定义类型"，而非误导性的不存在）；
    - 库内不存在且注册表也没有 → 404；
    - 非 custom 行 → 400；非属主且非 admin → 404（与不存在同构）。
    """
    existing = service.get_node(node_type)
    if existing is None:
        if service.is_registered(node_type):
            raise HTTPException(status_code=400, detail=f"非自定义节点类型，不可修改: {node_type}")
        raise HTTPException(status_code=404, detail=f"节点不存在: {node_type}")
    if existing.source != "custom":
        raise HTTPException(status_code=400, detail=f"非自定义节点类型，不可修改: {node_type}")
    requester_id = str(current_user.get("user_id") or "")
    is_admin = current_user.get("role") == "admin"
    if not is_admin and (existing.created_by or "default") != requester_id:
        raise HTTPException(status_code=404, detail=f"节点不存在: {node_type}")
    return existing


@router.post("/nodes/custom", status_code=201)
async def create_custom_node(
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """注册自定义节点类型（spec：type/label/tier/executor_body/form_schema/inputs/outputs）"""
    service = _get_custom_node_service()
    try:
        node = service.create_node(data, created_by=str(current_user.get("user_id") or ""))
    except Exception as e:  # noqa: BLE001
        raise _custom_node_error_http(e)
    return {"node": _custom_node_to_dict(node)}


@router.get("/nodes/custom")
async def list_custom_nodes(current_user: Dict[str, Any] = Depends(get_current_user)):
    """列出自定义节点类型（含属主 created_by）。"""
    service = _get_custom_node_service()
    nodes = service.list_nodes()
    return {"nodes": [_custom_node_to_dict(n) for n in nodes], "total": len(nodes)}


@router.put("/nodes/custom/{node_type:path}")
async def update_custom_node(
    node_type: str,
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新自定义节点类型（属主/admin；更新自动快照旧版本，版本号 patch +1）"""
    service = _get_custom_node_service()
    _custom_node_writable_or_404(service, node_type, current_user)
    try:
        node = service.update_node(node_type, data, created_by=str(current_user.get("user_id") or ""))
    except Exception as e:  # noqa: BLE001
        raise _custom_node_error_http(e)
    return {"node": _custom_node_to_dict(node)}


@router.delete("/nodes/custom/{node_type:path}")
async def delete_custom_node(
    node_type: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """删除自定义节点类型（仅 custom 且属主/admin；builtin 守卫 400）"""
    service = _get_custom_node_service()
    _custom_node_writable_or_404(service, node_type, current_user)
    deleted = service.delete_node(node_type)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"节点不存在: {node_type}")
    return {"message": "自定义节点已删除", "type": node_type}


@router.get("/nodes/search/{query}")
async def search_nodes(query: str):
    """搜索节点"""
    registry = get_node_registry()
    results = registry.search(query)
    return {
        "nodes": [
            {
                "type": n.type,
                "label": n.label,
                "icon": n.icon,
                "category": n.category,
                "description": n.description,
                "source": n.source,
                "tags": n.tags,
            }
            for n in results
        ],
        "total": len(results),
    }


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
    return {
        "node": {
            "type": node.type,
            "label": node.label,
            "icon": node.icon,
            "category": node.category,
            "description": node.description,
            "sub_blocks": [_sub_block_to_dict(s) for s in node.sub_blocks],
            "inputs": [_port_to_dict(i) for i in node.inputs],
            "outputs": [_port_to_dict(o) for o in node.outputs],
            "source": node.source,
            "version": node.version,
            "tags": node.tags,
        }
    }


# ==================== 工作流扩展 API ====================


@router.post("/workflows/{workflow_id}/duplicate")
async def duplicate_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """复制工作流（P0-1：源须可读；副本属主=当前用户）"""
    storage = _get_storage()
    existing = _owned_workflow_or_404(storage, workflow_id, current_user)

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
            metadata=existing.metadata.copy(),
            # B1：副本来源=template；归属继承（owner 或项目成员才带上）
            origin="template",
            project_id=(
                existing.project_id
                if (
                    existing.user_id == str(current_user.get("user_id") or "")
                    or (existing.project_id and _is_project_member(
                        str(current_user.get("user_id") or ""), existing.project_id))
                )
                else None
            ),
            agent_id=existing.agent_id if existing.user_id == str(current_user.get("user_id") or "") else None,
        )
        storage.save_workflow(
            new_workflow, user_id=str(current_user.get("user_id") or "") or None
        )
        return {"workflow": new_workflow.to_dict(), "message": "工作流复制成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"复制工作流失败: {str(e)}")


@router.get("/workflows/{workflow_id}/definition")
async def get_workflow_definition(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取工作流定义"""
    storage = _get_storage()
    workflow = _owned_workflow_or_404(storage, workflow_id, current_user)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")

    return {
        "nodes": [n.__dict__ for n in workflow.nodes],
        "edges": [e.__dict__ for e in workflow.edges],
        "variables": [v.__dict__ for v in workflow.variables],
    }


@router.put("/workflows/{workflow_id}/definition")
async def update_workflow_definition(
    workflow_id: str,
    data: Dict[str, Any] = Body(...),
    base_version: Optional[int] = Query(None, description="B2 乐观锁基版本（画布编辑器回写携带）"),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """更新工作流定义（节点/边/变量/名称/描述）。

    局部更新语义：未提供的字段不动——variables/status 等编辑面之外的字段
    永不被画布回写抹除（B2 "往返不丢字段"由此端点保证，画布快照不再重建定义）。
    base_version：与当前内容版本号不一致 → 409（detail 含 current_version）。
    """
    storage = _get_storage()
    existing = _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)

    if base_version is not None:
        current = storage.get_workflow_version_number(workflow_id)
        if int(base_version) != current:
            raise HTTPException(
                status_code=409,
                detail={"error": f"定义版本冲突: base_version={base_version} 落后于当前版本 {current}",
                        "current_version": current},
            )

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

        # B2：编辑器改名/描述回写
        if data.get("name"):
            existing.name = str(data["name"])
        if "description" in data:
            existing.description = str(data["description"])
        # B2：视口随定义回写落 metadata.viewport（省去单独 PUT viewport 往返）
        if isinstance(data.get("viewport"), dict):
            existing.metadata["viewport"] = {
                "x": float(data["viewport"].get("x", 0) or 0),
                "y": float(data["viewport"].get("y", 0) or 0),
                "zoom": float(data["viewport"].get("zoom", 1) or 1),
            }

        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {
            "message": "工作流定义更新成功",
            "workflow": existing.to_dict(),
            "version": storage.get_workflow_version_number(workflow_id),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"更新工作流定义失败: {str(e)}")


@router.put("/workflows/{workflow_id}/viewport")
async def save_workflow_viewport(
    workflow_id: str,
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """保存工作流视口状态"""
    storage = _get_storage()
    existing = _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)

    try:
        # 保存视口状态到 metadata
        existing.metadata["viewport"] = {"x": data.get("x", 0), "y": data.get("y", 0), "zoom": data.get("zoom", 1)}
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {"message": "视口状态保存成功"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"保存视口状态失败: {str(e)}")


@router.post("/workflows/{workflow_id}/publish")
async def publish_workflow(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """发布工作流（P2：编译 AgentManifest 并落 agents 记录，chat 页可直接选用）"""
    storage = _get_storage()
    existing = _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)

    try:
        # 验证工作流
        validator = get_dag_validator()
        validation_result = validator.validate(existing.nodes, existing.edges)

        if not validation_result.is_valid:
            raise HTTPException(status_code=400, detail=f"工作流验证失败: {', '.join(validation_result.errors)}")

        # P2 Step 3 — 编译 AgentManifest 并持久化 agent 记录（幂等 upsert）
        from neurova.agent.workflow_agent import compile_workflow_agent, manifest_to_agent_info

        manifest = compile_workflow_agent(existing)
        agent_info = manifest_to_agent_info(manifest)
        storage.save_agent(agent_info)

        # 更新状态为已发布
        existing.status = WorkflowStatus.PUBLISHED
        existing.updated_at = time.time()
        storage.save_workflow(existing)
        return {
            "code": 0,
            "message": "工作流发布成功",
            "data": {
                "workflow": existing.to_dict(),
                "agent": {
                    "agent_id": agent_info.agent_id,
                    "name": agent_info.name,
                    "role": agent_info.role,
                    "capabilities": agent_info.capabilities,
                    "metadata": agent_info.metadata,
                },
            },
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"发布失败: {str(e)}")
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
async def resume_execution(
    execution_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
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

        logger = get_logger(__name__)
        logger.error("DEBUG: name=%s, role=%s, manager=%s", name, role, manager)

        agent = manager.create_agent(name=name, role=role, config=data.get("config", {}), flow_id=data.get("flow_id"))
        from starlette.responses import JSONResponse

        # 构建响应数据
        agent_data = {
            "id": str(agent.agent_id) if hasattr(agent, "agent_id") else None,
            "name": str(agent.name) if hasattr(agent, "name") else name,
            "role": str(agent.role) if hasattr(agent, "role") else role,
            "config": dict(agent.config) if hasattr(agent, "config") else data.get("config", {}),
            "flow_id": str(agent.flow_id) if hasattr(agent, "flow_id") else data.get("flow_id"),
            "status": str(agent.status) if hasattr(agent, "status") else "active",
            "created_at": float(agent.created_at) if hasattr(agent, "created_at") else None,
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
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """列出工作流模板（P0-1：登录用户可读）"""
    storage = _get_storage()
    try:
        templates = storage.list_templates(category=category)
        return {"templates": [t.to_dict() for t in templates], "total": len(templates)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"获取模板列表失败: {str(e)}")


@router.post("/templates")
async def create_template(
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """创建工作流模板（P0-1：源工作流须可写；模板属主=创建者）"""
    storage = _get_storage()
    try:
        # 基于现有工作流创建模板
        workflow_id = data.get("workflow_id")
        if not workflow_id:
            raise HTTPException(status_code=400, detail="workflow_id 是必填字段")

        existing = _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)
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
            metadata=existing.metadata.copy(),
        )
        storage.save_workflow(
            template, user_id=str(current_user.get("user_id") or "") or None
        )
        from starlette.responses import JSONResponse

        return JSONResponse(content={"template": template.to_dict(), "message": "模板创建成功"}, status_code=201)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"创建模板失败: {str(e)}")


@router.post("/templates/{template_id}/instantiate")
async def instantiate_template(
    template_id: str,
    data: Dict[str, Any] = Body(...),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """从模板创建工作流（P0-1：实例属主=实例化人）"""
    storage = _get_storage()
    try:
        # 获取模板（登录用户可读——模板对全员开放的计划语义 §1.3）
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
            metadata=template.metadata.copy(),
            # B1：模板实例来源标记；归属可选带上下文（project 需成员校验）
            origin="template",
            project_id=data.get("project_id"),
            agent_id=data.get("agent_id"),
        )
        _check_ownership_fields(new_workflow, current_user)

        # 应用变量覆盖
        if "variables" in data:
            for var in new_workflow.variables:
                if var.name in data["variables"]:
                    var.default_value = data["variables"][var.name]

        storage.save_workflow(
            new_workflow, user_id=str(current_user.get("user_id") or "") or None
        )
        from starlette.responses import JSONResponse

        return JSONResponse(
            content={"workflow": new_workflow.to_dict(), "message": "从模板创建工作流成功"}, status_code=201
        )
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
    return {"storage": storage.get_statistics(), "nodes": registry.get_summary()}


# ==================== ComfyUI 集成 ====================


class ComfyUIExecuteRequest(BaseModel):
    """ComfyUI 单节点执行请求"""

    class_type: str
    config: Dict[str, Any] = {}
    inputs: Dict[str, Any] = {}


# 注：旧的 POST /comfyui/import「定义优先」导入端点已下线。
# 工作流 = 无限画布工作流，ComfyUI 导入统一走
# POST /v1/collaboration/comfyui/import-canvas 落为可编辑画布快照，
# WorkflowDefinition 只是画布执行时的内部编译产物。


@router.get("/comfyui/status")
async def get_comfyui_status():
    """检查 ComfyUI 服务可用性"""
    from neurova.collaboration.neurflow.comfyui_client import get_comfyui_client

    client = get_comfyui_client()
    return {"available": client.is_available(), "host": client.host}


@router.post("/comfyui/execute")
async def execute_comfyui_node_endpoint(request: ComfyUIExecuteRequest):
    """直接执行单个 ComfyUI 节点（提交 prompt 到 ComfyUI /prompt）"""
    from neurova.collaboration.neurflow.comfyui_nodes import _execute_comfyui_node

    result = await _execute_comfyui_node(f"comfyui:{request.class_type}", request.config, request.inputs)
    return result


# ==================== P0 Step 4 — 调试 API ====================


from neurova.collaboration.neurflow.execution_engine import DebugSession  # noqa: E402
from neurova.collaboration.neurflow.execution_engine import get_node_mocks as _get_node_mocks  # noqa: E402


# 全局注册表：execution_id → DebugSession（in-memory，仅调试用）。
# 资源修复 #2（台账 2026-09-11）：调试执行无终态回收钩子（后台执行结束不回写本表，
# collaboration_api 还以裸赋值写入），故在注册表本体做 LRU 封顶——上限
# _DEBUG_SESSIONS_MAX，超限逐出最久未访问条目；裸赋值同样经 __setitem__ 受约束。
_DEBUG_SESSIONS_MAX = 100


class _BoundedDebugSessions(OrderedDict):
    """execution_id → DebugSession 有界 LRU 注册表（保持 isinstance dict 契约）。"""

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        self.move_to_end(key)
        while len(self) > _DEBUG_SESSIONS_MAX:
            self.popitem(last=False)

    def get(self, key, default=None):
        if key in self:
            self.move_to_end(key)
        return super().get(key, default)

    def setdefault(self, key, default=None):
        # 覆写 dict.setdefault：C 层实现不会路由到上方 __setitem__
        if key in self:
            self.move_to_end(key)
            return self[key]
        self[key] = default
        return default


_DEBUG_SESSIONS: Dict[str, DebugSession] = _BoundedDebugSessions()

# 全局注册表：node_id → mock_output（in-memory，调试用）


class BreakpointRequest(BaseModel):
    """设置断点请求体"""

    breakpoints: list[str] = []
    replace: bool = True


class ResumeRequest(BaseModel):
    """恢复执行请求体"""

    step: Optional[str] = None  # None | "in" | "over" | "out"


class MockNodeRequest(BaseModel):
    """设置节点 mock 输出请求体"""

    mock_output: Optional[Any] = None
    clear: bool = False


@router.post("/executions/{execution_id}/breakpoint")
async def set_breakpoints(
    execution_id: str,
    body: BreakpointRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """为指定 execution 设置/追加断点集合。"""
    session = _DEBUG_SESSIONS.setdefault(execution_id, DebugSession())
    if body.replace:
        session.breakpoints = set(body.breakpoints)
    else:
        session.breakpoints.update(body.breakpoints)
    return {
        "execution_id": execution_id,
        "breakpoints": sorted(session.breakpoints),
        "count": len(session.breakpoints),
    }


@router.post("/executions/{execution_id}/debug/resume")
async def resume_debug_execution(
    execution_id: str,
    body: ResumeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """恢复调试暂停中的执行；可选 step 模式（in/over/out）。

    路径区分于 /executions/{id}/resume（人工审批恢复）——两者同名会导致
    FastAPI 路由遮蔽（先注册者独占，调试恢复成死代码）。
    """
    session = _DEBUG_SESSIONS.get(execution_id)
    if not session:
        raise HTTPException(status_code=404, detail="未找到该 execution 的调试会话")
    if body.step is not None and body.step not in ("in", "over", "out"):
        raise HTTPException(status_code=400, detail="step 必须为 in/over/out 之一")
    session.step_mode = body.step
    session.resume()
    return {"execution_id": execution_id, "resumed": True, "step_mode": session.step_mode}


@router.get("/executions/{execution_id}/variables")
async def get_execution_variables(
    execution_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """获取当前执行实例的所有变量（含 inputs/variables/node_results）。"""
    storage = _get_storage()
    execution = storage.get_execution(execution_id)
    if not execution:
        raise HTTPException(status_code=404, detail="执行实例不存在")
    return {
        "execution_id": execution_id,
        "inputs": execution.inputs,
        "variables": execution.variables,
        "node_results": {
            nid: {
                "status": nr.status,
                "output": nr.output,
            }
            for nid, nr in execution.node_results.items()
        },
    }


@router.put("/nodes/{node_id}/mock")
async def set_node_mock(
    node_id: str,
    body: MockNodeRequest,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """为节点设置 mock 输出；clear=true 时清空（恢复真实执行）。"""
    mocks = _get_node_mocks()
    if body.clear:
        mocks.pop(node_id, None)
        return {"node_id": node_id, "mocked": False}
    mocks[node_id] = body.mock_output
    return {"node_id": node_id, "mocked": True}


# ==================== P1-1 单节点 step-run（画布调试 UX 底座） ====================


class StepRunRequest(BaseModel):
    node_id: str
    inputs: Optional[Dict[str, Any]] = None
    upstream_outputs: Optional[Dict[str, Any]] = None


@router.post("/workflows/{workflow_id}/step-run")
async def step_run_node(
    workflow_id: str,
    body: StepRunRequest,
    current_user: Dict[str, Any] = Depends(get_current_user_or_default),
):
    """单节点试跑：只执行指定节点（mock 优先），上游输出经
    upstream_outputs 注入（画布右键面板/变量检查的数据源）。"""
    storage = _get_storage()
    workflow = _owned_workflow_or_404(storage, workflow_id, current_user)
    if not workflow:
        raise HTTPException(status_code=404, detail="工作流不存在")
    if not any(n.id == body.node_id for n in workflow.nodes):
        raise HTTPException(status_code=404, detail=f"节点不存在: {body.node_id}")

    executor = get_workflow_executor()
    try:
        result = await executor.step_run(
            workflow,
            body.node_id,
            upstream_outputs=body.upstream_outputs or {},
            inputs=body.inputs or {},
            user_id=str(current_user.get("user_id") or "") or None,
        )
    except Exception as e:  # noqa: BLE001 — 引擎异常转失败信封
        result = {"status": "failed", "error": str(e), "duration_ms": 0.0}
    return {"code": 0, "message": "ok", "data": result}


from .neurflow_triggers import (  # noqa: F401,E402 — compatibility exports
    _WEBHOOK_RATE_LIMITERS,
    _webhook_ingress_deps,
    _WEBHOOK_MAX_BODY_BYTES,
    receive_webhook_trigger,
    TriggerCreateRequest,
    list_workflow_triggers,
    create_workflow_trigger,
    delete_workflow_trigger,
    fire_trigger,
    list_trigger_deliveries,
    handle_webhook_ingress_simple,
    _get_retry_service,
    list_failed_deliveries,
    retry_delivery,
    retry_due_deliveries,
    webhook_ingress,
    TriggerRateLimiter,
    router as _triggers_router,
    deliveries_router as _deliveries_router,
)

webhook_ingress.set_deps_provider(_webhook_ingress_deps)


def get_workflow_agent_deps() -> Dict[str, Any]:
    """遗留③a：workflow_agent 桥接 deps 工厂（tool_executor 首次调用时装配）。

    load_agent / load_published_workflow 走 Neurflow storage；
    run_workflow 走 WorkflowExecutor（user_id 由 tool_executor 从请求级
    身份透传——工作流内配置引用按属主隔离校验）。
    """
    from neurova.collaboration.neurflow.models import WorkflowStatus

    def load_agent(aid: str):
        return _get_storage().get_agent(aid)

    def load_published_workflow(ref: str):
        storage = _get_storage()
        wf = storage.get_workflow(ref)
        if wf is not None and wf.status == WorkflowStatus.PUBLISHED:
            return wf
        return None

    async def run_workflow(workflow, inputs, user_id=None):
        # P0-1：user_id 由 tool_executor 请求级透传；缺省（系统派发）回退
        # workflow 属主，保证知识库节点等用户级凭据校验不落空
        effective = user_id or getattr(workflow, "user_id", None) or None
        return await get_workflow_executor().execute(
            workflow=workflow, inputs=inputs, user_id=effective
        )

    return {
        "load_agent": load_agent,
        "load_published_workflow": load_published_workflow,
        "run_workflow": run_workflow,
    }


# 遗留③a：模块导入时一次性装配（tool_executor 的 run_workflow_agent 分支消费）
from neurova.agent.workflow_agent import set_workflow_agent_deps as _set_wa_deps  # noqa: E402

_set_wa_deps(get_workflow_agent_deps)


router.include_router(_triggers_router)


# ==================== P2 遗留② — 版本 REST API ====================


@router.get("/workflows/{workflow_id}/versions")
async def list_workflow_versions_api(
    workflow_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """工作流版本历史（倒序；内容指纹快照）。"""
    storage = _get_storage()
    _owned_workflow_or_404(storage, workflow_id, current_user)
    return {"code": 0, "data": storage.list_workflow_versions(workflow_id)}


@router.post("/workflows/{workflow_id}/versions/{version}/rollback")
async def rollback_workflow_api(
    workflow_id: str,
    version: int,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """回滚到指定版本（状态保持当前值；回滚本身产生新版本）。"""
    storage = _get_storage()
    _owned_workflow_or_404(storage, workflow_id, current_user, writable=True)
    if not storage.rollback_workflow(workflow_id, version):
        raise HTTPException(status_code=404, detail="版本不存在")
    return {
        "code": 0,
        "message": "rollback ok",
        "data": {"workflow": storage.get_workflow(workflow_id).to_dict()},
    }


# ==================== Checkpoint API ====================


@router.get("/executions/{execution_id}/checkpoint")
async def get_execution_checkpoint(
    execution_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Probe：执行检查点摘要（completed/failed/pending/变量快照/错误）。"""
    from neurova.collaboration.neurflow.storage import NeurflowStorage as _Ck

    storage = _get_storage()
    instance = storage.get_checkpoint(execution_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="检查点不存在")
    # pending 需要完整节点集：优先从 DB 工作流取；画布内存型退化为已知集
    workflow = storage.get_workflow(instance.workflow_id)
    node_ids = [n.id for n in workflow.nodes] if workflow else list((instance.node_results or {}).keys())
    return {"code": 0, "data": _checkpoint_summary(instance, node_ids)}


@router.post("/executions/{execution_id}/retry")
async def retry_from_checkpoint(
    execution_id: str,
    body: Dict[str, Any] = Body(default={}),
    current_user: Dict[str, Any] = Depends(get_current_user),
):
    """Resume：从检查点续跑（跳过已完成节点，保留变量）。

    要求工作流定义在 DB（发布型）；画布内存型工作流（DRAFT→内存
    PUBLISHED 不落库）无法恢复定义——返回 400 明确说明。
    """
    from neurova.collaboration.neurflow.checkpoint import execution_checkpoint_summary

    storage = _get_storage()
    instance = storage.get_checkpoint(execution_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="检查点不存在")

    workflow = storage.get_workflow(instance.workflow_id)
    if workflow is None:
        raise HTTPException(
            status_code=400,
            detail="画布型工作流暂不支持恢复（定义未落库），请重新执行",
        )

    instance.status = WorkflowStatus.RUNNING
    instance.error = None
    instance.finished_at = None

    await get_workflow_executor().execute(
        workflow=workflow,
        inputs=instance.inputs,
        instance=instance,
        resume=True,
    )
    return {
        "code": 0,
        "message": "retry ok",
        "data": {
            "execution_id": instance.id,
            "status": instance.status.value,
            "summary": execution_checkpoint_summary(instance, [n.id for n in workflow.nodes]),
        },
    }


def _checkpoint_summary(instance, node_ids=None) -> dict:
    """端点内轻量摘要（不依赖 checkpoint 模块 import 循环）。"""
    from neurova.collaboration.neurflow.checkpoint import execution_checkpoint_summary

    # node_ids 缺失时仅按已知结果分类（pending 需节点集才能算，此处以检查点记录为准）
    import typing as _t
    node_ids = node_ids or list((instance.node_results or {}).keys())
    return execution_checkpoint_summary(instance, node_ids)


@router.get("/otel/status")
def otel_status():
    """P0-5 OTel 桥状态（可选依赖探测 + 投影账目）。"""
    try:
        from neurova.core.otel_bridge import bridge_stats

        return {"code": 0, "message": "ok", "data": {**bridge_stats()}}
    except Exception as e:  # noqa: BLE001 — 状态端点不 500
        return {"code": 0, "message": "ok", "data": {"installed": False, "enabled": False, "error": str(e)}}


router.include_router(_deliveries_router)
