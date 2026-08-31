"""
遗留③a — tool_executor 接入 execute_workflow_agent 测试

契约（ToolExecutor）：
- 新工具分支 run_workflow_agent：params={agent_id, inputs?/message?}
- 成功：{"success": True, "result": <outputs>, "execution_id": ...}
- 桥接失败信封转 {"error": ...}（AGENT_NOT_FOUND / NOT_A_WORKFLOW_AGENT /
  WORKFLOW_NOT_PUBLISHED / WORKFLOW_AGENT_DEPS_NOT_CONFIGURED）
- deps 经 set_workflow_agent_deps 注入（工具分支用全局 provider）
- 治理预检照常走（分支位于 precheck 之后）

TDD：先红后绿。MagicMock agent_ref 构造 ToolExecutor。
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from neurova.tool_executor import ToolExecutor
from neurova.agent import workflow_agent as wa
from neurova.collaboration.neurflow.models import AgentInfo


@pytest.fixture(autouse=True)
def _reset_deps():
    """用例间清 deps provider + mock 治理预检通过。"""
    saved = wa._deps_provider
    wa._deps_provider = None
    yield
    wa._deps_provider = saved


def _make_executor(monkeypatch):
    te = ToolExecutor(agent_ref=MagicMock())
    # 治理预检放行（本测试聚焦分支逻辑）
    monkeypatch.setattr(te, "_governance_precheck", AsyncMock(return_value=None))
    return te


def _ok_instance():
    inst = MagicMock()
    inst.status.value = "completed"
    inst.outputs = {"reply": "done"}
    inst.id = "exec_wa_1"
    inst.error = None
    return inst


class TestRunWorkflowAgentTool:
    @pytest.mark.asyncio
    async def test_success_envelope(self, monkeypatch):
        agent = AgentInfo(
            agent_id="wf_agent_wf_1", name="a", role="workflow",
            metadata={"source_type": "workflow", "workflow_id": "wf_1"},
        )
        deps = {
            "load_agent": MagicMock(return_value=agent),
            "load_published_workflow": MagicMock(return_value=MagicMock()),
            "run_workflow": AsyncMock(return_value=_ok_instance()),
        }
        wa.set_workflow_agent_deps(lambda: deps)

        te = _make_executor(monkeypatch)
        result = await te._execute_single_tool(
            "run_workflow_agent", {"agent_id": "wf_agent_wf_1", "message": "hi"}
        )
        assert result.get("success") is True
        assert result["result"] == {"reply": "done"}
        assert result["execution_id"] == "exec_wa_1"

    @pytest.mark.asyncio
    async def test_message_wrapped_into_inputs(self, monkeypatch):
        agent = AgentInfo(
            agent_id="wf_agent_wf_1", name="a", role="workflow",
            metadata={"source_type": "workflow", "workflow_id": "wf_1"},
        )
        captured = {}

        async def run_workflow(workflow, inputs):
            captured["inputs"] = inputs
            return _ok_instance()

        deps = {
            "load_agent": MagicMock(return_value=agent),
            "load_published_workflow": MagicMock(return_value=MagicMock()),
            "run_workflow": run_workflow,
        }
        wa.set_workflow_agent_deps(lambda: deps)

        te = _make_executor(monkeypatch)
        await te._execute_single_tool(
            "run_workflow_agent", {"agent_id": "wf_agent_wf_1", "message": "hello"}
        )
        assert captured["inputs"] == {"message": "hello"}

    @pytest.mark.asyncio
    async def test_agent_not_found_becomes_error(self, monkeypatch):
        deps = {
            "load_agent": MagicMock(return_value=None),
            "load_published_workflow": MagicMock(),
            "run_workflow": AsyncMock(),
        }
        wa.set_workflow_agent_deps(lambda: deps)

        te = _make_executor(monkeypatch)
        result = await te._execute_single_tool(
            "run_workflow_agent", {"agent_id": "wf_agent_none"}
        )
        assert "error" in result
        assert "AGENT_NOT_FOUND" in result["error"]

    @pytest.mark.asyncio
    async def test_missing_agent_id_rejected(self, monkeypatch):
        te = _make_executor(monkeypatch)
        result = await te._execute_single_tool("run_workflow_agent", {})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_deps_not_configured_error(self, monkeypatch):
        te = _make_executor(monkeypatch)
        result = await te._execute_single_tool(
            "run_workflow_agent", {"agent_id": "wf_agent_x"}
        )
        assert "error" in result
        assert "WORKFLOW_AGENT_DEPS_NOT_CONFIGURED" in result["error"]