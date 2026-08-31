"""蜂群内置工具（spawn_subagent/subagent_status/list_agents）单元测试"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.builtin_tools import BuiltinToolRegistry, _BUILTIN_SCHEMAS
from neurova.tool_executor import ToolExecutor


@pytest.fixture
def executor():
    agent = MagicMock()
    agent.current_session_id = "sess-abc"  # P3-c 收窄：spawn 经显式 property 读取
    return ToolExecutor(agent), agent


class TestSwarmToolSchemas:
    """schema 注册即对 LLM 可见"""

    def test_swarm_schemas_registered(self):
        for name in ("spawn_subagent", "subagent_status", "list_agents"):
            assert name in _BUILTIN_SCHEMAS, f"{name} 未注册 schema"
            assert "description" in _BUILTIN_SCHEMAS[name]

    def test_registry_exposes_openai_format(self):
        registry = BuiltinToolRegistry.__new__(BuiltinToolRegistry)  # 跳过 __init__ 的重依赖
        registry._tools = {}
        from neurova.builtin_tools import BuiltinTool

        for name, spec in _BUILTIN_SCHEMAS.items():
            registry._tools[name] = BuiltinTool(
                name=name, description=spec["description"], parameters=spec["parameters"]
            )
        openai_tools = registry.get_openai_tools()
        names = {t["function"]["name"] for t in openai_tools}
        assert {"spawn_subagent", "subagent_status", "list_agents"} <= names


class TestSpawnSubagentTool:
    @pytest.mark.asyncio
    async def test_spawn_passes_session_and_initiator(self, executor):
        exe, agent = executor
        fake_swarm = MagicMock()
        fake_swarm.spawn = AsyncMock(return_value={"status": "completed", "report": "ok"})
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=fake_swarm):
            result = await exe._execute_spawn_subagent({"task": "子任务", "agent_id": "a1"})

        assert result["report"] == "ok"
        fake_swarm.spawn.assert_awaited_once()
        kwargs = fake_swarm.spawn.call_args.kwargs
        assert kwargs["task"] == "子任务"
        assert kwargs["agent_id"] == "a1"
        assert kwargs["session_id"] == "sess-abc"
        assert kwargs["initiator_agent"] is agent
        assert kwargs["origin"] == "chat"

    @pytest.mark.asyncio
    async def test_spawn_requires_task(self, executor):
        exe, _ = executor
        result = await exe._execute_spawn_subagent({})
        assert "error" in result

    @pytest.mark.asyncio
    async def test_background_flag_passthrough(self, executor):
        exe, _ = executor
        fake_swarm = MagicMock()
        fake_swarm.spawn = AsyncMock(return_value={"subagent_id": "s1", "background": True})
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=fake_swarm):
            await exe._execute_spawn_subagent({"task": "t", "background": True})
        assert fake_swarm.spawn.call_args.kwargs["background"] is True


class TestSubagentStatusTool:
    @pytest.mark.asyncio
    async def test_status_query(self, executor):
        exe, _ = executor
        fake_swarm = MagicMock()
        fake_swarm.status = MagicMock(return_value={"status": "completed", "report": "done"})
        with patch("neurova.agent.swarm.get_swarm_manager", return_value=fake_swarm):
            result = await exe._execute_subagent_status({"subagent_id": "swarm_x"})
        assert result["report"] == "done"
        fake_swarm.status.assert_called_once_with("swarm_x")

    @pytest.mark.asyncio
    async def test_status_requires_id(self, executor):
        exe, _ = executor
        assert "error" in await exe._execute_subagent_status({})


class TestListAgentsTool:
    @pytest.mark.asyncio
    async def test_lists_registered_agents(self, executor):
        exe, _ = executor
        a1, a2 = MagicMock(), MagicMock()
        a1.config.name = "研究员"
        a1.config.description = "负责调研"
        a1.config.llm_config.model = "gpt-4"
        a2.config.name = "写手"
        a2.config.description = "负责写作"
        a2.config.llm_config.model = "claude-3"

        with patch("neurova.api.endpoints.get_app_state", return_value={"agents": {"a1": a1, "a2": a2, "dead": None}}):
            result = await exe._execute_list_agents({})

        assert result["count"] == 2
        ids = {a["agent_id"] for a in result["agents"]}
        assert ids == {"a1", "a2"}
        by_id = {a["agent_id"]: a for a in result["agents"]}
        assert by_id["a1"]["name"] == "研究员"
        assert by_id["a1"]["model"] == "gpt-4"

    @pytest.mark.asyncio
    async def test_registry_unavailable(self, executor):
        exe, _ = executor
        with patch("neurova.api.endpoints.get_app_state", side_effect=ImportError("no state")):
            result = await exe._execute_list_agents({})
        assert "error" in result
