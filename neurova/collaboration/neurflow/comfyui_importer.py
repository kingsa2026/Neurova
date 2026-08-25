"""
ComfyUI 工作流导入器 — TDD 切片 3

把 ComfyUI API 格式的工作流 JSON 转换为 Neurflow WorkflowDefinition。

ComfyUI API 格式:
    {
        "1": {"class_type": "CheckpointLoaderSimple",
              "inputs": {"ckpt_name": "model.safetensors"}},
        "2": {"class_type": "CLIPTextEncode",
              "inputs": {"text": "prompt", "clip": ["1", 1]}}
    }

转换规则:
1. ComfyUI 节点 ID → WorkflowNode.id（保留原始字符串 ID）
2. class_type → type="comfyui:{class_type}"
3. 标量 inputs → node.config
4. 数组 inputs [node_id, output_index] → WorkflowEdge
   （source_handle=str(output_index)，target_handle=输入字段名）
5. 自动网格布局 position
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Tuple

from neurova.core.logger import get_logger

try:
    from .models import WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowStatus
except ImportError:  # pragma: no cover
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition,
        WorkflowEdge,
        WorkflowNode,
        WorkflowStatus,
    )

logger = get_logger(__name__)


def _split_inputs(raw_inputs: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Tuple[str, str, str, Any]]]:
    """把节点 inputs 拆为（标量配置, 连接边描述）

    数组输入 [node_id, output_index] 视为对上游节点输出的引用 → 边。
    """
    config: Dict[str, Any] = {}
    connections: List[Tuple[str, str, str, Any]] = []  # (input_field, source_id, source_handle, raw)

    for field_name, value in (raw_inputs or {}).items():
        if isinstance(value, (list, tuple)) and len(value) == 2 and isinstance(value[0], str):
            source_id, output_index = value
            connections.append((field_name, str(source_id), str(output_index), value))
        else:
            config[field_name] = value
    return config, connections


def _grid_position(index: int, columns: int = 4) -> Dict[str, float]:
    """自动网格布局：每行 columns 个节点，横向 260 / 纵向 180 间距"""
    col = index % columns
    row = index // columns
    return {"x": float(col * 260), "y": float(row * 180)}


def import_comfyui_workflow(
    comfyui_workflow: Dict[str, Any],
    name: str = "ComfyUI 导入工作流",
    description: str = "",
) -> WorkflowDefinition:
    """把 ComfyUI API 格式工作流转换为 Neurflow WorkflowDefinition

    Args:
        comfyui_workflow: ComfyUI API 格式 JSON（{node_id: {class_type, inputs}}）
        name: 导入后的工作流名称
        description: 工作流描述

    Returns:
        WorkflowDefinition（category="comfyui"，metadata 标记来源并保留原始 JSON）

    Raises:
        ValueError: 节点缺少 class_type
    """
    nodes: List[WorkflowNode] = []
    edges: List[WorkflowEdge] = []

    for index, (node_id, node_spec) in enumerate((comfyui_workflow or {}).items()):
        class_type = (node_spec or {}).get("class_type")
        if not class_type:
            raise ValueError(
                f"ComfyUI 节点 '{node_id}' 缺少 class_type 字段，无法导入"
            )

        config, connections = _split_inputs((node_spec or {}).get("inputs", {}))

        nodes.append(
            WorkflowNode(
                id=str(node_id),
                type=f"comfyui:{class_type}",
                position=_grid_position(index),
                config=config,
                label=str(class_type),
            )
        )

        for field_name, source_id, source_handle, _raw in connections:
            edges.append(
                WorkflowEdge(
                    id=f"edge_{node_id}_{field_name}_{source_id}_{source_handle}",
                    source=source_id,
                    target=str(node_id),
                    source_handle=source_handle,
                    target_handle=field_name,
                )
            )

    return WorkflowDefinition(
        id=f"wf_comfyui_{uuid.uuid4().hex[:12]}",
        name=name,
        description=description or "从 ComfyUI API 工作流导入",
        version="1.0.0",
        nodes=nodes,
        edges=edges,
        variables=[],
        tags=["comfyui"],
        category="comfyui",
        author="comfyui-importer",
        created_at=time.time(),
        updated_at=time.time(),
        status=WorkflowStatus.DRAFT,
        metadata={
            "source": "comfyui",
            "original_comfyui_workflow": comfyui_workflow or {},
        },
    )


__all__ = ["import_comfyui_workflow"]
