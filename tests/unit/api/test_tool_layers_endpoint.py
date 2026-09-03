"""
TDD RED-1：暴露 agent → 工具层调用链阻断问题

验证 API 端点 /v1/tool-layers/tools/execute 能通过 agent.tool_executor.execute()
成功执行内置工具，而非回退到 "(simulated)" 假成功。

根因（P0-3）：
    neurova/api/endpoints/tool_layers.py:193 调用
        agent.tool_executor.execute(body.tool_name, body.arguments)
    但 ToolExecutor 类只有 _execute_single_tool / execute_text_tool_calls 等
    私有/特定方法，缺少公开的 execute() 入口 → AttributeError 被外层 except 吞没
    → 端点返回 code:0 + "(simulated)" 假成功（P0-8）。
"""

import pytest
from unittest.mock import Mock, AsyncMock, patch


class TestToolExecutorPublicInterface:
    """测试 ToolExecutor 公开接口 — 供 API 端点调用"""

    def _create_executor(self):
        from neurova.tool_executor import ToolExecutor

        agent = Mock()
        agent._skill_registry = Mock()
        agent.tool_router = Mock()
        agent.tool_memory = Mock()
        agent.tool_lifecycle = Mock()
        agent.skill_packer = Mock()
        agent.config = Mock()
        agent.memory_manager = Mock()
        agent.memory_manager._emotion_analyzer = Mock()
        return ToolExecutor(agent)

    def test_execute_method_exists(self):
        """ToolExecutor 应公开 execute() 方法

        API 端点 tool_layers.py:193 调用 agent.tool_executor.execute(name, args)
        缺少此方法 → AttributeError → 端点回退到 simulated 假成功
        """
        executor = self._create_executor()
        assert hasattr(executor, "execute"), (
            "ToolExecutor 缺少 execute() 方法 — "
            "API 端点 tool_layers.py:193 调用会 AttributeError 被吞没"
        )
        assert callable(executor.execute), "execute 不是可调用方法"

    @pytest.mark.asyncio
    async def test_execute_runs_builtin_tool_without_simulated(self):
        """execute() 应执行内置工具，返回真实结果（非 simulated 字符串）"""
        executor = self._create_executor()

        # memory_search 是内置工具，应通过公开 execute() 入口执行
        result = await executor.execute("memory_search", {"query": "测试查询"})

        assert isinstance(result, dict), "execute() 应返回 dict"
        result_str = str(result).lower()
        assert "simulated" not in result_str, (
            f"execute() 不应返回 simulated 假结果，实际: {result}"
        )


class TestExecuteToolEndpoint:
    """测试 API 端点 /tools/execute 行为"""

    @pytest.mark.asyncio
    async def test_endpoint_returns_real_result_not_simulated(self):
        """端点应返回真实工具结果，而非 (simulated) 假成功

        场景：ToolEngine 为空（ValueError）→ 回退到 agent.tool_executor.execute()
        期望：返回 code:0 + 真实结果
        当前：agent.tool_executor.execute() 不存在 → AttributeError → 返回 simulated
        """
        from neurova.api.endpoints import tool_layers
        from neurova.api.endpoints.tool_layers import (
            execute_tool,
            ToolExecuteRequest,
        )

        # 准备：真实的 ToolExecutor（带 mock agent）
        from neurova.tool_executor import ToolExecutor

        mock_agent = Mock()
        mock_agent._skill_registry = Mock()
        mock_agent.tool_router = Mock()
        mock_agent.tool_memory = Mock()
        mock_agent.tool_lifecycle = Mock()
        mock_agent.skill_packer = Mock()
        mock_agent.config = Mock()
        mock_agent.memory_manager = Mock()
        mock_agent.memory_manager._emotion_analyzer = Mock()
        # memory_search 内部调用 memory_manager.recall()，需返回可迭代空列表
        mock_agent.memory_manager.recall = Mock(return_value=[])
        real_executor = ToolExecutor(mock_agent)

        # mock get_tool_engine 返回会抛 ValueError 的空 engine（模拟空 ToolEngine）
        empty_engine = Mock()
        empty_engine.execute_with_safeguards = AsyncMock(
            side_effect=ValueError("工具未注册: memory_search")
        )
        empty_engine.list_tools = Mock(return_value=[])

        # mock get_agent_instance 返回带真实 tool_executor 的 agent
        mock_agent_with_executor = Mock()
        mock_agent_with_executor.tool_executor = real_executor

        with patch.object(tool_layers, "get_tool_engine", return_value=empty_engine), \
             patch("neurova.api.endpoints.get_agent_instance", return_value=mock_agent_with_executor):

            body = ToolExecuteRequest(
                tool_name="memory_search",
                arguments={"query": "测试"},
                timeout=5,
            )
            response = await execute_tool(body)

        # 断言：返回 code:0 且 result 不是 simulated 字符串
        assert response["code"] == 0, f"应成功，实际 code: {response['code']}"
        result = response["data"]["result"]
        result_str = str(result).lower()
        assert "simulated" not in result_str, (
            f"端点不应返回 simulated 假成功，实际: {result}"
        )


