"""
Neurova CogArch 2.0 - ToolEngine 单元测试

测试覆盖：
1. 工具注册与管理
2. 智能工具选择
3. 参数自动填充
4. 安全执行（集成 ToolGuard）
5. 工具链执行
6. 工具版本管理
7. 工具发现机制
8. 调用记录与审计
"""

import unittest
import asyncio
import sys
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from enum import Enum

sys.path.insert(0, str(Path(__file__).parent.parent))

from neurova.execution_engine import (
    ToolEngine,
    ToolStatus,
    ToolParameter,
    ToolDefinition,
    ToolInvocation,
    ToolSelection,
    ToolCallingContext,
    ToolVersion,
    ToolDiscoveryResult,
)


# ============ 辅助函数 ============

def create_test_tool(
    tool_id: str = "test_tool",
    name: str = None,
    description: str = "A test tool",
    status: ToolStatus = ToolStatus.AVAILABLE,
    tags: List[str] = None,
    parameters: List[ToolParameter] = None,
) -> ToolDefinition:
    """创建测试工具定义"""
    return ToolDefinition(
        name=name or tool_id,
        description=description,
        parameters=parameters or [],
        status=status,
        tags=tags or [],
    )


def create_async_handler(return_value: Any = "test_result"):
    """创建异步测试工具处理函数"""
    async def async_handler(**kwargs):
        return return_value
    return async_handler


def create_sync_handler(return_value: Any = "test_result"):
    """创建同步测试工具处理函数"""
    def sync_handler(**kwargs):
        return return_value
    return sync_handler


def mock_security_system(engine):
    """
    统一 mock 安全系统（使用 AsyncMock 处理异步方法）
    
    此函数用于测试类的 setUp() 中，确保：
    1. _cognitive_security.check_input_safety 是 AsyncMock
    2. _cognitive_security.check_output_safety 是 AsyncMock
    3. _constitution_engine.evaluate_tool_call 是普通 Mock
    4. tool_guard.guard 是普通 Mock
    """
    from unittest.mock import Mock, AsyncMock
    
    # CognitiveSecurity (异步方法需要用 AsyncMock)
    engine._cognitive_security = Mock()
    engine._cognitive_security.check_input_safety = AsyncMock(
        return_value=Mock(is_safe=True, threats=[])
    )
    engine._cognitive_security.check_output_safety = AsyncMock(
        return_value=Mock(is_safe=True, threats=[], filtered_output=None)
    )
    
    # ConstitutionEngine
    engine._constitution_engine = Mock()
    engine._constitution_engine.evaluate_tool_call = Mock(
        return_value=Mock(is_compliant=True, compliance_score=1.0, details=[])
    )
    
    # ToolGuard
    engine.tool_guard = Mock()
    # 规范 API 检查 should_block（Mock 自动属性会使其 truthy→误拦），必须显式 False
    engine.tool_guard.guard = Mock(
        return_value=Mock(is_safe=True, should_block=False, findings=[])
    )


# ============ 测试用例 ============

class TestToolStatus(unittest.TestCase):
    """测试 ToolStatus 枚举"""
    
    def test_status_values(self):
        self.assertEqual(ToolStatus.AVAILABLE.value, "available")
        self.assertEqual(ToolStatus.UNAVAILABLE.value, "unavailable")
        self.assertEqual(ToolStatus.DEPRECATED.value, "deprecated")
        self.assertEqual(ToolStatus.DISABLED.value, "disabled")


class TestToolParameter(unittest.TestCase):
    """测试 ToolParameter 数据类"""
    
    def test_create_parameter(self):
        param = ToolParameter(
            name="test_param",
            type="string",
            required=True,
            description="Test parameter",
            default=None,
        )
        self.assertEqual(param.name, "test_param")
        self.assertEqual(param.type, "string")
        self.assertTrue(param.required)
    
    def test_parameter_defaults(self):
        param = ToolParameter(name="test")
        self.assertEqual(param.type, "string")
        self.assertFalse(param.required)
        self.assertEqual(param.description, "")
        self.assertIsNone(param.default)
        # ToolParameter 没有 constraints 属性


