"""P1-5 MCP server 面（TDD — Dify `core/mcp/server` 对标）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §3.4/§4 P1-5）：
Neurova 平台自身可作为 MCP server 对外暴露能力面：
- NeurovaMCPServer：协议无关的核心（清单/调用），传输层（stdio/SSE）
  由 SDK 适配器另行包壳——核心先落，传输后接
- list_tools()：已发布工作流（workflow_as_tool schema 复用）+ 技能
  （skill_registry 清单）聚合为 MCP tools 形态（name/description/
  inputSchema）
- call_tool(name, arguments)：按前缀分派 workflow:/skill:*；
  工作流经 workflow_as_tool（DAG 输入校验 + 发布态检查），技能经
  skill_registry.get_skill().execute
- 未知工具 → MCP 语义错误信封（不崩）；技能工具名不带前缀的注册面
  归一为 skill:{name}
"""

import asyncio
import time
from unittest.mock import MagicMock

import pytest


class TestListTools:
    def test_aggregates_workflows_and_skills(self, tmp_path):
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )
        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        storage = NeurflowStorage(str(tmp_path / "nf.db"))
        storage.save_workflow(WorkflowDefinition(
            id="wf_mcp", name="MCP 样例流", description="demo", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0},
                             config={"fields": [{"name": "city", "type": "string", "label": "城市", "required": True}]}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 99, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="s", target="e")],
            variables=[], tags=[], category="g", author="t",
            created_at=time.time(), updated_at=time.time(),
            status=WorkflowStatus.PUBLISHED,
        ))

        skill = MagicMock()
        skill.name = "translate"
        skill.description = "翻译技能"
        registry = MagicMock()
        registry._skills = {"translate": skill}

        server = NeurovaMCPServer(storage=storage, skill_registry=registry)
        tools = server.list_tools()

        names = [t["name"] for t in tools]
        assert "workflow:wf_mcp" in names
        assert "skill:translate" in names
        wf_tool = next(t for t in tools if t["name"] == "workflow:wf_mcp")
        assert wf_tool["inputSchema"]["properties"]["city"]["type"] == "string"
        skill_tool = next(t for t in tools if t["name"] == "skill:translate")
        assert "翻译" in skill_tool["description"]


class TestCallTool:
    @pytest.fixture
    def server(self, tmp_path):
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )
        from neurova.collaboration.neurflow.storage import NeurflowStorage
        from neurova.tool_layers.mcp_server import NeurovaMCPServer

        storage = NeurflowStorage(str(tmp_path / "nf.db"))
        storage.save_workflow(WorkflowDefinition(
            id="wf_call", name="调用流", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0},
                             config={"fields": [{"name": "q", "type": "string", "required": True}]}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 99, "y": 0}, config={}),
            ],
            edges=[WorkflowEdge(id="e1", source="s", target="e")],
            variables=[], tags=[], category="g", author="t",
            created_at=time.time(), updated_at=time.time(),
            status=WorkflowStatus.PUBLISHED,
        ))

        skill_result = MagicMock()
        skill_result.success = True
        skill_result.data = {"answer": "42"}
        skill = MagicMock()
        skill.name = "oracle"
        skill.description = "x"

        async def _skill_exec(params, context=None):
            return skill_result

        skill.execute = _skill_exec
        registry = MagicMock()
        registry._skills = {"oracle": skill}

        return NeurovaMCPServer(storage=storage, skill_registry=registry)

    @pytest.mark.asyncio
    async def test_call_workflow_tool(self, server):
        out = await server.call_tool("workflow:wf_call", {"q": "hi"})
        assert out["success"] is True, out
        assert "result" in out

    @pytest.mark.asyncio
    async def test_call_skill_tool(self, server):
        out = await server.call_tool("skill:oracle", {"task": "?"})
        assert out["success"] is True
        assert out["result"]["answer"] == "42"

    @pytest.mark.asyncio
    async def test_call_unknown_tool_mcp_error(self, server):
        """MCP 语义错误信封（isError 形态，不抛异常）"""
        out = await server.call_tool("tool:nope", {})
        assert out.get("isError") is True
        assert "nope" in out.get("error", "")

    @pytest.mark.asyncio
    async def test_workflow_required_validation_still_applies(self, server):
        """MCP 面不绕过 DAG 输入校验（必填缺失拒执行）"""
        out = await server.call_tool("workflow:wf_call", {})
        assert out["success"] is False
        assert "q" in (out.get("error") or "")
