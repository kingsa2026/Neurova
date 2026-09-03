"""
UnifiedToolRegistry 单元测试

测试覆盖：
1. 内置工具注册（自动同步到 Router 和 Engine）
2. 批量注册
3. 直接注册到 Engine
4. 延迟加载子模块（CapabilityGraph、CLIExecutor、ToolLogger）
5. 执行并记录日志
"""

import unittest
import asyncio
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from neurova.tool_layers.unified_registry import UnifiedToolRegistry
from neurova.tool_layers.schemas import ToolSchema, ToolSource
from neurova.execution_engine.tool_engine import ToolDefinition, ToolParameter


class TestUnifiedToolRegistryInit(unittest.TestCase):
    """测试 UnifiedToolRegistry 初始化"""
    
    def test_init_default(self):
        registry = UnifiedToolRegistry()
        self.assertIsNone(registry.tool_router)
        self.assertIsNone(registry.tool_engine)
        self.assertIsNone(registry._capability_graph)
        self.assertIsNone(registry._cli_executor)
        self.assertIsNone(registry._tool_logger)
    
    def test_init_with_router_and_engine(self):
        mock_router = Mock()
        mock_engine = Mock()
        
        registry = UnifiedToolRegistry(
            tool_router=mock_router,
            tool_engine=mock_engine
        )
        
        self.assertEqual(registry.tool_router, mock_router)
        self.assertEqual(registry.tool_engine, mock_engine)
        mock_router.set_execution_engine.assert_called_once_with(mock_engine)


class TestBuiltinToolRegistration(unittest.TestCase):
    """测试内置工具注册（同步到 Router 和 Engine）"""
    
    def setUp(self):
        self.mock_router = Mock()
        self.mock_engine = Mock()
        self.registry = UnifiedToolRegistry(
            tool_router=self.mock_router,
            tool_engine=self.mock_engine
        )
    
    def test_register_builtin_to_both(self):
        def test_func(x):
            return x * 2
        
        self.registry.register_builtin(
            "double", test_func,
            category="math",
            description="Double a number",
            parameters=[{"name": "x", "type": "number", "required": True}]
        )
        
        # 检查 Router 注册
        self.mock_router.register_builtin.assert_called_once_with("double", test_func)
        
        # 检查 Engine 注册
        self.mock_engine.register_tool.assert_called_once()
        call_args = self.mock_engine.register_tool.call_args
        tool_def = call_args[0][0]
        handler = call_args[0][1]
        
        self.assertEqual(tool_def.id, "builtin:double")
        self.assertEqual(tool_def.name, "double")
        self.assertEqual(tool_def.description, "Double a number")
        self.assertEqual(tool_def.category, "math")
        self.assertEqual(handler, test_func)
    
    def test_register_builtin_without_engine(self):
        registry = UnifiedToolRegistry(tool_router=self.mock_router)
        
        def test_func():
            return "result"
        
        registry.register_builtin("test", test_func)
        
        # 只应该注册到 Router
        self.mock_router.register_builtin.assert_called_once_with("test", test_func)
    
    def test_register_builtin_without_router(self):
        registry = UnifiedToolRegistry(tool_engine=self.mock_engine)
        
        def test_func():
            return "result"
        
        registry.register_builtin("test", test_func)
        
        # 只应该注册到 Engine
        self.mock_engine.register_tool.assert_called_once()
    
    def test_register_builtin_batch(self):
        tools = {
            "add": lambda x, y: x + y,
            "multiply": lambda x, y: x * y,
        }
        
        self.registry.register_builtin_batch(tools)
        
        # 检查 Router 批量注册
        self.mock_router.register_builtin_batch.assert_called_once_with(tools)
        
        # 检查 Engine 批量注册
        self.assertEqual(self.mock_engine.register_tool.call_count, 2)


class TestRegisterToEngine(unittest.TestCase):
    """测试直接注册到 Engine"""
    
    def setUp(self):
        self.mock_router = Mock()
        self.mock_engine = Mock()
        self.registry = UnifiedToolRegistry(
            tool_router=self.mock_router,
            tool_engine=self.mock_engine
        )
    
    def test_register_to_engine(self):
        definition = ToolDefinition(
            id="custom:tool",
            name="custom_tool",
            description="Custom tool",
            parameters=[]
        )
        handler = lambda: "result"
        
        self.registry.register_to_engine(definition, handler, version="2.0.0")
        
        self.mock_engine.register_tool.assert_called_once_with(
            definition, handler, version="2.0.0"
        )


class TestLazyLoadedSubModules(unittest.TestCase):
    """测试延迟加载子模块"""
    
    def setUp(self):
        self.registry = UnifiedToolRegistry()
    
    def test_get_capability_graph(self):
        with patch('neurova.tool_layers.capability_graph.ToolCapabilityGraph') as MockGraph:
            mock_graph = Mock()
            MockGraph.return_value = mock_graph
            
            graph = self.registry.get_capability_graph()
            
            self.assertEqual(graph, mock_graph)
            self.assertEqual(self.registry._capability_graph, mock_graph)
            
            # 再次调用应该返回缓存的实例
            graph2 = self.registry.get_capability_graph()
            self.assertEqual(graph2, mock_graph)
            MockGraph.assert_called_once()
    
    def test_get_cli_executor(self):
        with patch('neurova.tool_layers.cli_tool.CLIToolExecutor') as MockExecutor:
            mock_executor = Mock()
            MockExecutor.return_value = mock_executor
            
            executor = self.registry.get_cli_executor()
            
            self.assertEqual(executor, mock_executor)
            self.assertEqual(self.registry._cli_executor, mock_executor)
            
            # 再次调用应该返回缓存的实例
            executor2 = self.registry.get_cli_executor()
            self.assertEqual(executor2, mock_executor)
            MockExecutor.assert_called_once()
    
    def test_get_tool_logger(self):
        with patch('neurova.tool_layers.tool_logger.ToolExecutionLogger') as MockLogger:
            mock_logger = Mock()
            MockLogger.return_value = mock_logger
            
            logger = self.registry.get_tool_logger()
            
            self.assertEqual(logger, mock_logger)
            self.assertEqual(self.registry._tool_logger, mock_logger)
            
            # 再次调用应该返回缓存的实例
            logger2 = self.registry.get_tool_logger()
            self.assertEqual(logger2, mock_logger)
            MockLogger.assert_called_once()


