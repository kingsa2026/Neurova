"""
测试 ToolRouter 签名匹配

验证 BaseAgentLoop 和 ToolRouter 的接口兼容性。
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from types import SimpleNamespace

# 确保可以导入 ToolRouter
from neurova.tool_layers.tool_router import ToolRouter, ToolResult


class TestToolRouterSignature:
    """测试 ToolRouter.execute 方法签名"""
    
    def test_execute_accepts_agent_id_and_user_id(self):
        """验证 execute 方法接受 agent_id 和 user_id 参数"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        # 检查 execute 方法签名
        import inspect
        sig = inspect.signature(router.execute)
        params = list(sig.parameters.keys())
        
        # 应该包含 tool_name, params, agent_id, user_id
        assert "tool_name" in params, "缺少 tool_name 参数"
        assert "params" in params, "缺少 params 参数"
        assert "agent_id" in params, "缺少 agent_id 参数"
        assert "user_id" in params, "缺少 user_id 参数"
    
    @pytest.mark.asyncio
    async def test_execute_with_all_params(self):
        """验证 execute 可以传递所有参数"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        # 注册一个 mock 工具
        mock_tool = Mock()
        mock_tool.execute = AsyncMock(return_value={"success": True})
        mock_tool.is_mcp = False
        mock_tool.is_skill = False
        mock_tool.name = "test_tool"
        
        router.register_builtin("test_tool", mock_tool)
        
        # 应该可以传递 agent_id 和 user_id 而不报错
        result = await router.execute(
            tool_name="test_tool",
            params={"key": "value"},
            agent_id="agent_123",
            user_id="user_456",
        )
        
        assert result is not None
    
    @pytest.mark.asyncio
    async def test_execute_backward_compatible(self):
        """验证 execute 向后兼容（不传 agent_id/user_id 也可）"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        mock_tool = Mock()
        mock_tool.execute = AsyncMock(return_value={"result": "ok"})
        mock_tool.is_mcp = False
        mock_tool.is_skill = False
        mock_tool.name = "legacy_tool"
        
        router.register_builtin("legacy_tool", mock_tool)
        
        # 不传 agent_id 和 user_id 也应正常工作
        result = await router.execute(
            tool_name="legacy_tool",
            params={},
        )
        
        assert result is not None


class TestBaseAgentLoopToolRouterCall:
    """测试 BaseAgentLoop 调用 ToolRouter 的方式"""
    
    def test_base_loop_calls_with_correct_params(self):
        """验证 BaseAgentLoop 调用时传递正确的参数"""
        from neurova.agent.loops.base import BaseAgentLoop
        
        # 检查源码中调用 ToolRouter 的地方
        import inspect
        source = inspect.getsource(BaseAgentLoop)
        
        # 应该调用 execute 并传递 tool_name, params, agent_id, user_id
        assert "tool_router.execute(" in source, "未找到 tool_router.execute 调用"
        assert "agent_id=" in source, "缺少 agent_id 参数"
        assert "user_id=" in source, "缺少 user_id 参数"


class TestToolRouterIntegration:
    """测试 ToolRouter 与 BaseAgentLoop 集成"""
    
    @pytest.mark.asyncio
    async def test_full_integration_flow(self):
        """验证完整的工具路由流程"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        # 创建 mock 工具
        executed_params = []
        
        async def mock_execute(params):
            executed_params.append(params)
            return {"executed": True, "params": params}
        
        mock_tool = Mock()
        mock_tool.execute = mock_execute
        mock_tool.is_mcp = False
        mock_tool.is_skill = False
        mock_tool.name = "test_tool"
        
        router.register_builtin("test_tool", mock_tool)
        
        # 模拟 BaseAgentLoop 的调用方式
        result = await router.execute(
            tool_name="test_tool",
            params={"query": "test"},
            agent_id="agent_001",
            user_id="user_002",
        )
        
        # 现在返回 ToolResult 对象
        assert result.success is True
        assert result.result["executed"] is True
        assert executed_params[0]["query"] == "test"
    
    @pytest.mark.asyncio
    async def test_tool_not_found_error(self):
        """验证工具不存在时返回失败的 ToolResult"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        # 现在返回 ToolResult 而不是抛出异常
        result = await router.execute(
            tool_name="nonexistent_tool",
            params={},
            agent_id="agent_001",
            user_id="user_002",
        )
        
        assert result.success is False
        assert "nonexistent_tool" in result.error


class TestToolRouterResultFormat:
    """测试 ToolRouter 返回格式"""
    
    @pytest.mark.asyncio
    async def test_result_has_success_attribute(self):
        """验证结果有 success 属性（与 BaseAgentLoop 兼容）"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        # 内置工具返回字典
        mock_tool = Mock()
        mock_tool.execute = AsyncMock(return_value={"data": "test_result"})
        mock_tool.is_mcp = False
        mock_tool.is_skill = False
        mock_tool.name = "dict_tool"
        
        router.register_builtin("dict_tool", mock_tool)
        
        result = await router.execute(
            tool_name="dict_tool",
            params={},
            agent_id="agent_001",
            user_id="user_002",
        )
        
        # BaseAgentLoop 期望结果有 success 和 result 属性
        assert hasattr(result, 'success'), "结果应有 success 属性"
        assert hasattr(result, 'result'), "结果应有 result 属性"
        assert result.success is True
        assert result.result == {"data": "test_result"}
    
    @pytest.mark.asyncio
    async def test_result_error_handling(self):
        """验证错误情况返回正确的 ToolResult"""
        from neurova.tool_layers.tool_router import ToolRouter
        
        router = ToolRouter()
        
        # 不存在的工具
        result = await router.execute(
            tool_name="nonexistent",
            params={},
            agent_id="agent_001",
            user_id="user_002",
        )
        
        assert result.success is False
        assert result.error is not None
        assert "nonexistent" in result.error
