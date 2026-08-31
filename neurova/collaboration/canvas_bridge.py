"""
画布 → Neurflow 工作流桥接

把 CanvasDesignerPage 保存的画布快照（CanvasSnapshot）转换为可执行的
neurflow WorkflowDefinition，打通"可视化画布 → 工作流引擎"链路。

格式对照:
    画布节点 {id, type, label, position:{x,y}, config}
        → WorkflowNode {id, type, label, position, config}   （类型名一致，直接映射）
    画布边 {id, source:{nodeId, portId}, target:{nodeId, portId}}
        → WorkflowEdge {source: nodeId, target: nodeId,
                        source_handle: portId}               （condition 端口
                        true/false 与 neurflow source_handle 语义天然对齐）

未知节点类型（未注册到 NodeRegistry）抛 ValueError 列明——不静默假执行。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger

try:
    from .models import WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowStatus
    from .node_registry import get_node_registry
except ImportError:  # pragma: no cover
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
    )
    from neurova.collaboration.neurflow.node_registry import get_node_registry

logger = get_logger(__name__)


def _known_node_types() -> set:
    """注册表中已知的节点类型集合（含 builtin/tool/skill/mcp/comfyui/custom）"""
    registry = get_node_registry()
    registry.ensure_builtin()
    # 遗留 A：恢复自定义节点（load_into_registry 幂等——画布运行校验
    # 必须能认出 custom:*，否则重启后含自定义节点的画布 400 未注册）
    try:
        from neurova.collaboration.neurflow.custom_nodes import get_custom_node_service

        get_custom_node_service().load_into_registry()
    except Exception:  # noqa: BLE001 - custom 恢复失败不阻塞 builtin 校验
        pass
    known = set()
    try:
        for d in registry.list_all():
            known.add(d.type)
    except Exception:  # noqa: BLE001 - 注册表接口差异时降级为空集合
        pass
    return known


def canvas_to_workflow(snapshot: Dict[str, Any], name: str = "") -> WorkflowDefinition:
    """画布快照 → WorkflowDefinition

    Args:
        snapshot: 画布快照 {name?, nodes: [...], edges: [...]}
        name: 工作流名称（缺省用画布名）

    Returns:
        可执行的 WorkflowDefinition

    Raises:
        ValueError: 含未知节点类型 / 节点缺少 type 字段
    """
    canvas_nodes: List[Dict[str, Any]] = snapshot.get("nodes", []) or []
    canvas_edges: List[Dict[str, Any]] = snapshot.get("edges", []) or []

    if not canvas_nodes:
        raise ValueError("画布为空，至少需要一个节点")

    known_types = _known_node_types()

    # ── 节点转换 + 类型校验 ──
    wf_nodes: List[WorkflowNode] = []
    unknown_types: List[str] = []
    node_ids = set()
    for cn in canvas_nodes:
        node_id = str(cn.get("id", "")).strip()
        node_type = str(cn.get("type", "")).strip()
        if not node_id or not node_type:
            raise ValueError(f"画布节点缺少 id/type 字段: {cn}")
        if node_type not in known_types:
            unknown_types.append(node_type)
        node_ids.add(node_id)
        wf_nodes.append(
            WorkflowNode(
                id=node_id,
                type=node_type,
                position={
                    "x": float((cn.get("position") or {}).get("x", 0)),
                    "y": float((cn.get("position") or {}).get("y", 0)),
                },
                config=dict(cn.get("config") or {}),
                label=cn.get("label"),
            )
        )

    if unknown_types:
        raise ValueError(
            "画布包含未注册的节点类型，无法执行: "
            + ", ".join(sorted(set(unknown_types)))
            + "（请移除或在节点库中同步）"
        )

    # ── 边转换 ──
    wf_edges: List[WorkflowEdge] = []
    for idx, ce in enumerate(canvas_edges):
        source_ref = ce.get("source") or {}
        target_ref = ce.get("target") or {}
        source_id = str(source_ref.get("nodeId", "")).strip() if isinstance(source_ref, dict) else str(source_ref)
        target_id = str(target_ref.get("nodeId", "")).strip() if isinstance(target_ref, dict) else str(target_ref)
        if not source_id or not target_id:
            # 旧快照可能只有坐标（x1,y1,x2,y2）无逻辑连接——跳过
            logger.debug("跳过无逻辑连接的画布边: %s", ce.get("id"))
            continue
        if source_id not in node_ids or target_id not in node_ids:
            raise ValueError(f"画布边 '{ce.get('id')}' 引用了不存在的节点: {source_id} → {target_id}")

        port_id = source_ref.get("portId") if isinstance(source_ref, dict) else None
        wf_edges.append(
            WorkflowEdge(
                id=str(ce.get("id") or f"edge_{idx}_{source_id}_{target_id}"),
                source=source_id,
                target=target_id,
                # 端口 ID 即 neurflow 的 source_handle（condition 的 true/false、loop 的 current/loop_done）
                source_handle=str(port_id) if port_id else None,
            )
        )

    return WorkflowDefinition(
        id=f"wf_canvas_{uuid.uuid4().hex[:12]}",
        name=name or snapshot.get("name") or "画布工作流",
        description="从画布快照生成",
        version="1.0.0",
        nodes=wf_nodes,
        edges=wf_edges,
        variables=[],
        tags=["canvas"],
        category="canvas",
        author="canvas-bridge",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        metadata={"source": "canvas"},
    )


def definition_to_canvas(workflow: WorkflowDefinition, name: str = "") -> Dict[str, Any]:
    """WorkflowDefinition → 画布快照（反向桥接）

    用途：ComfyUI 导入等"定义优先"的入口把结果落成画布——
    工作流 = 无限画布工作流，画布快照是用户数据的唯一可编辑形态。

    规则:
    1. 节点 type/position/config 原样保留；label/icon/端口从注册表补全
       （未注册类型端口为空，不报错——画布是编辑形态，执行前再校验）
    2. 边 source_handle/target_handle → {nodeId, portId} 引用，
       并按节点位置生成近似连线坐标供前端渲染
    """
    registry = get_node_registry()
    registry.ensure_builtin()

    canvas_nodes: List[Dict[str, Any]] = []
    node_ports: Dict[str, Tuple[List[Dict[str, str]], List[Dict[str, str]]]] = {}
    for wn in workflow.nodes:
        node_id = str(wn.id)
        node_type = str(wn.type)
        definition = registry.get(node_type)

        def _port(pid, plabel):
            # NodeDefinition 端口可能是对象（.id/.label）或 dict（"id"/"label"）
            if isinstance(pid, dict):
                return {"id": str(pid.get("id") or ""), "label": str(pid.get("label") or "")}
            return {"id": str(getattr(pid, "id", "")), "label": str(getattr(pid, "label", plabel or ""))}

        inputs = [_port(p, p.get("label") if isinstance(p, dict) else getattr(p, "label", "")) for p in (definition.inputs if definition else [])]
        outputs = [_port(p, p.get("label") if isinstance(p, dict) else getattr(p, "label", "")) for p in (definition.outputs if definition else [])]
        node_ports[node_id] = (inputs, outputs)
        canvas_nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "label": wn.label or (definition.label if definition else node_type),
                "icon": (definition.icon if definition else "") or "📦",
                "position": {
                    "x": float((wn.position or {}).get("x", 0)),
                    "y": float((wn.position or {}).get("y", 0)),
                },
                "inputs": inputs,
                "outputs": outputs,
                "config": dict(wn.config or {}),
            }
        )

    canvas_edges: List[Dict[str, Any]] = []
    pos = {c["id"]: c["position"] for c in canvas_nodes}
    for we in workflow.edges:
        src_id, tgt_id = str(we.source), str(we.target)
        if src_id not in node_ports or tgt_id not in node_ports:
            continue
        src_inputs, src_outputs = node_ports[src_id]
        tgt_inputs, _tgt_outputs = node_ports[tgt_id]
        source_port = str(we.source_handle) if we.source_handle else (src_outputs[0]["id"] if src_outputs else "out")
        target_port = str(we.target_handle) if we.target_handle else (tgt_inputs[0]["id"] if tgt_inputs else "in")
        sp, tp = pos.get(src_id, {"x": 0, "y": 0}), pos.get(tgt_id, {"x": 0, "y": 0})
        canvas_edges.append(
            {
                "id": str(we.id or f"edge_{src_id}_{target_port}_{tgt_id}"),
                "source": {"nodeId": src_id, "portId": source_port},
                "target": {"nodeId": tgt_id, "portId": target_port},
                # 近似几何：源节点右缘 → 目标节点左缘（前端按端口重算路径）
                "x1": float(sp.get("x", 0)) + 130,
                "y1": float(sp.get("y", 0)) + 30,
                "x2": float(tp.get("x", 0)),
                "y2": float(tp.get("y", 0)) + 30,
            }
        )

    return {
        "name": name or workflow.name or "画布工作流",
        "nodes": canvas_nodes,
        "edges": canvas_edges,
        "metadata": {"source": "workflow", "workflow_id": workflow.id},
    }


__all__ = ["canvas_to_workflow", "definition_to_canvas"]
