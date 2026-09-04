"""P1-3 workflow_as_tool（TDD — Dify 对标 §4 P1-3）。

契约（Dify `workflow_as_tool`：子流程是一等工具）：
1. list_published_workflows_as_tools(storage)：已发布工作流 → 工具清单
   （name=workflow:{id}，description 来自工作流，parameters 来自
   start 节点 fields——天然自带输入校验（DAG 定义））
2. build_workflow_tool_schema(wf)：OpenAI function schema 形态
3. execute_workflow_as_tool(workflow_id, inputs, user_id)：统一派发
   （经 workflow_agent 桥或直接执行），返回 {success, result}
4. tool_executor：workflow:{id} 命名空间工具可直接被 execute 分派
   （注册进 builtin 分派面），未注册工作流明确报错
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest


def _make_wf(wf_id="wf_tool_1", name="天气查询流", fields=None, status="published"):
    from neurova.collaboration.neurflow.models import (
        WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
    )

    start_config = {"fields": fields or [
        {"name": "city", "type": "string", "label": "城市", "required": True},
        {"name": "date", "type": "string", "label": "日期", "required": False},
    ]}
    return WorkflowDefinition(
        id=wf_id, name=name, description="按城市查询天气", version="1.0.0",
        nodes=[
            WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0}, config=start_config),
            WorkflowNode(id="e", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ],
        edges=[WorkflowEdge(id="e1", source="s", target="e")],
        variables=[], tags=[], category="general", author="t",
        created_at=time.time(), updated_at=time.time(),
        status=WorkflowStatus(status) if isinstance(status, str) else status,
    )


def _storage_with(wf, tmp_path):
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    storage = NeurflowStorage(str(tmp_path / "nf.db"))
    storage.save_workflow(wf)
    return storage


class TestSchemaGeneration:
    def test_build_schema_from_start_fields(self, tmp_path):
        from neurova.collaboration.neurflow.workflow_as_tool import build_workflow_tool_schema

        wf = _make_wf()
        schema = build_workflow_tool_schema(wf)

        assert schema["name"] == "workflow:wf_tool_1"
        assert "天气查询流" in schema["description"]
        props = schema["parameters"]["properties"]
        assert props["city"]["type"] == "string"
        assert schema["parameters"]["required"] == ["city"], "required 字段来自 start 节点声明"

    def test_draft_workflows_excluded(self, tmp_path):
        from neurova.collaboration.neurflow.workflow_as_tool import list_published_workflows_as_tools

        storage = _storage_with(_make_wf("wf_pub", status="published"), tmp_path)
        storage.save_workflow(_make_wf("wf_draft", status="draft"))
        tools = list_published_workflows_as_tools(storage)
        names = [t["name"] for t in tools]
        assert "workflow:wf_pub" in names
        assert "workflow:wf_draft" not in names

    def test_tool_list_shape(self, tmp_path):
        from neurova.collaboration.neurflow.workflow_as_tool import list_published_workflows_as_tools

        storage = _storage_with(_make_wf(), tmp_path)
        tools = list_published_workflows_as_tools(storage)
        assert len(tools) == 1
        assert tools[0]["name"].startswith("workflow:")
        assert "parameters" in tools[0]


class TestDispatch:
    @pytest.mark.asyncio
    async def test_execute_via_dispatch(self, tmp_path):
        """execute_workflow_as_tool 真实执行（start→end 直通）"""
        from neurova.collaboration.neurflow.workflow_as_tool import execute_workflow_as_tool

        storage = _storage_with(_make_wf(), tmp_path)
        outcome = await execute_workflow_as_tool(
            "wf_tool_1", {"city": "北京"}, storage=storage, user_id="u1"
        )
        assert outcome["success"] is True, outcome.get("error")
        assert "execution_id" in outcome

    @pytest.mark.asyncio
    async def test_unknown_workflow_errors(self, tmp_path):
        from neurova.collaboration.neurflow.workflow_as_tool import execute_workflow_as_tool

        storage = _storage_with(_make_wf(), tmp_path)
        outcome = await execute_workflow_as_tool("ghost", {}, storage=storage)
        assert outcome["success"] is False
        assert "ghost" in (outcome.get("error") or "")

    @pytest.mark.asyncio
    async def test_required_field_missing_rejected(self, tmp_path):
        """必填输入缺失 → 拒绝执行（DAG 定义自带输入校验）"""
        from neurova.collaboration.neurflow.workflow_as_tool import execute_workflow_as_tool

        storage = _storage_with(_make_wf(), tmp_path)
        outcome = await execute_workflow_as_tool("wf_tool_1", {"date": "今天"}, storage=storage)
        assert outcome["success"] is False
        assert "city" in (outcome.get("error") or "")


class TestToolExecutorWiring:
    @pytest.mark.asyncio
    async def test_workflow_namespace_dispatched(self, tmp_path):
        """tool_executor.execute 对 workflow:{id} 命名空间直接分派"""
        from neurova.collaboration.neurflow.workflow_as_tool import execute_workflow_as_tool

        storage = _storage_with(_make_wf(), tmp_path)
        with patch(
            "neurova.collaboration.neurflow.workflow_as_tool._get_workflow_tool_storage",
            return_value=storage,
        ):
            from neurova.tool_executor import ToolExecutor

            agent_stub = MagicMock()
            agent_stub._skill_registry = None
            agent_stub.tool_router = None
            executor = ToolExecutor(agent_stub)
            executor._tool_engine = None

            result = await executor._execute_tool_core("workflow:wf_tool_1", {"city": "北京"})
        result_dict, success, source = result
        assert success is True, result_dict
        assert source == "workflow_tool"
