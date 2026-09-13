"""R3-3 CUA 双层 MCP 导出（CUA Phase 3 立项 §2）

红线：默认关（NEUROVA_CUA_MCP_EXPORT 未设 → 不导出、按名调用也拒）；导出即
受治理（工具面路由到 ToolExecutor 单一实现，走同一 governance/审计/ActionResult，
与内部直调逐字段等价，不复制实现）。

验收：
1. 默认关：list_tools 无 computer_*；call_tool("computer_screenshot") → isError
2. 开启：list_tools 含 computer_* 全量 + run_computer_task
3. 工具面 call_tool 路由到 ToolExecutor._execute_single_tool（单一实现源）
4. 工具面返回值与内部执行结果逐字段等价（不加工）
5. agent 面 run_computer_task → agent.chat(goal) 一轮
6. 无 agent_ref 时导出项不出现（无法执行）
"""

import pytest

from neurova.tool_layers.mcp_server import NeurovaMCPServer


class FakeAgent:
    def __init__(self):
        self.chat_calls = []

    async def chat(self, user_input, **kw):
        self.chat_calls.append((user_input, kw))
        return {"reply": f"done: {user_input}", "success": True}


@pytest.fixture
def enabled(monkeypatch):
    monkeypatch.setenv("NEUROVA_CUA_MCP_EXPORT", "1")


@pytest.mark.asyncio
class TestDisabledByDefault:
    async def test_list_tools_no_computer(self):
        srv = NeurovaMCPServer(agent_ref=FakeAgent())
        names = [t["name"] for t in srv.list_tools()]
        assert not any(n.startswith("computer_") for n in names)
        assert "run_computer_task" not in names

    async def test_call_computer_rejected(self):
        srv = NeurovaMCPServer(agent_ref=FakeAgent())
        out = await srv.call_tool("computer_screenshot", {})
        assert out.get("isError") is True
        assert "未启用" in out.get("error", "") or "导出" in out.get("error", "")


@pytest.mark.asyncio
class TestEnabled:
    async def test_list_tools_includes_computer(self, enabled):
        srv = NeurovaMCPServer(agent_ref=FakeAgent())
        names = [t["name"] for t in srv.list_tools()]
        assert "computer_screenshot" in names
        assert "computer_click" in names
        assert "run_computer_task" in names

    async def test_no_agent_ref_no_export(self, enabled):
        srv = NeurovaMCPServer(agent_ref=None)
        names = [t["name"] for t in srv.list_tools()]
        assert not any(n.startswith("computer_") for n in names)

    async def test_tool_face_routes_to_executor_single_source(self, enabled, monkeypatch):
        from neurova.tool_executor import ToolExecutor

        sentinel = {"success": True, "screen": {"width": 1920}, "action_result": {"effect": "confirmed"}}
        captured = {}

        async def fake_exec(self, tool_name, params, skip_governance=False):
            captured["name"] = tool_name
            captured["params"] = params
            captured["skip_governance"] = skip_governance
            return sentinel

        monkeypatch.setattr(ToolExecutor, "_execute_single_tool", fake_exec)
        srv = NeurovaMCPServer(agent_ref=FakeAgent())
        out = await srv.call_tool("computer_screenshot", {"region": "x"})
        # 逐字段等价：返回的就是 ToolExecutor 的原始结果（不加工）
        assert out == sentinel
        assert captured["name"] == "computer_screenshot"
        # 治理预检不得被导出面绕过
        assert captured["skip_governance"] is False

    async def test_agent_face_runs_one_turn(self, enabled):
        agent = FakeAgent()
        srv = NeurovaMCPServer(agent_ref=agent)
        out = await srv.call_tool("run_computer_task", {"goal": "打开记事本"})
        assert agent.chat_calls and agent.chat_calls[0][0] == "打开记事本"
        assert out.get("success") is True
        assert "done" in str(out.get("result"))

    async def test_agent_face_missing_goal(self, enabled):
        srv = NeurovaMCPServer(agent_ref=FakeAgent())
        out = await srv.call_tool("run_computer_task", {})
        assert out.get("isError") is True
