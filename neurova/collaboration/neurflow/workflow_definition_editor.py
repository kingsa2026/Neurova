"""工作流定义编辑面（N4）：读取 / 修改 / 回滚 / 发布 / DRAFT 暂存 / 草稿执行。

安全版本口径（设计 §5.4）：
- `workflows.safe_version` 指向一条可回滚的 `workflow_versions` 快照；
- 修改已发布定义前必须先有有效安全版本，缺失时先为当前内容补基线；
- 校验失败不落盘，审计记录拒绝原因；执行成功后才提升安全版本；
- 回滚默认回到安全版本，回滚自身产生新版本（undo-friendly）。
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Optional

from neurova.core.data_root import dataLanding
from neurova.core.logger import get_logger

from .dag import get_dag_validator
from .models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)
from .node_registry import get_node_registry

logger = get_logger(__name__)

_audit_lock = threading.RLock()

_EDITABLE_STATUSES = ("draft", "published")


class WorkflowDefinitionError(ValueError):
    """定义编辑业务错误，携带机器可读 code 供 Agent 分支处理。"""

    def __init__(self, message: str, code: str = "invalid_definition"):
        super().__init__(message)
        self.code = code


def getWorkflowDefinitionStorage():
    """缺省 storage（与 API 同款单例；测试可 patch 本函数注入临时库）。"""
    from neurova.api.endpoints.neurflow_api import _get_storage

    return _get_storage()


def _workflowStatus(workflow: WorkflowDefinition) -> str:
    return str(getattr(getattr(workflow, "status", None), "value", workflow.status))


def _nodeDicts(nodes: List[WorkflowNode]) -> List[Dict[str, Any]]:
    return [node.__dict__ for node in nodes]


def _edgeDicts(edges: List[WorkflowEdge]) -> List[Dict[str, Any]]:
    return [edge.__dict__ for edge in edges]


def _coerceNodes(nodes: List[Any]) -> List[WorkflowNode]:
    return [item if isinstance(item, WorkflowNode) else WorkflowNode(**item) for item in nodes or []]


def _coerceEdges(edges: List[Any]) -> List[WorkflowEdge]:
    return [item if isinstance(item, WorkflowEdge) else WorkflowEdge(**item) for item in edges or []]


def _portId(port: Any) -> str:
    """兼容两种端口形态：NodePort 对象与注册表里的 dict。"""
    if isinstance(port, dict):
        return str(port.get("id") or "")
    return str(getattr(port, "id", "") or "")


def validateWorkflowDefinition(
    nodes: List[Any], edges: List[Any]
) -> Dict[str, Any]:
    """DAG + 节点类型 + 端口声明校验；返回 {is_valid, errors, warnings}。"""
    errors: List[str] = []
    warnings: List[str] = []
    try:
        workflowNodes = _coerceNodes(nodes)
        workflowEdges = _coerceEdges(edges)
    except (TypeError, ValueError) as exc:
        return {
            "is_valid": False,
            "errors": [f"节点/边字段不合法: {exc}"],
            "warnings": [],
        }

    nodeIds = [node.id for node in workflowNodes]
    duplicates = sorted({nodeId for nodeId in nodeIds if nodeIds.count(nodeId) > 1})
    if duplicates:
        errors.append(f"节点 id 重复: {', '.join(duplicates)}")

    result = get_dag_validator().validate(workflowNodes, workflowEdges)
    errors.extend(result.errors)
    warnings.extend(result.warnings)

    registry = get_node_registry()
    knownTypes = set()
    try:
        from neurova.collaboration.canvas_bridge import known_node_types

        knownTypes = known_node_types()
    except Exception as exc:  # noqa: BLE001 - 同步失败时退回注册表现值
        logger.warning("节点类型同步失败（校验按注册表现值）: %s", exc)
        try:
            knownTypes = {item.type for item in registry.list_all()}
        except Exception:  # noqa: BLE001
            knownTypes = set()

    definitions: Dict[str, Any] = {}
    nodeTypes = {node.id: node.type for node in workflowNodes}
    customService = None
    for node in workflowNodes:
        if node.type in definitions:
            continue
        if node.type.startswith("custom:"):
            if customService is None:
                from .custom_nodes import get_custom_node_service

                customService = get_custom_node_service()
            definition = customService.get_node(node.type)
            if definition is None:
                errors.append(f"未知节点类型: {node.type}")
            elif definition.status != "active":
                errors.append(
                    f"自定义节点 '{node.type}' 当前为 {definition.status}，"
                    "未激活的节点不可被工作流引用"
                )
            definitions[node.type] = definition
        else:
            if node.type not in knownTypes:
                errors.append(f"未知节点类型: {node.type}")
            definitions[node.type] = registry.get(node.type)

    for edge in workflowEdges:
        sourceDefinition = definitions.get(nodeTypes.get(edge.source, ""))
        targetDefinition = definitions.get(nodeTypes.get(edge.target, ""))
        if edge.source_handle and sourceDefinition is not None and sourceDefinition.outputs:
            outputIds = {_portId(port) for port in sourceDefinition.outputs}
            if edge.source_handle not in outputIds:
                errors.append(
                    f"边 '{edge.id}' 的源端口 '{edge.source_handle}' 不在节点 "
                    f"'{edge.source}'({sourceDefinition.type}) 的端口声明中: "
                    f"{', '.join(sorted(outputIds))}"
                )
        if edge.target_handle and targetDefinition is not None and targetDefinition.inputs:
            inputIds = {_portId(port) for port in targetDefinition.inputs}
            if edge.target_handle not in inputIds:
                errors.append(
                    f"边 '{edge.id}' 的目标端口 '{edge.target_handle}' 不在节点 "
                    f"'{edge.target}'({targetDefinition.type}) 的输入声明中: "
                    f"{', '.join(sorted(inputIds))}"
                )

    return {
        "is_valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def recordWorkflowAudit(entry: Dict[str, Any]) -> None:
    """逐条写定义变更审计（JSONL，敏感值不落）。"""
    path = os.environ.get("NEUROVA_WORKFLOW_DEFINITION_AUDIT") or str(
        dataLanding("workflow_definition_audit.jsonl")
    )
    payload = {"at": time.time(), **(entry or {})}
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with _audit_lock:
            with open(path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")
    except OSError as exc:  # noqa: BLE001 - 审计失败不阻断主流程，但要留痕
        logger.warning("工作流定义审计写入失败: %s", exc)


def _loadWorkflow(
    storage, workflowId: str, actorId: str = "", isAdmin: bool = False
) -> WorkflowDefinition:
    workflow = storage.get_workflow(
        workflowId,
        requester_id=actorId or None,
        is_admin=isAdmin,
    )
    if workflow is None:
        raise WorkflowDefinitionError(
            f"工作流不存在或无权访问: {workflowId}", code="not_found"
        )
    return workflow


def _safePayload(storage, workflowId: str) -> Optional[Dict[str, Any]]:
    safe = storage.getSafeVersion(workflowId)
    if safe is None:
        return None
    return {
        "version": safe["version"],
        "reason": safe["reason"],
        "at": safe["at"],
        "valid": safe["valid"],
    }


def getWorkflowDefinition(
    workflowId: str,
    actorId: str = "",
    isAdmin: bool = False,
    storage=None,
) -> Dict[str, Any]:
    """读取定义；已发布且无有效安全版本时为当前版本建立基线。"""
    storage = storage or getWorkflowDefinitionStorage()
    try:
        workflow = _loadWorkflow(storage, workflowId, actorId, isAdmin)
    except WorkflowDefinitionError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}

    version = storage.get_workflow_version_number(workflowId)
    status = _workflowStatus(workflow)
    safe = storage.getSafeVersion(workflowId)
    safeCreated = False
    if status == "published" and (safe is None or not safe["valid"]):
        try:
            safe = storage.ensureSafeVersion(
                workflowId,
                reason="baseline_on_get",
                evidence={"actor": actorId, "source": "agent_tool"},
            )
            safeCreated = bool(safe.get("created"))
            if safeCreated:
                recordWorkflowAudit(
                    {
                        "action": "safe_baseline",
                        "workflow_id": workflowId,
                        "actor": actorId,
                        "version": safe["version"],
                        "reason": "baseline_on_get",
                    }
                )
        except Exception as exc:  # noqa: BLE001 - 建基线失败要诚实拒绝
            return {
                "success": False,
                "code": "safe_version_unavailable",
                "error": f"已发布工作流无法建立安全版本基线，拒绝直接修改: {exc}",
                "workflow_id": workflowId,
                "status": status,
                "version": version,
            }

    return {
        "success": True,
        "workflow_id": workflow.id,
        "name": workflow.name,
        "status": status,
        "version": version,
        "safe_version": safe["version"] if safe else None,
        "safe_reason": safe["reason"] if safe else "",
        "safe_at": safe["at"] if safe else 0,
        "safe_created": safeCreated,
        "definition": workflow.to_dict(),
    }


def updateWorkflowDefinition(
    workflowId: str,
    nodes: Optional[List[Any]] = None,
    edges: Optional[List[Any]] = None,
    baseVersion: Optional[int] = None,
    actorId: str = "",
    batchId: str = "",
    note: str = "",
    storage=None,
) -> Dict[str, Any]:
    """直接修改已发布/草稿定义；已发布先确保安全版本，校验失败不落盘。"""
    storage = storage or getWorkflowDefinitionStorage()
    try:
        workflow = _loadWorkflow(storage, workflowId, actorId)
    except WorkflowDefinitionError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}

    status = _workflowStatus(workflow)
    if status not in _EDITABLE_STATUSES:
        return {
            "success": False,
            "code": "invalid_status",
            "error": f"当前状态 {status} 不允许修改定义（仅 draft/published）",
        }
    if baseVersion is None:
        return {
            "success": False,
            "code": "base_version_required",
            "error": "缺少 base_version：先用 workflow_definition_get 读取当前版本",
            "version": storage.get_workflow_version_number(workflowId),
        }
    currentVersion = storage.get_workflow_version_number(workflowId)
    if int(baseVersion) != currentVersion:
        return {
            "success": False,
            "code": "version_conflict",
            "error": f"定义版本冲突: base_version={baseVersion} 落后于当前版本 {currentVersion}",
            "current_version": currentVersion,
        }
    if nodes is None and edges is None:
        return {"success": False, "code": "invalid_params", "error": "nodes/edges 至少提供一个"}

    try:
        newNodes = list(workflow.nodes) if nodes is None else _coerceNodes(nodes)
        newEdges = list(workflow.edges) if edges is None else _coerceEdges(edges)
    except (TypeError, ValueError) as exc:
        return {"success": False, "code": "invalid_params", "error": f"节点/边字段不合法: {exc}"}

    validation = validateWorkflowDefinition(_nodeDicts(newNodes), _edgeDicts(newEdges))
    if not validation["is_valid"]:
        recordWorkflowAudit(
            {
                "action": "update_refused",
                "workflow_id": workflowId,
                "actor": actorId,
                "batch_id": batchId,
                "old_version": currentVersion,
                "reason": "validation_failed",
                "errors": validation["errors"],
            }
        )
        return {
            "success": False,
            "code": "validation_failed",
            "error": "定义校验失败，未写入：" + "; ".join(validation["errors"]),
            "errors": validation["errors"],
            "warnings": validation["warnings"],
            "version": currentVersion,
            "safe_version": (_safePayload(storage, workflowId) or {}).get("version"),
        }

    safe = storage.getSafeVersion(workflowId)
    if status == "published" and (safe is None or not safe["valid"]):
        try:
            safe = storage.ensureSafeVersion(
                workflowId,
                reason="before_agent_update",
                evidence={"actor": actorId, "batch_id": batchId},
            )
            if safe.get("created"):
                recordWorkflowAudit(
                    {
                        "action": "safe_baseline",
                        "workflow_id": workflowId,
                        "actor": actorId,
                        "batch_id": batchId,
                        "version": safe["version"],
                        "reason": "before_agent_update",
                    }
                )
        except Exception as exc:  # noqa: BLE001 - 快照失败则拒绝直接改
            recordWorkflowAudit(
                {
                    "action": "update_refused",
                    "workflow_id": workflowId,
                    "actor": actorId,
                    "batch_id": batchId,
                    "old_version": currentVersion,
                    "reason": "safe_version_unavailable",
                    "error": str(exc),
                }
            )
            return {
                "success": False,
                "code": "safe_version_unavailable",
                "error": f"无法建立安全版本基线，拒绝修改已发布定义: {exc}",
                "version": currentVersion,
            }

    workflow.nodes = newNodes
    workflow.edges = newEdges
    workflow.updated_at = time.time()
    try:
        storage.save_workflow(workflow)
    except Exception as exc:  # noqa: BLE001
        recordWorkflowAudit(
            {
                "action": "update_failed",
                "workflow_id": workflowId,
                "actor": actorId,
                "batch_id": batchId,
                "old_version": currentVersion,
                "error": str(exc),
            }
        )
        return {"success": False, "code": "save_failed", "error": f"保存定义失败: {exc}"}

    newVersion = storage.get_workflow_version_number(workflowId)
    recordWorkflowAudit(
        {
            "action": "update",
            "workflow_id": workflowId,
            "actor": actorId,
            "batch_id": batchId,
            "old_version": currentVersion,
            "new_version": newVersion,
            "note": note,
            "node_count": len(newNodes),
            "edge_count": len(newEdges),
            "safe_version": (safe or {}).get("version"),
        }
    )
    return {
        "success": True,
        "workflow_id": workflowId,
        "version": newVersion,
        "base_version": int(baseVersion),
        "status": _workflowStatus(workflow),
        "safe_version": (safe or {}).get("version"),
        "validation": validation,
    }


def rollbackWorkflowDefinition(
    workflowId: str,
    targetVersion: Optional[int] = None,
    actorId: str = "",
    batchId: str = "",
    storage=None,
) -> Dict[str, Any]:
    """回滚到指定版本；缺省回滚到安全版本。"""
    storage = storage or getWorkflowDefinitionStorage()
    try:
        _loadWorkflow(storage, workflowId, actorId)
    except WorkflowDefinitionError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}

    safe = storage.getSafeVersion(workflowId)
    target = int(targetVersion) if targetVersion is not None else None
    if target is None:
        if safe is None or not safe["valid"]:
            return {
                "success": False,
                "code": "no_safe_version",
                "error": "没有可回滚的安全版本",
                "workflow_id": workflowId,
            }
        target = int(safe["version"])

    versions = {int(item["version"]) for item in storage.list_workflow_versions(workflowId)}
    if target not in versions:
        return {
            "success": False,
            "code": "version_not_found",
            "error": f"目标版本快照不存在: {target}",
            "available_versions": sorted(versions, reverse=True),
        }

    if not storage.rollback_workflow(workflowId, target):
        return {"success": False, "code": "rollback_failed", "error": "回滚失败"}

    newVersion = storage.get_workflow_version_number(workflowId)
    currentSafe = storage.getSafeVersion(workflowId)
    recordWorkflowAudit(
        {
            "action": "rollback",
            "workflow_id": workflowId,
            "actor": actorId,
            "batch_id": batchId,
            "restored_from": target,
            "new_version": newVersion,
            "safe_version": currentSafe["version"] if currentSafe else None,
        }
    )
    return {
        "success": True,
        "workflow_id": workflowId,
        "restored_from": target,
        "version": newVersion,
        "safe_version": currentSafe["version"] if currentSafe else None,
    }


def publishWorkflowDefinition(
    workflowId: str,
    actorId: str = "",
    batchId: str = "",
    note: str = "",
    storage=None,
) -> Dict[str, Any]:
    """DRAFT → PUBLISHED；发布动作本身把当前版本设为安全基线。"""
    storage = storage or getWorkflowDefinitionStorage()
    try:
        workflow = _loadWorkflow(storage, workflowId, actorId)
    except WorkflowDefinitionError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}

    status = _workflowStatus(workflow)
    if status not in _EDITABLE_STATUSES:
        return {
            "success": False,
            "code": "invalid_status",
            "error": f"当前状态 {status} 不允许发布（仅 draft/published）",
        }

    validation = validateWorkflowDefinition(
        _nodeDicts(workflow.nodes), _edgeDicts(workflow.edges)
    )
    if not validation["is_valid"]:
        recordWorkflowAudit(
            {
                "action": "publish_refused",
                "workflow_id": workflowId,
                "actor": actorId,
                "batch_id": batchId,
                "reason": "validation_failed",
                "errors": validation["errors"],
            }
        )
        return {
            "success": False,
            "code": "validation_failed",
            "error": "定义校验失败，未发布：" + "; ".join(validation["errors"]),
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

    try:
        from neurova.agent.workflow_agent import (
            compile_workflow_agent,
            manifest_to_agent_info,
        )

        manifest = compile_workflow_agent(workflow)
        agentInfo = manifest_to_agent_info(manifest)
    except Exception as exc:  # noqa: BLE001 - 编译失败不改变状态
        recordWorkflowAudit(
            {
                "action": "publish_refused",
                "workflow_id": workflowId,
                "actor": actorId,
                "batch_id": batchId,
                "reason": "compile_failed",
                "error": str(exc),
            }
        )
        return {
            "success": False,
            "code": "publish_failed",
            "error": f"发布编译失败: {exc}",
        }

    workflow.status = WorkflowStatus.PUBLISHED
    workflow.updated_at = time.time()
    try:
        storage.save_workflow(workflow)
        storage.save_agent(agentInfo)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "code": "save_failed", "error": f"发布落库失败: {exc}"}

    version = storage.get_workflow_version_number(workflowId)
    try:
        storage.setSafeVersion(
            workflowId,
            version,
            reason=f"publish:{note}" if note else "publish",
            evidence={"actor": actorId, "batch_id": batchId, "source": "agent_tool"},
        )
    except ValueError:
        safe = storage.ensureSafeVersion(
            workflowId,
            reason="publish",
            evidence={"actor": actorId, "batch_id": batchId},
        )
        version = int(safe["version"])

    recordWorkflowAudit(
        {
            "action": "publish",
            "workflow_id": workflowId,
            "actor": actorId,
            "batch_id": batchId,
            "version": version,
            "note": note,
            "agent_id": agentInfo.agent_id,
        }
    )
    return {
        "success": True,
        "workflow_id": workflowId,
        "status": "published",
        "version": version,
        "safe_version": version,
        "agent_id": agentInfo.agent_id,
    }


def duplicateWorkflowDefinition(
    workflowId: str,
    name: str = "",
    actorId: str = "",
    batchId: str = "",
    storage=None,
) -> Dict[str, Any]:
    """复制为 DRAFT 草稿副本（修复循环的暂存落点）。"""
    storage = storage or getWorkflowDefinitionStorage()
    try:
        source = _loadWorkflow(storage, workflowId, actorId)
    except WorkflowDefinitionError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}

    newId = f"{workflowId}_copy_{uuid.uuid4().hex[:8]}"
    metadata = copy.deepcopy(source.metadata or {})
    metadata.update(
        {
            "source_workflow_id": source.id,
            "source_version": storage.get_workflow_version_number(workflowId),
            "batch_id": batchId,
        }
    )
    now = time.time()
    draft = WorkflowDefinition(
        id=newId,
        name=name or f"{source.name} (构建草稿)",
        description=source.description,
        version=source.version,
        nodes=copy.deepcopy(source.nodes),
        edges=copy.deepcopy(source.edges),
        variables=copy.deepcopy(source.variables),
        tags=list(source.tags or []),
        category=source.category,
        author=source.author,
        created_at=now,
        updated_at=now,
        status=WorkflowStatus.DRAFT,
        template=False,
        public=False,
        metadata=metadata,
        user_id=actorId or None,
        project_id=source.project_id,
        agent_id=source.agent_id,
        origin="nl_chat",
    )
    try:
        storage.save_workflow(draft, user_id=actorId or None)
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "code": "save_failed", "error": f"创建草稿副本失败: {exc}"}

    version = storage.get_workflow_version_number(newId)
    recordWorkflowAudit(
        {
            "action": "duplicate",
            "workflow_id": workflowId,
            "draft_workflow_id": newId,
            "actor": actorId,
            "batch_id": batchId,
            "source_version": metadata["source_version"],
            "version": version,
        }
    )
    return {
        "success": True,
        "workflow_id": newId,
        "source_workflow_id": workflowId,
        "name": draft.name,
        "status": "draft",
        "version": version,
    }


async def executeWorkflowDefinition(
    workflowId: str,
    inputs: Optional[Dict[str, Any]] = None,
    allowDraft: bool = False,
    actorId: str = "",
    actorAgentId: Optional[str] = None,
    sessionId: str = "",
    storage=None,
) -> Dict[str, Any]:
    """执行定义：默认只允许已发布；allowDraft 用于修复循环的草稿试跑。

    已发布执行成功才把当前版本提升为安全版本（执行校验凭据）。
    """
    storage = storage or getWorkflowDefinitionStorage()
    try:
        workflow = _loadWorkflow(storage, workflowId, actorId)
    except WorkflowDefinitionError as exc:
        return {"success": False, "code": exc.code, "error": str(exc)}

    status = _workflowStatus(workflow)
    if status != "published" and not allowDraft:
        return {
            "success": False,
            "code": "draft_execution_forbidden",
            "error": f"工作流未发布（当前 {status}）；试跑草稿需 allow_draft=true",
        }

    validation = validateWorkflowDefinition(
        _nodeDicts(workflow.nodes), _edgeDicts(workflow.edges)
    )
    if not validation["is_valid"]:
        return {
            "success": False,
            "code": "validation_failed",
            "error": "执行前校验失败：" + "; ".join(validation["errors"]),
            "errors": validation["errors"],
            "warnings": validation["warnings"],
        }

    from .execution_engine import get_workflow_executor

    try:
        instance = await get_workflow_executor().execute(
            workflow,
            dict(inputs or {}),
            user_id=actorId or None,
            agent_id=actorAgentId,
            session_id=sessionId or None,
        )
    except Exception as exc:  # noqa: BLE001 - 执行异常转结构化结果
        recordWorkflowAudit(
            {
                "action": "execute_failed",
                "workflow_id": workflowId,
                "actor": actorId,
                "error": str(exc),
                "status": status,
            }
        )
        return {"success": False, "code": "run_failed", "error": f"工作流执行异常: {exc}"}

    statusValue = str(getattr(getattr(instance, "status", None), "value", instance.status))
    nodeResults = {}
    for nodeId, nodeResult in (getattr(instance, "node_results", None) or {}).items():
        nodeResults[nodeId] = {
            "status": str(
                getattr(getattr(nodeResult, "status", None), "value", nodeResult.status)
            ),
            "output": getattr(nodeResult, "output", None),
            "error": getattr(nodeResult, "error", None),
            "duration": getattr(nodeResult, "duration", None),
        }
    succeeded = statusValue in ("completed", "succeeded", "success")
    executionId = str(getattr(instance, "id", "") or "")

    safeVersion = None
    if succeeded and status == "published":
        version = storage.get_workflow_version_number(workflowId)
        try:
            storage.setSafeVersion(
                workflowId,
                version,
                reason="execution_verified",
                evidence={"execution_id": executionId, "actor": actorId},
            )
            safeVersion = version
        except ValueError as exc:
            logger.warning("执行成功但安全版本提升失败: %s", exc)

    recordWorkflowAudit(
        {
            "action": "execute",
            "workflow_id": workflowId,
            "actor": actorId,
            "status": statusValue,
            "execution_id": executionId,
            "safe_version": safeVersion,
        }
    )
    return {
        "success": succeeded,
        "workflow_id": workflowId,
        "status": statusValue,
        "execution_id": executionId,
        "outputs": getattr(instance, "outputs", None) or {},
        "error": getattr(instance, "error", None),
        "node_results": nodeResults,
        "duration": getattr(instance, "duration", None),
        "safe_version": safeVersion,
    }


__all__ = [
    "WorkflowDefinitionError",
    "getWorkflowDefinitionStorage",
    "validateWorkflowDefinition",
    "recordWorkflowAudit",
    "getWorkflowDefinition",
    "updateWorkflowDefinition",
    "rollbackWorkflowDefinition",
    "publishWorkflowDefinition",
    "duplicateWorkflowDefinition",
    "executeWorkflowDefinition",
]