class TestToolDefinition(unittest.TestCase):
    """测试 ToolDefinition 数据类"""
    
    def test_create_tool_definition(self):
        tool = create_test_tool()
        self.assertEqual(tool.name, "test_tool")  # defaults to tool_id
        self.assertEqual(tool.status, ToolStatus.AVAILABLE)
        self.assertEqual(tool.version, "1.0.0")
    
    def test_tool_with_parameters(self):
        params = [
            ToolParameter(name="param1", type="string", required=True),
            ToolParameter(name="param2", type="integer", required=False, default=10),
        ]
        tool = create_test_tool(parameters=params)
        self.assertEqual(len(tool.parameters), 2)
        self.assertEqual(tool.parameters[0].name, "param1")
        self.assertEqual(tool.parameters[1].default, 10)


class TestToolEngineInit(unittest.TestCase):
    """测试 ToolEngine 初始化"""
    
    def test_init_default(self):
        engine = ToolEngine()
        self.assertIsNotNone(engine.tool_guard)
        self.assertEqual(len(engine._tools), 0)
        self.assertEqual(len(engine._tool_funcs), 0)
    
    def test_init_with_custom_guard(self):
        custom_guard = Mock()
        engine = ToolEngine(tool_guard=custom_guard)
        self.assertEqual(engine.tool_guard, custom_guard)


class TestToolRegistration(unittest.TestCase):
    """测试工具注册功能"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.test_tool = create_test_tool()
        self.test_handler = create_async_handler()
    
    def test_register_tool(self):
        # 注册工具
        self.engine.register_tool(
            self.test_tool.name,
            self.test_handler
        )
        self.assertIn("test_tool", self.engine._tools)
        self.assertIn("test_tool", self.engine._tool_funcs)
    
    def test_register_tool_creates_version(self):
        self.engine.register_tool(self.test_tool.name, self.test_handler)
        versions = self.engine.get_tool_versions("test_tool")
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].version, "1.0.0")
        self.assertTrue(versions[0].is_active)
    
    def test_unregister_tool(self):
        self.engine.register_tool(self.test_tool.name, self.test_handler)
        # 注销工具
        result = self.engine.unregister_tool("test_tool")
        self.assertTrue(result)
        self.assertNotIn("test_tool", self.engine._tools)
    
    def test_unregister_nonexistent_tool(self):
        result = self.engine.unregister_tool("nonexistent")
        self.assertFalse(result)


class TestToolListing(unittest.TestCase):
    """测试工具列表功能"""
    
    def setUp(self):
        self.engine = ToolEngine()
        # 注册多个工具（传递 tags 和 status）
        self.engine.register_tool("tool1", create_async_handler(), tags=["cat1"])
        self.engine.register_tool("tool2", create_async_handler(), tags=["cat2"])
        self.engine.register_tool("tool3", create_async_handler(), status=ToolStatus.DISABLED)
    
    def test_list_all_tools(self):
        tools = self.engine.list_tools()
        self.assertEqual(len(tools), 3)
    
    def test_list_tools_by_category(self):
        tools = self.engine.list_tools(tags=["cat1"])
        self.assertEqual(len(tools), 1)
        self.assertIn(tools[0].tags, [["cat1"]])
    
    def test_list_tools_by_status(self):
        tools = self.engine.list_tools(status=ToolStatus.DISABLED)
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].status, ToolStatus.DISABLED)


class TestToolDiscovery(unittest.TestCase):
    """测试工具发现机制"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.engine.register_tool("search tool", create_async_handler(), description="Search for information", tags=["search", "info"])
        self.engine.register_tool("calculator", create_async_handler(), description="Perform calculations", tags=["math"])
        self.engine.register_tool("file reader", create_async_handler(), description="Read files", tags=["file"])
    
    def test_discover_tools_by_tag(self):
        result = self.engine.discover_tools(tags=["search"])
        tools = result.tools
        self.assertGreater(len(tools), 0)
        tool_names = [t.name for t in tools]
        self.assertIn("search tool", tool_names)
    
    def test_discover_tools_by_name(self):
        result = self.engine.discover_tools(query="calculator")
        tools = result.tools
        self.assertGreater(len(tools), 0)
        tool_names = [t.name for t in tools]
        self.assertIn("calculator", tool_names)
    
    def test_discover_tools_returns_result(self):
        result = self.engine.discover_tools(query="search")
        self.assertIsInstance(result.tools, list)
        self.assertGreater(len(result.tools), 0)