class TestExecuteAndLog(unittest.TestCase):
    """测试执行并记录日志"""
    
    def setUp(self):
        self.mock_router = Mock()
        self.registry = UnifiedToolRegistry(tool_router=self.mock_router)
    
    def test_execute_and_log_success(self):
        mock_result = Mock()
        mock_result.success = True
        mock_result.result = "test_result"
        mock_result.error = None
        
        self.mock_router.execute = AsyncMock(return_value=mock_result)
        
        async def execute():
            return await self.registry.execute_and_log(
                "test_tool", {"param": "value"}, "agent1", "user1"
            )
        
        result = asyncio.run(execute())
        
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "test_result")
        self.assertIsNone(result["error"])
        self.assertIn("latency_ms", result)
        
        # 检查 Router 调用
        self.mock_router.execute.assert_called_once_with(
            "test_tool", {"param": "value"}, "agent1", "user1"
        )
    
    def test_execute_and_log_failure(self):
        mock_result = Mock()
        mock_result.success = False
        mock_result.result = None
        mock_result.error = "Tool execution failed"
        
        self.mock_router.execute = AsyncMock(return_value=mock_result)
        
        async def execute():
            return await self.registry.execute_and_log(
                "test_tool", {}, "agent1", "user1"
            )
        
        result = asyncio.run(execute())
        
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Tool execution failed")
    
    def test_execute_and_log_exception(self):
        self.mock_router.execute = AsyncMock(side_effect=Exception("Unexpected error"))
        
        async def execute():
            return await self.registry.execute_and_log(
                "test_tool", {}, "agent1", "user1"
            )
        
        result = asyncio.run(execute())
        
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "Unexpected error")
    
    def test_execute_and_log_no_router(self):
        registry = UnifiedToolRegistry()
        
        async def execute():
            return await registry.execute_and_log(
                "test_tool", {}, "agent1", "user1"
            )
        
        result = asyncio.run(execute())
        
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "ToolRouter 未初始化")
    
    def test_execute_and_log_with_logger(self):
        mock_logger = Mock()
        self.registry._tool_logger = mock_logger
        
        mock_result = Mock()
        mock_result.success = True
        mock_result.result = "result"
        mock_result.error = None
        
        self.mock_router.execute = AsyncMock(return_value=mock_result)
        
        async def execute():
            return await self.registry.execute_and_log(
                "test_tool", {"x": 1}, "agent1", "user1"
            )
        
        result = asyncio.run(execute())
        
        # 检查日志记录
        mock_logger.log.assert_called_once()
        log_entry = mock_logger.log.call_args[0][0]
        self.assertEqual(log_entry["tool_name"], "test_tool")
        self.assertTrue(log_entry["success"])
        self.assertEqual(log_entry["agent_id"], "agent1")
        self.assertEqual(log_entry["user_id"], "user1")


class TestUnifiedToolRegistryExtended(unittest.TestCase):
    """扩展的 UnifiedToolRegistry 测试"""
    
    def test_register_builtin_parameters_conversion(self):
        """测试参数定义转换"""
        mock_engine = Mock()
        registry = UnifiedToolRegistry(tool_engine=mock_engine)
        
        def test_func(a, b):
            return a + b
        
        parameters = [
            {"name": "a", "type": "integer", "required": True, "description": "First number"},
            {"name": "b", "type": "integer", "required": True, "description": "Second number"},
        ]
        
        registry.register_builtin(
            "add", test_func,
            parameters=parameters
        )
        
        # 检查 Engine 注册的参数
        call_args = mock_engine.register_tool.call_args
        tool_def = call_args[0][0]
        
        self.assertEqual(len(tool_def.parameters), 2)
        self.assertEqual(tool_def.parameters[0].name, "a")
        self.assertEqual(tool_def.parameters[0].type, "integer")
        self.assertTrue(tool_def.parameters[0].required)
    
    def test_register_builtin_batch_to_engine(self):
        """测试批量注册到 Engine"""
        mock_engine = Mock()
        registry = UnifiedToolRegistry(tool_engine=mock_engine)
        
        tools = {
            "tool1": lambda: "result1",
            "tool2": lambda: "result2",
        }
        
        registry.register_builtin_batch(tools)
        
        # 检查 Engine 注册次数
        self.assertEqual(mock_engine.register_tool.call_count, 2)
        
        # 检查工具定义
        calls = mock_engine.register_tool.call_args_list
        tool_ids = [call[0][0].id for call in calls]
        self.assertIn("builtin:tool1", tool_ids)
        self.assertIn("builtin:tool2", tool_ids)


if __name__ == "__main__":
    unittest.main(verbosity=2)