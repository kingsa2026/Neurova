# -*- coding: utf-8 -*-
"""Neurflow 模板公共构建器（审计 P2-28 剩余项）。

``templates/`` 下 8 个领域模板的 ``_create_nodes`` / ``_create_edges`` /
``_create_variables`` 同形：以声明式纯数据 spec 描述节点/边/变量，再逐字段
装配成 WorkflowNode / WorkflowEdge / WorkflowVariable。本模块把"装配"这一
公共形状收口为单一实现，模板文件只保留各自的声明式 spec。

行为保持：构建结果与各模板原先手写的数据类逐字段一致，由快照对照测试钉住
（``tests/unit/neurflow/test_template_builder_snapshot.py``，fixture 为重构前
抓取的原始输出）。spec 是模块级共享字面量，config/metadata/default_value
深拷贝后挂载，保持与原先"每次调用重建字面量"相同的可变对象语义。
"""

import copy
from typing import Any, Dict, List

from ..models import WorkflowEdge, WorkflowNode, WorkflowVariable


def buildNodes(specs: List[Dict[str, Any]]) -> List[WorkflowNode]:
    """按声明式节点 spec 构建节点列表。

    spec 字段：
    - id/type/config 必填；x/y 组装为 position
    - label/metadata 可选（缺省 None / 空 dict，与 WorkflowNode 字段默认一致）
    """
    nodes: List[WorkflowNode] = []
    for spec in specs:
        nodes.append(
            WorkflowNode(
                id=spec["id"],
                type=spec["type"],
                position={"x": spec["x"], "y": spec["y"]},
                config=copy.deepcopy(spec["config"]),
                label=spec.get("label"),
                metadata=copy.deepcopy(spec.get("metadata", {})),
            )
        )
    return nodes


def buildEdges(specs: List[Dict[str, Any]]) -> List[WorkflowEdge]:
    """按声明式边 spec 构建边列表。

    spec 字段：id/source/target 必填；source_handle/target_handle/label/condition
    可选（缺省 None，与 WorkflowEdge 字段默认一致）。
    """
    edges: List[WorkflowEdge] = []
    for spec in specs:
        edges.append(
            WorkflowEdge(
                id=spec["id"],
                source=spec["source"],
                target=spec["target"],
                source_handle=spec.get("source_handle"),
                target_handle=spec.get("target_handle"),
                label=spec.get("label"),
                condition=spec.get("condition"),
            )
        )
    return edges


def buildVariables(specs: List[Dict[str, Any]]) -> List[WorkflowVariable]:
    """按声明式变量 spec 构建变量列表。

    spec 字段：name/type 必填；default_value/description/scope 可选
    （scope 缺省 "workflow"，与 WorkflowVariable 字段默认一致）。
    """
    variables: List[WorkflowVariable] = []
    for spec in specs:
        variables.append(
            WorkflowVariable(
                name=spec["name"],
                type=spec["type"],
                default_value=copy.deepcopy(spec.get("default_value")),
                description=spec.get("description"),
                scope=spec.get("scope", "workflow"),
            )
        )
    return variables


# 便捷导出
__all__ = ["buildNodes", "buildEdges", "buildVariables"]