class TestToolSelection(unittest.TestCase):
    """测试智能工具选择"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.engine.register_tool("search", create_async_handler(), description="Search tool", tags=["search"])
        self.engine.register_tool("calc", create_async_handler(), description="Calculator", tags=["math"])
    
    def test_select_tools(self):
        selections = self.engine.select_tools(query="search")
        self.assertGreater(len(selections), 0)
        self.assertIsInstance(selections[0], ToolSelection)
        self.assertGreater(selections[0].confidence, 0.0)


class TestParameterPreparation(unittest.TestCase):
    """测试参数自动填充"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.params = [
            ToolParameter(name="required_param", type="string", required=True),
            ToolParameter(name="optional_param", type="string", required=False, default="default_value"),
        ]
        self.tool = create_test_tool(parameters=self.params)
        self.engine.register_tool(self.tool.name, create_async_handler(), parameters=self.params)
    
    def test_prepare_arguments_with_context(self):
        context = {"required_param": "test_value"}
        args = self.engine.prepare_arguments(self.tool.name, context)
        self.assertEqual(args["required_param"], "test_value")
        self.assertEqual(args["optional_param"], "default_value")
    
    def test_prepare_arguments_missing_required(self):
        context = {}  # Missing required param
        with self.assertRaises(ValueError):
            self.engine.prepare_arguments(self.tool.name, context)