class TestExecuteToolEndpointNoSimulatedFallback:
    """测试 API 端点 /tools/execute 不返回假成功（P0-8）"""

    @pytest.mark.asyncio
    async def test_endpoint_returns_error_for_unknown_tool(self):
        """未知工具应返回错误码，而非 (simulated) 假成功

        场景：ToolEngine 无此工具 → agent.tool_executor.execute() 返回 {error: ...}
        期望：端点应传播错误，返回非 0 错误码
        当前：端点吞没所有失败，返回 code:0 + "(simulated)" → 前端误显示成功
        """
        from neurova.api.endpoints import tool_layers
        from neurova.api.endpoints.tool_layers import (
            execute_tool,
            ToolExecuteRequest,
        )
        from neurova.tool_executor import ToolExecutor

        # 准备：真实 ToolExecutor（带 mock agent，无 skill/router）
        mock_agent = Mock()
        mock_agent._skill_registry = Mock()
        mock_agent._skill_registry.has_skill = Mock(return_value=False)
        mock_agent.tool_router = None  # 无路由器 → execute() 返回 {error}
        mock_agent.tool_memory = Mock()
        mock_agent.tool_lifecycle = Mock()
        mock_agent.skill_packer = Mock()
        mock_agent.config = Mock()
        mock_agent.memory_manager = Mock()
        mock_agent.memory_manager._emotion_analyzer = Mock()
        real_executor = ToolExecutor(mock_agent)

        empty_engine = Mock()
        empty_engine.execute_with_safeguards = AsyncMock(
            side_effect=ValueError("工具未注册: nonexistent_tool_xyz")
        )

        mock_agent_with_executor = Mock()
        mock_agent_with_executor.tool_executor = real_executor

        with patch.object(tool_layers, "get_tool_engine", return_value=empty_engine), \
             patch("neurova.api.endpoints.get_agent_instance", return_value=mock_agent_with_executor):

            body = ToolExecuteRequest(
                tool_name="nonexistent_tool_xyz",
                arguments={},
                timeout=5,
            )
            response = await execute_tool(body)

        # 断言：不应返回 code:0 + simulated
        result_str = str(response.get("data", {}).get("result", "")).lower()
        assert "simulated" not in result_str, (
            f"未知工具不应返回 simulated 假成功，实际: {response}"
        )
        # 当工具执行返回 error 字段时，端点应传播错误（非 0 错误码）
        result = response.get("data", {}).get("result", {})
        if isinstance(result, dict) and "error" in result:
            assert response.get("code") != 0, (
                f"工具执行失败（result 含 error 字段）应返回非 0 错误码，"
                f"实际 code: {response.get('code')}, response: {response}"
            )


class TestListAllToolsAggregation:
    """测试 /tools 端点聚合多源工具（P0-5）"""

    @pytest.mark.asyncio
    async def test_list_all_tools_includes_builtin_tools(self):
        """list_all_tools 应包含 BuiltinToolRegistry 的内置工具

        场景：ToolEngine 为空（list_tools 返回 []），但 agent._builtin_tools
              有 15 个内置工具（memory_search / file_read 等）
        期望：端点返回非空列表，包含 memory_search
        当前：端点只从 ToolEngine 取工具 → 永远返回 []
        """
        from neurova.api.endpoints import tool_layers
        from neurova.api.endpoints.tool_layers import list_all_tools
        from neurova.builtin_tools import BuiltinToolRegistry

        # 准备：空 ToolEngine + 真实 BuiltinToolRegistry
        empty_engine = Mock()
        empty_engine.list_tools = Mock(return_value=[])
        empty_engine.discover_public_tools = Mock(return_value=Mock(tools=[]))

        mock_agent = Mock()
        mock_agent._builtin_tools = BuiltinToolRegistry()

        with patch.object(tool_layers, "get_tool_engine", return_value=empty_engine), \
             patch("neurova.api.endpoints.get_agent_instance", return_value=mock_agent):
            tools = await list_all_tools(source=None)

        # 断言：应包含内置工具（非空）
        assert len(tools) > 0, (
            f"list_all_tools 应包含 BuiltinToolRegistry 的内置工具，"
            f"实际返回空列表（ToolEngine 为空时未聚合 agent._builtin_tools）"
        )
        tool_names = [t.tool_id for t in tools]
        assert "memory_search" in tool_names, (
            f"应包含 memory_search 内置工具，实际工具: {tool_names}"
        )
