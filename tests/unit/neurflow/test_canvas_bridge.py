"""画布 → Neurflow 工作流桥接测试"""

import pytest

from neurova.collaboration.canvas_bridge import canvas_to_workflow, definition_to_canvas
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)


def make_snapshot(nodes, edges, name="测试画布"):
    return {"name": name, "nodes": nodes, "edges": edges}


def node(id, type, config=None, x=0, y=0, label=None):
    return {
        "id": id,
        "type": type,
        "label": label or id,
        "icon": "🤖",
        "position": {"x": x, "y": y},
        "inputs": [{"id": "in", "label": "in"}],
        "outputs": [{"id": "out", "label": "out"}],
        "config": config or {},
    }


def edge(id, source_node, source_port, target_node, target_port):
    return {
        "id": id,
        "source": {"nodeId": source_node, "portId": source_port},
        "target": {"nodeId": target_node, "portId": target_port},
        "x1": 0,
        "y1": 0,
        "x2": 100,
        "y2": 100,
    }


class TestCanvasConversion:
    def test_basic_conversion(self):
        snapshot = make_snapshot(
            nodes=[
                node("start", "builtin:start"),
                node("agent1", "builtin:agent", {"agent_id": "researcher", "task": "调研"}),
                node("end", "builtin:end"),
            ],
            edges=[
                edge("e1", "start", "out", "agent1", "task"),
                edge("e2", "agent1", "result", "end", "in"),
            ],
        )
        wf = canvas_to_workflow(snapshot, name="画布工作流")

        assert wf.name == "画布工作流"
        assert len(wf.nodes) == 3
        node_map = {n.id: n for n in wf.nodes}
        assert node_map["agent1"].type == "builtin:agent"
        assert node_map["agent1"].config == {"agent_id": "researcher", "task": "调研"}
        # 边：portId → source_handle
        assert len(wf.edges) == 2
        e1 = next(e for e in wf.edges if e.id == "e1")
        assert e1.source == "start"
        assert e1.target == "agent1"
        assert e1.source_handle == "out"

    def test_condition_port_maps_to_source_handle(self):
        """condition 的 true/false 端口与 neurflow source_handle 语义对齐"""
        snapshot = make_snapshot(
            nodes=[
                node("cond", "builtin:condition"),
                node("a", "builtin:transform"),
                node("b", "builtin:transform"),
            ],
            edges=[
                edge("e1", "cond", "true", "a", "in"),
                edge("e2", "cond", "false", "b", "in"),
            ],
        )
        wf = canvas_to_workflow(snapshot)
        edge_map = {e.target: e for e in wf.edges}
        assert edge_map["a"].source_handle == "true"
        assert edge_map["b"].source_handle == "false"

    def test_unknown_type_raises_with_type_listed(self):
        # 重置全局注册表：其他测试（如 ComfyUI 导入）会向单例注册节点类型，
        # 本测试必须与执行顺序无关
        from neurova.collaboration.neurflow.node_registry import reset_node_registry

        reset_node_registry()
        snapshot = make_snapshot(
            nodes=[
                node("k", "comfyui:KSampler"),
                node("start", "builtin:start"),
            ],
            edges=[],
        )
        with pytest.raises(ValueError) as exc:
            canvas_to_workflow(snapshot)
        assert "comfyui:KSampler" in str(exc.value)

    def test_empty_canvas_raises(self):
        with pytest.raises(ValueError) as exc:
            canvas_to_workflow(make_snapshot([], []))
        assert "至少需要一个节点" in str(exc.value)

    def test_geometry_only_edges_skipped(self):
        """旧快照的纯坐标边（无逻辑连接）被跳过"""
        snapshot = make_snapshot(
            nodes=[node("a", "builtin:start"), node("b", "builtin:end")],
            edges=[{"id": "geo", "x1": 0, "y1": 0, "x2": 50, "y2": 50}],
        )
        wf = canvas_to_workflow(snapshot)
        assert len(wf.edges) == 0

    def test_metadata_marks_canvas_source(self):
        snapshot = make_snapshot(nodes=[node("a", "builtin:start")], edges=[])
        wf = canvas_to_workflow(snapshot)
        assert wf.metadata.get("source") == "canvas"
        assert wf.category == "canvas"


def make_definition():
    return WorkflowDefinition(
        id="wf_test_1",
        name="反向桥接",
        description="测试定义",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="1", type="comfyui:CheckpointLoaderSimple", position={"x": 0, "y": 0}, config={"ckpt_name": "a.safetensors"}, label="CheckpointLoaderSimple"),
            WorkflowNode(id="2", type="comfyui:VAEDecode", position={"x": 260, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="1", target="2", source_handle="0", target_handle="samples"),
        ],
        variables=[],
        tags=["comfyui"],
        category="comfyui",
        author="comfyui-importer",
        created_at=0.0,
        updated_at=0.0,
        status=WorkflowStatus.DRAFT,
    )


class TestDefinitionToCanvas:
    def test_roundtrip_nodes_keep_type_position_config(self):
        canvas = definition_to_canvas(make_definition(), name="导入画布")
        assert canvas["name"] == "导入画布"
        types = {n["id"]: n["type"] for n in canvas["nodes"]}
        assert types["1"] == "comfyui:CheckpointLoaderSimple"
        assert types["2"] == "comfyui:VAEDecode"
        n1 = next(n for n in canvas["nodes"] if n["id"] == "1")
        assert n1["position"] == {"x": 0.0, "y": 0.0}
        assert n1["config"] == {"ckpt_name": "a.safetensors"}

    def test_nodes_enriched_with_registry_ports(self):
        """端口来自节点注册表（comfyui 节点已注册时）；未知类型端口为空不报错"""
        from neurova.collaboration.neurflow.node_registry import get_node_registry

        registry = get_node_registry()
        from neurova.collaboration.neurflow import comfyui_nodes

        comfyui_nodes.register_comfyui_nodes(registry)

        canvas = definition_to_canvas(make_definition())
        n1 = next(n for n in canvas["nodes"] if n["id"] == "1")
        assert n1["outputs"], "已注册节点应带输出端口"
        assert all("id" in p and "label" in p for p in n1["outputs"] + n1["inputs"])

    def test_edges_map_handles_to_port_refs(self):
        canvas = definition_to_canvas(make_definition())
        assert len(canvas["edges"]) == 1
        e = canvas["edges"][0]
        assert e["source"] == {"nodeId": "1", "portId": "0"}
        assert e["target"]["nodeId"] == "2"
        assert e["target"]["portId"]  # 回退到首个输入端口 id
        # 坐标按节点位置近似生成（前端渲染用）
        assert all(k in e for k in ("x1", "y1", "x2", "y2"))

    def test_metadata_marks_workflow_source(self):
        canvas = definition_to_canvas(make_definition())
        assert canvas["metadata"]["source"] == "workflow"
        assert canvas["metadata"]["workflow_id"] == "wf_test_1"