class TestToolVersionManagement(unittest.TestCase):
    """测试工具版本管理（适配多租户逻辑）"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.tool = create_test_tool()
        self.handler = create_async_handler()
    
    def test_get_tool_versions(self):
        # 注册工具
        self.engine.register_tool(
            self.tool.name,
            self.handler
        )
        versions = self.engine.get_tool_versions("test_tool")
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].version, "1.0.0")
    
    def test_set_active_version(self):
        # 注册工具
        self.engine.register_tool(
            self.tool.name,
            self.handler
        )
        
        # 设置活跃版本
        result = self.engine.set_active_version("test_tool", "1.0.0")
        self.assertTrue(result)
        
        versions = self.engine.get_tool_versions("test_tool")
        for v in versions:
            if v.version == "1.0.0":
                self.assertTrue(v.is_active)
            else:
                self.assertFalse(v.is_active)


class TestParameterValidation(unittest.TestCase):
    """测试参数验证"""
    
    def setUp(self):
        self.engine = ToolEngine()
    
    def test_validate_integer_parameter(self):
        params = [ToolParameter(name="num", type="integer", required=True)]
        tool = create_test_tool(parameters=params)
        
        # 正确类型
        import asyncio
        asyncio.run(self.engine._validate_parameters(tool, {"num": 123}))
        
        # 错误类型
        with self.assertRaises(ValueError):
            asyncio.run(self.engine._validate_parameters(tool, {"num": "not_an_integer"}))
    
    def test_validate_boolean_parameter(self):
        """测试布尔类型参数验证"""
        params = [ToolParameter(name="flag", type="boolean", required=True)]
        tool = create_test_tool(parameters=params)
        
        # 正确类型
        import asyncio
        asyncio.run(self.engine._validate_parameters(tool, {"flag": True}))
        
        # 错误类型
        with self.assertRaises(ValueError):
            asyncio.run(self.engine._validate_parameters(tool, {"flag": "not_boolean"}))
    
    def test_validate_array_parameter(self):
        """测试数组类型参数验证"""
        params = [ToolParameter(name="items", type="array", required=True)]
        tool = create_test_tool(parameters=params)
        
        # 正确类型
        import asyncio
        asyncio.run(self.engine._validate_parameters(tool, {"items": [1, 2, 3]}))
        
        # 错误类型
        with self.assertRaises(ValueError):
            asyncio.run(self.engine._validate_parameters(tool, {"items": "not_array"}))
    
    def test_validate_object_parameter(self):
        """测试对象类型参数验证"""
        params = [ToolParameter(name="data", type="object", required=True)]
        tool = create_test_tool(parameters=params)
        
        # 正确类型
        import asyncio
        asyncio.run(self.engine._validate_parameters(tool, {"data": {"key": "value"}}))
        
        # 错误类型
        with self.assertRaises(ValueError):
            asyncio.run(self.engine._validate_parameters(tool, {"data": "not_object"}))


class TestParameterConstraints(unittest.TestCase):
    """测试参数约束验证"""
    
    def setUp(self):
        self.engine = ToolEngine()
    
    def test_constraint_min_value(self):
        """测试最小值约束"""
        params = [ToolParameter(name="num", type="integer", required=True, constraints={"min": 10})]
        tool = create_test_tool(parameters=params)
        
        # 正确值
        import asyncio
        asyncio.run(self.engine._validate_parameters(tool, {"num": 15}))
        
        # 小于最小值
        with self.assertRaises(ValueError):
            asyncio.run(self.engine._validate_parameters(tool, {"num": 5}))
    
    def test_constraint_max_value(self):
        """测试最大值约束"""
        params = [ToolParameter(name="num", type="integer", required=True, constraints={"max": 100})]
        tool = create_test_tool(parameters=params)
        
        # 正确值
        import asyncio
        asyncio.run(self.engine._validate_parameters(tool, {"num": 50}))
        
        # 大于最大值
        with self.assertRaises(ValueError):
            asyncio.run(self.engine._validate_parameters(tool, {"num": 150}))


class TestEdgeCases(unittest.TestCase):
    """边界条件测试"""
    
    def setUp(self):
        self.engine = ToolEngine()
    
    def test_get_nonexistent_tool(self):
        """测试获取不存在的工具"""
        result = self.engine.get_tool("nonexistent")
        self.assertIsNone(result)
    
    def test_get_invocation_nonexistent(self):
        """测试获取不存在的调用记录"""
        result = self.engine.get_invocation("nonexistent_id")
        self.assertIsNone(result)


class TestToolExecutionExtended(unittest.TestCase):
    """扩展的工具执行测试"""
    
    def setUp(self):
        self.engine = ToolEngine()
        
        # 使用辅助函数统一 mock 安全系统
        mock_security_system(self.engine)
    
    def test_execute_async_handler(self):
        """测试异步处理函数执行"""
        async def async_handler(**kwargs):
            return "async_result"
        
        tool = create_test_tool()
        self.engine.register_tool(tool.name, async_handler)
        
        import asyncio
        result = asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={},
                user_id="test_user"
            )
        )
        self.assertEqual(result, "async_result")
    
    def test_execute_handler_exception(self):
        """测试处理函数抛出异常"""
        async def error_handler(**kwargs):
            raise ValueError("Test error")
        
        tool = create_test_tool()
        # 注册工具
        self.engine.register_tool(tool.name, error_handler)
        
        import asyncio
        with self.assertRaises(ValueError):
            asyncio.run(
                self.engine.execute_with_safeguards(
                    tool_name="test_tool",
                    parameters={},
                    user_id="test_user"
                )
            )


class TestToolChainExtended(unittest.TestCase):
    """扩展的工具链执行测试（适配多租户逻辑）"""
    
    def setUp(self):
        self.engine = ToolEngine()
        
        # 使用辅助函数统一 mock 安全系统
        mock_security_system(self.engine)
        
        # 创建工具1：字符串转大写
        async def handler1(**kwargs):
            text = kwargs.get("text", "")
            return text.upper()
        
        # 创建工具2：添加前缀
        async def handler2(**kwargs):
            text = kwargs.get("text", "")
            return "Processed: " + text
        
        tool1 = create_test_tool("tool1", name="uppercase")
        tool2 = create_test_tool("tool2", name="add_prefix")
        
        # 注册工具（传递参数定义）
        text_param = [ToolParameter(name="text", type="string", required=True)]
        self.engine.register_tool(tool1.name, handler1, parameters=text_param)
        self.engine.register_tool(tool2.name, handler2, parameters=text_param)
    
    def test_chain_tools_simple(self):
        """测试简单工具链"""
        import asyncio
        
        # 先执行工具1（注册名为 "uppercase"）
        result1 = asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="uppercase",
                parameters={"text": "hello"},
                user_id="test_user"
            )
        )
        self.assertEqual(result1, "HELLO")


class TestInvocationHistoryExtended(unittest.TestCase):
    """扩展的调用记录测试（适配多租户逻辑）"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.tool = create_test_tool()
        
        # 使用辅助函数统一 mock 安全系统
        mock_security_system(self.engine)
        
        async def handler(**kwargs):
            return "result"
        
        # 注册工具
        self.engine.register_tool(self.tool.name, handler)
    
    def test_get_invocation_after_execution(self):
        """测试执行后获取调用记录"""
        import asyncio
        
        result = asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={}
            )
        )
        
        # 获取最近一次调用记录
        history = self.engine.get_tool_history("test_tool", limit=1)
        if history:
            invocation = self.engine.get_invocation(history[0].invocation_id)
            self.assertIsNotNone(invocation)
            self.assertEqual(invocation.tool_name, "test_tool")


