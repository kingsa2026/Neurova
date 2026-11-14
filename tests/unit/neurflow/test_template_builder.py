# -*- coding: utf-8 -*-
"""模板公共构建器单元测试 — 装配行为与字段缺省逐一钉住。

buildNodes/buildEdges/buildVariables 是 8 个 Neurflow 模板声明式 spec 的
唯一装配出口；本测试钉住装配语义（字段映射、缺省值、每次构建深拷贝）。
"""
import pytest

from neurova.collaboration.neurflow.models import WorkflowEdge, WorkflowNode, WorkflowVariable
from neurova.collaboration.neurflow.templates.builder import buildEdges, buildNodes, buildVariables


class TestBuildNodes:
    def test_full_spec_builds_exact_node(self):
        """全字段 spec 逐字段装配为 WorkflowNode"""
        spec = {
            "id": "start",
            "type": "builtin:start",
            "x": 100,
            "y": 200,
            "label": "开始",
            "metadata": {"category": "flow"},
            "config": {"inputs_schema": {"topic": {"type": "textarea", "required": True}}},
        }
        nodes = buildNodes([spec])

        assert len(nodes) == 1
        node = nodes[0]
        assert isinstance(node, WorkflowNode)
        assert node.id == "start"
        assert node.type == "builtin:start"
        assert node.position == {"x": 100, "y": 200}
        assert node.label == "开始"
        assert node.metadata == {"category": "flow"}
        assert node.config == spec["config"]
        # 数据类默认字段保持
        assert node.enabled is True
        assert node.mock_output is None

    def test_minimal_spec_uses_field_defaults(self):
        """只带必填字段的 spec：label=None、metadata=空 dict"""
        node = buildNodes(
            [{"id": "n1", "type": "builtin:llm", "x": 0, "y": 0, "config": {"prompt": "p"}}]
        )[0]

        assert node.label is None
        assert node.metadata == {}
        assert node.enabled is True

    def test_config_deep_copied_per_build(self):
        """模块级 spec 被多次构建共享：config 必须深拷贝，互不串扰、不污染 spec"""
        spec = {"id": "n1", "type": "builtin:llm", "x": 0, "y": 0, "config": {"a": {"b": 1}}}
        first, second = buildNodes([spec]), buildNodes([spec])

        first[0].config["a"]["b"] = 999

        assert second[0].config["a"]["b"] == 1
        assert spec["config"]["a"]["b"] == 1

    def test_position_key_order_is_x_then_y(self):
        """position 键序与原模板字面量一致（x 在前）"""
        node = buildNodes([{"id": "n", "type": "t", "x": 1, "y": 2, "config": {}}])[0]
        assert list(node.position.keys()) == ["x", "y"]


class TestBuildEdges:
    def test_basic_edge(self):
        edges = buildEdges([{"id": "e1", "source": "a", "target": "b"}])

        assert len(edges) == 1
        edge = edges[0]
        assert isinstance(edge, WorkflowEdge)
        assert edge.id == "e1"
        assert edge.source == "a"
        assert edge.target == "b"
        assert edge.source_handle is None
        assert edge.target_handle is None
        assert edge.label is None
        assert edge.condition is None

    def test_conditional_edge_with_source_handle(self):
        edge = buildEdges(
            [{"id": "e2", "source": "check", "target": "next", "source_handle": "true"}]
        )[0]

        assert edge.source_handle == "true"


class TestBuildVariables:
    def test_full_spec(self):
        variables = buildVariables(
            [
                {
                    "name": "threshold",
                    "type": "number",
                    "default_value": 0.95,
                    "description": "阈值",
                    "scope": "workflow",
                }
            ]
        )

        assert len(variables) == 1
        var = variables[0]
        assert isinstance(var, WorkflowVariable)
        assert var.name == "threshold"
        assert var.type == "number"
        assert var.default_value == 0.95
        assert var.description == "阈值"
        assert var.scope == "workflow"

    def test_scope_defaults_to_workflow(self):
        var = buildVariables([{"name": "tone", "type": "string"}])[0]

        assert var.scope == "workflow"
        assert var.default_value is None
        assert var.description is None
