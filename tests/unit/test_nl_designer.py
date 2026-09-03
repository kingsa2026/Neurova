"""
测试：自然语言画布设计器（NL → 画布节点/边）(R-8)

契约:
  1. generate_canvas_from_nl(prompt) 经 LLM 生成 WorkflowDefinition JSON
     → 校验 → definition_to_canvas 转画布快照（nodes/edges 含端口引用）
  2. 节点类型白名单：仅注册表已知类型允许；未知类型 → 丢弃该节点并记录（不整体失败）
  3. 生成 JSON 不合法/缺少必需字段 → 返回结构化错误（不抛异常）
  4. 返回快照可直接被前端 canvasNodes/canvasEdges 应用
"""

import json

import pytest

from neurova.collaboration.neurflow.nl_designer import (
    parse_generated_workflow,
    sanitize_node_types,
    generate_canvas_from_nl,
)

VALID_WORKFLOW_JSON = {
    "name": "文本分析流程",
    "description": "LLM 生成后清理摘要",
    "nodes": [
        {"id": "n1", "type": "builtin:start", "label": "开始", "position": {"x": 40, "y": 80}, "config": {}},
        {"id": "n2", "type": "builtin:llm", "label": "摘要", "position": {"x": 260, "y": 80},
         "config": {"prompt": "请总结", "model_name": "auto", "model_provider": "auto"}},
        {"id": "n3", "type": "builtin:end", "label": "结束", "position": {"x": 480, "y": 80}, "config": {}},
    ],
    "edges": [
        {"source": "n1", "target": "n2", "source_handle": "out", "target_handle": "input"},
        {"source": "n2", "target": "n3", "source_handle": "output", "target_handle": "in"},
    ],
}


class TestSanitizeNodeTypes:
    def test_known_types_kept(self):
        known = {"builtin:start", "builtin:llm", "builtin:end"}
        nodes = [
            {"id": "n1", "type": "builtin:start"},
            {"id": "n2", "type": "builtin:llm"},
        ]
        result = sanitize_node_types(nodes, known)
        assert len(result) == 2

    def test_unknown_type_dropped(self):
        known = {"builtin:start"}
        nodes = [
            {"id": "n1", "type": "builtin:start"},
            {"id": "n2", "type": "unknown:weird"},
        ]
        result = sanitize_node_types(nodes, known)
        assert len(result) == 1
        assert result[0]["type"] == "builtin:start"


class TestParseGeneratedWorkflow:
    def test_valid_json_parses(self):
        wf = parse_generated_workflow(json.dumps(VALID_WORKFLOW_JSON))
        assert wf is not None
        assert wf["name"] == "文本分析流程"
        assert len(wf["nodes"]) == 3

    def test_invalid_json_returns_none(self):
        assert parse_generated_workflow("{not json") is None
        assert parse_generated_workflow('[1,2,3]') is None  # 非 dict


class TestGenerateCanvasFromNl:
    @pytest.mark.asyncio
    async def test_fake_llm_produces_canvas(self, monkeypatch):
        from neurova.collaboration.neurflow import nl_designer as m

        async def fake(prompt, agent_id="default", model=None): return json.dumps(VALID_WORKFLOW_JSON)
        monkeypatch.setattr(m, "_call_agent_llm", fake)
        canvas = await generate_canvas_from_nl("帮我设计一个文本分析流程")
        assert canvas["status"] == "success"
        data = canvas["data"]
        assert "nodes" in data and "edges" in data
        assert len(data["nodes"]) == 3
        # 边应带 source/target 端口引用（前端契约 nodeId/portId）
        assert data["edges"][0]["source"]["nodeId"] == "n1"

    @pytest.mark.asyncio
    async def test_edges_use_real_ports(self, monkeypatch):
        """R-8: 边端口必须归一化为注册表真实端口（LLM 常用 out/output，
        但 start 输出是 output、text_input 输出是 text、knowledge_base 输出是 results——
        端口不匹配会导致画布连线悬空）。"""
        from neurova.collaboration.neurflow import nl_designer as m

        fake = {
            "name": "x",
            "nodes": [
                {"id": "n1", "type": "builtin:start", "label": "s", "position": {"x": 40, "y": 80}, "config": {}},
                {"id": "n2", "type": "builtin:text_input", "label": "t", "position": {"x": 260, "y": 80}, "config": {"value": "hi"}},
                {"id": "n3", "type": "builtin:end", "label": "e", "position": {"x": 480, "y": 80}, "config": {}},
            ],
            "edges": [
                # LLM 习惯用 out/output/input —— 需归一化为真实端口
                {"source": "n1", "target": "n2", "source_handle": "out", "target_handle": "input"},
                {"source": "n2", "target": "n3", "source_handle": "output", "target_handle": "input"},
            ],
        }

        async def fake_llm(prompt, agent_id="default", model=None):
            return json.dumps(fake)

        monkeypatch.setattr(m, "_call_agent_llm", fake_llm)
        canvas = await generate_canvas_from_nl("x")
        assert canvas["status"] == "success"
        edges = canvas["data"]["edges"]
        # n1(start 有输出)→n2(text_input 无输入) 不可连 → 丢弃；
        # n2(text 输出)→n3(end 有输入) 保留且端口归一化为真实值
        assert len(edges) == 1
        assert edges[0]["source"]["nodeId"] == "n2"
        assert edges[0]["source"]["portId"] == "text"
        assert edges[0]["target"]["nodeId"] == "n3"
        assert edges[0]["target"]["portId"] == "input"

    @pytest.mark.asyncio
    async def test_llm_error_returns_failed(self, monkeypatch):
        from neurova.collaboration.neurflow import nl_designer as m

        async def boom(prompt):
            raise RuntimeError("LLM 不可用")

        monkeypatch.setattr(m, "_call_agent_llm", boom)
        canvas = await generate_canvas_from_nl("任意")
        assert canvas["status"] == "failed"
        assert "error" in canvas

    @pytest.mark.asyncio
    async def test_specifies_agent_and_model(self, monkeypatch):
        """R-8: generate_canvas_from_nl 透传 agent_id 与 model 给 _call_agent_llm。"""
        from neurova.collaboration.neurflow import nl_designer as m

        captured = {}

        async def fake(prompt, agent_id="default", model=None):
            captured["agent_id"] = agent_id
            captured["model"] = model
            return json.dumps(VALID_WORKFLOW_JSON)

        monkeypatch.setattr(m, "_call_agent_llm", fake)
        canvas = await generate_canvas_from_nl("帮我设计", agent_id="kai", model="glm-4")
        assert canvas["status"] == "success"
        assert captured["agent_id"] == "kai"
        assert captured["model"] == "glm-4"

    @pytest.mark.asyncio
    async def test_default_agent_fallback(self, monkeypatch):
        """未传 agent_id 时 _call_agent_llm 默认使用 default。"""
        from neurova.collaboration.neurflow import nl_designer as m

        captured = {}

        async def fake(prompt, agent_id="default", model=None):
            captured["agent_id"] = agent_id
            return json.dumps(VALID_WORKFLOW_JSON)

        monkeypatch.setattr(m, "_call_agent_llm", fake)
        await generate_canvas_from_nl("x")
        assert captured["agent_id"] == "default"