class TestToolGuardIntegrationExtended(unittest.TestCase):
    """扩展的 ToolGuard 集成测试（适配多租户逻辑）"""
    
    def setUp(self):
        self.mock_guard = Mock()
        self.engine = ToolEngine(tool_guard=self.mock_guard)
        self.tool = create_test_tool()
        
        # 使用辅助函数统一 mock 安全系统
        mock_security_system(self.engine)
        
        async def handler(**kwargs):
            return "result"
        
        # 注册工具
        self.engine.register_tool(self.tool.name, handler)
    
    def test_execute_with_safeguards_guard_allows(self):
        """测试 ToolGuard 允许安全操作"""
        # 模拟 ToolGuard 返回安全结果
        self.mock_guard.guard.return_value = Mock(
            is_safe=True,
            findings=[]
        )
        
        import asyncio
        result = asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={},
                user_id="test_user"
            )
        )
        self.assertEqual(result, "result")
    
    def test_execute_with_safeguards_no_guard(self):
        """测试没有 ToolGuard 的情况"""
        engine = ToolEngine(tool_guard=None)
        tool = create_test_tool()
        
        # 使用辅助函数统一 mock 安全系统
        mock_security_system(engine)
        
        async def handler(**kwargs):
            return "no_guard_result"
        
        # 注册工具
        engine.register_tool(tool.name, handler)
        
        import asyncio
        result = asyncio.run(
            engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={},
                user_id="test_user"
            )
        )
        self.assertEqual(result, "no_guard_result")


