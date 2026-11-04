"""构建批次补偿执行（§12.13 跨 surface 残余风险）。

读取 `batch_journal` 的 undo 条目，按逆序逐面回滚；每个 surface 仍走自己的
事务/版本锁，不做跨存储 2PC。已补偿条目不重放。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from neurova.core.logger import get_logger

from .batch_journal import listCompensations, markCompensated

logger = get_logger(__name__)


async def compensateBuildBatch(
    batchId: str,
    *,
    actorId: str = "",
    sessionId: str = "",
    storage=None,
    canvasStore=None,
    canvasOpService=None,
    customNodeService=None,
) -> Dict[str, Any]:
    entries = listCompensations(batchId)
    pending = [
        (index, entry)
        for index, entry in enumerate(entries)
        if not entry.get("compensated_at")
    ]
    if not pending:
        return {
            "success": True,
            "batch_id": batchId,
            "compensated": 0,
            "results": [],
            "message": "没有待补偿条目",
        }

    results: List[Dict[str, Any]] = []
    for index, entry in reversed(pending):
        action = str(entry.get("action") or "")
        payload = entry.get("payload") or {}
        try:
            result = await _applyUndo(
                action,
                payload,
                actorId=actorId,
                sessionId=sessionId,
                storage=storage,
                canvasStore=canvasStore,
                canvasOpService=canvasOpService,
                customNodeService=customNodeService,
            )
        except Exception as exc:  # noqa: BLE001 - 逐面失败要如实上报并停在失败点
            results.append(
                {"index": index, "action": action, "success": False, "error": str(exc)}
            )
            return {
                "success": False,
                "batch_id": batchId,
                "compensated": sum(1 for item in results if item["success"]),
                "results": results,
                "error": f"补偿在 {action} 失败: {exc}",
            }
        markCompensated(batchId, index, result)
        results.append({"index": index, "action": action, "success": True, "result": result})

    return {
        "success": True,
        "batch_id": batchId,
        "compensated": len(results),
        "results": results,
    }


async def _applyUndo(
    action: str,
    payload: Dict[str, Any],
    *,
    actorId: str,
    sessionId: str,
    storage,
    canvasStore,
    canvasOpService,
    customNodeService,
) -> Dict[str, Any]:
    if action == "restore_canvas":
        service = canvasOpService
        if service is None:
            from neurova.collaboration.canvas_ops import CanvasOpService, get_canvas_op_service

            store = canvasStore
            if store is None:
                from neurova.collaboration.canvas_store import get_canvas_store

                store = get_canvas_store()
            service = CanvasOpService(store=store)
        result = await service.restore_snapshot(
            str(payload.get("canvas_id") or ""),
            payload.get("nodes") or [],
            payload.get("edges") or [],
            session_id=sessionId or None,
            actor=actorId or "agent",
            requester_id=actorId or None,
        )
        return {"surface": "canvas", **result}

    if action == "delete_canvas":
        store = canvasStore
        if store is None:
            from neurova.collaboration.canvas_store import get_canvas_store

            store = get_canvas_store()
        deleted = store.delete(
            str(payload.get("canvas_id") or ""), requester_id=actorId or None
        )
        return {"surface": "canvas", "deleted": bool(deleted)}

    if action == "deactivate_node":
        service = customNodeService
        if service is None:
            from neurova.collaboration.neurflow.custom_nodes import (
                get_custom_node_service,
            )

            service = get_custom_node_service()
        node = service.deactivate_node(str(payload.get("node_type") or ""))
        return {"surface": "node", "node_type": node.type, "status": node.status}

    if action == "rollback_workflow":
        from neurova.collaboration.neurflow.workflow_definition_editor import (
            rollbackWorkflowDefinition,
        )

        result = rollbackWorkflowDefinition(
            str(payload.get("workflow_id") or ""),
            targetVersion=payload.get("target_version"),
            actorId=actorId,
            batchId=str(payload.get("batch_id") or ""),
            storage=storage,
        )
        return {"surface": "workflow", **result}

    raise ValueError(f"未知补偿动作: {action}")


__all__ = ["compensateBuildBatch"]