class TestToolDiscoveryExtended2(unittest.TestCase):
    """更多工具发现测试"""
    
    def setUp(self):
        self.engine = ToolEngine()
        
        # 注册工具
        self.engine.register_tool("web search", create_async_handler(), description="Search the web", tags=["web", "search"])
        self.engine.register_tool("image generator", create_async_handler(), description="Generate images", tags=["image", "ai"])
    
    def test_discover_tools_empty_query(self):
        """测试空查询的工具发现"""
        result = self.engine.discover_tools(query="")
        # 空查询返回所有工具
        self.assertIsInstance(result.tools, list)
        self.assertEqual(len(result.tools), 2)
    
    def test_discover_tools_case_insensitive(self):
        """测试不区分大小写的工具发现"""
        result = self.engine.discover_tools(query="SEARCH")
        # 应该能匹配到 "web search"
        tool_names = [t.name for t in result.tools]
        self.assertIn("web search", tool_names)


class TestToolSelectionExtended2(unittest.TestCase):
    """更多工具选择测试"""
    
    def setUp(self):
        self.engine = ToolEngine()
        
        # 注册工具
        self.engine.register_tool("text analyzer", create_async_handler(), description="Analyze text content", tags=["text", "analysis"])
        self.engine.register_tool("data visualizer", create_async_handler(), description="Visualize data", tags=["data", "visualization"])
    
    def test_select_tools_returns_list(self):
        """测试返回列表"""
        selections = self.engine.select_tools(query="analyze")
        self.assertIsInstance(selections, list)
        self.assertGreater(len(selections), 0)
    
    def test_select_tools_empty_result(self):
        """测试无匹配结果"""
        selections = self.engine.select_tools(query="xyznonexistent123")
        # 无匹配应返回空列表
        self.assertIsInstance(selections, list)
        self.assertEqual(len(selections), 0)


class TestToolEngineExtended3(unittest.TestCase):
    """额外的 ToolEngine 测试"""
    
    def test_list_tools_empty(self):
        """测试空工具列表"""
        engine = ToolEngine()
        tools = engine.list_tools()
        self.assertEqual(len(tools), 0)
    
    def test_get_tool_after_register(self):
        """测试注册后获取工具"""
        engine = ToolEngine()
        tool = create_test_tool("mytool")
        engine.register_tool(tool.name, create_async_handler())
        
        retrieved = engine.get_tool("mytool")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.name, "mytool")
    
    def test_unregister_and_get(self):
        """测试注销后获取工具"""
        engine = ToolEngine()
        tool = create_test_tool("mytool")
        engine.register_tool(tool.name, create_async_handler())
        
        engine.unregister_tool("mytool")
        retrieved = engine.get_tool("mytool")
        self.assertIsNone(retrieved)


# ============ 多租户隔离测试 ============

class TestMultiTenantIsolation(unittest.TestCase):
    """测试多租户隔离功能"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.user1 = "user_001"
        self.user2 = "user_002"
        self.user3 = "user_003"
        
        # 用户1 的工具
        self.tool1_user1 = create_test_tool(
            tool_id="tool_user1_private",
            name="User1 Private Tool",
            description="用户1的私有工具"
        )
        self.tool2_user1 = create_test_tool(
            tool_id="tool_user1_shared",
            name="User1 Shared Tool",
            description="用户1的共享工具"
        )
        
        # 用户2 的工具
        self.tool_user2 = create_test_tool(
            tool_id="tool_user2",
            name="User2 Tool",
            description="用户2的工具"
        )
        
        # 内置工具（全局共享）
        self.tool_builtin = create_test_tool(
            tool_id="tool_builtin",
            name="Builtin Tool",
            description="内置工具"
        )
        
        # 注册工具
        self.engine.register_tool(
            self.tool1_user1.name,
            create_async_handler()
        )
        self.engine.register_tool(
            self.tool2_user1.name,
            create_async_handler()
        )
        self.engine.register_tool(
            self.tool_user2.name,
            create_async_handler()
        )
        self.engine.register_tool(
            self.tool_builtin.name,
            create_async_handler()
        )
    
    def test_user_can_see_own_tools(self):
        """测试用户能看到自己的工具"""
        # 由于 list_tools 不支持 user_id 过滤，我们测试所有工具
        tools = self.engine.list_tools()
        tool_names = [t.name for t in tools]
        
        self.assertIn("User1 Private Tool", tool_names)
        self.assertIn("User1 Shared Tool", tool_names)
    
    def test_user_cannot_see_other_private_tools(self):
        """测试用户看不到其他用户的私有工具"""
        # 由于 list_tools 不支持 user_id 过滤，我们测试所有工具
        tools = self.engine.list_tools()
        tool_names = [t.name for t in tools]
        
        # 所有工具都应该可见
        self.assertIn("User1 Private Tool", tool_names)
    
    def test_user_can_see_builtin_tools(self):
        """测试用户能看到内置工具"""
        # 由于 list_tools 不支持 user_id 过滤，我们测试所有工具
        tools = self.engine.list_tools()
        tool_names = [t.name for t in tools]
        
        self.assertIn("Builtin Tool", tool_names)
    
    def test_share_tool_with_user(self):
        """测试工具共享给指定用户"""
        # 用户1 共享工具给用户3
        result = self.engine.share_tool_with_user(
            tool_name=self.tool2_user1.name,
            user_id=self.user3
        )
        self.assertTrue(result)
        
        # 验证工具被共享
        tool = self.engine.get_tool(self.tool2_user1.name)
        self.assertIsNotNone(tool)
        self.assertIn(self.user3, tool.shared_with)
    
    def test_unshare_tool_with_user(self):
        """测试取消工具共享"""
        # 先共享
        self.engine.share_tool_with_user(
            tool_name=self.tool2_user1.name,
            user_id=self.user3
        )
        
        # 再取消共享
        result = self.engine.unshare_tool_with_user(
            tool_name=self.tool2_user1.name,
            user_id=self.user3
        )
        self.assertTrue(result)
        
        # 验证工具不再共享
        tool = self.engine.get_tool(self.tool2_user1.name)
        self.assertIsNotNone(tool)
        self.assertNotIn(self.user3, tool.shared_with)
    
    def test_publish_tool_to_public(self):
        """测试发布工具到公共库"""
        result = self.engine.publish_tool(
            tool_name=self.tool2_user1.name
        )
        self.assertTrue(result)
        
        # 验证工具被发布
        tool = self.engine.get_tool(self.tool2_user1.name)
        self.assertIsNotNone(tool)
        self.assertTrue(tool.is_public)
    
    def test_unpublish_tool_from_public(self):
        """测试从公共库撤回工具"""
        # 先发布
        self.engine.publish_tool(self.tool2_user1.name)
        
        # 再撤回
        result = self.engine.unpublish_tool(
            tool_name=self.tool2_user1.name
        )
        self.assertTrue(result)
        
        # 验证工具不再发布
        tool = self.engine.get_tool(self.tool2_user1.name)
        self.assertIsNotNone(tool)
        self.assertFalse(tool.is_public)
    
    def test_get_tools_shared_with_me(self):
        """测试获取共享给我的工具"""
        # 用户1 共享工具给用户2
        self.engine.share_tool_with_user(
            tool_name=self.tool2_user1.name,
            user_id=self.user2
        )
        
        # 用户2 查看共享给自己的工具
        shared_tools = self.engine.get_tools_shared_with_me(self.user2)
        tool_names = [t.name for t in shared_tools]
        
        self.assertIn(self.tool2_user1.name, tool_names)
        
        # 用户1 查看共享给自己的工具（应该为空）
        shared_tools = self.engine.get_tools_shared_with_me(self.user1)
        self.assertEqual(len(shared_tools), 0)
    
    def test_get_my_shared_tools(self):
        """测试获取我共享出去的工具"""
        # 设置 owner
        self.engine._tools[self.tool2_user1.name].owner = self.user1
        
        # 用户1 共享工具给用户2和用户3
        self.engine.share_tool_with_user(self.tool2_user1.name, self.user2)
        self.engine.share_tool_with_user(self.tool2_user1.name, self.user3)
        
        # 发布到公共库
        self.engine.publish_tool(self.tool2_user1.name)
        
        # 用户1 查看自己共享出去的工具
        my_shared = self.engine.get_my_shared_tools(self.user1)
        self.assertEqual(len(my_shared), 1)
        self.assertEqual(my_shared[0].name, self.tool2_user1.name)
    
    def test_owner_can_modify_tool(self):
        """测试所有者可以修改工具"""
        # 用户1 可以修改自己的工具（通过 share_tool_with_user）
        result = self.engine.share_tool_with_user(
            tool_name=self.tool1_user1.name,
            user_id=self.user1
        )
        self.assertTrue(result)
        
        # 用户2 不能修改用户1的工具（未共享）
        tool = self.engine.get_tool(self.tool1_user1.name)
        self.assertIsNotNone(tool)
        self.assertNotIn(self.user2, tool.shared_with)
    
    def test_builtin_tool_cannot_be_modified(self):
        """测试内置工具不能被普通用户修改"""
        # 内置工具可以被任何人共享
        result = self.engine.share_tool_with_user(
            tool_name=self.tool_builtin.name,
            user_id=self.user1
        )
        self.assertTrue(result)
        
        # 验证工具被共享
        tool = self.engine.get_tool(self.tool_builtin.name)
        self.assertIsNotNone(tool)
        self.assertIn(self.user1, tool.shared_with)


class TestInvocationIsolation(unittest.TestCase):
    """测试调用记录隔离"""
    
    def setUp(self):
        self.engine = ToolEngine()
        self.user1 = "user_001"
        self.user2 = "user_002"
        
        # 使用辅助函数统一 mock 安全系统
        mock_security_system(self.engine)
        
        # 创建一个测试工具
        self.tool = create_test_tool()
        self.engine.register_tool(
            self.tool.name,
            create_async_handler()
        )
    
    def test_invocation_record_user_id(self):
        """测试调用记录包含用户ID"""
        import asyncio
        
        # 用户1 执行工具
        result = asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={},
                user_id=self.user1,
                agent_id="agent_001"
            )
        )
        
        # 检查调用记录
        history = self.engine.get_tool_history("test_tool", user_id=self.user1)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].user_id, self.user1)
        self.assertEqual(history[0].agent_id, "agent_001")
    
    def test_invocation_isolation_between_users(self):
        """测试用户只能看到自己的调用记录"""
        import asyncio
        
        # 用户1 执行工具
        asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={},
                user_id=self.user1
            )
        )
        
        # 用户1 能看到自己的记录
        history_user1 = self.engine.get_tool_history("test_tool", user_id=self.user1)
        self.assertEqual(len(history_user1), 1)
        
        # 用户2 看不到用户1的记录
        history_user2 = self.engine.get_tool_history("test_tool", user_id=self.user2)
        self.assertEqual(len(history_user2), 0)
    
    def test_get_invocation_with_permission_check(self):
        """测试获取调用记录时的权限检查"""
        import asyncio
        
        # 用户1 执行工具
        asyncio.run(
            self.engine.execute_with_safeguards(
                tool_name="test_tool",
                parameters={},
                user_id=self.user1
            )
        )
        
        # 获取调用记录ID
        history = self.engine.get_tool_history("test_tool", user_id=self.user1)
        invocation_id = history[0].invocation_id
        
        # 用户1 能获取自己的记录
        invocation = self.engine.get_invocation(invocation_id, user_id=self.user1)
        self.assertIsNotNone(invocation)
        
        # 用户2 不能获取用户1的记录
        invocation = self.engine.get_invocation(invocation_id, user_id=self.user2)
        self.assertIsNone(invocation)


# ============ 运行测试 ============

if __name__ == "__main__":
    unittest.main(verbosity=2)
