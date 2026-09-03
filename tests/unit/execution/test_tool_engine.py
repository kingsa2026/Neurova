"""
ToolEngine 单元测试
"""

import unittest
from unittest.mock import patch, MagicMock

try:
    from neurova.execution_engine.tool_engine import (
        ToolEngine, ToolDefinition, ToolParameter, ToolStatus,
        ToolCallingContext, ToolInvocation
    )
    HAS_TOOL_ENGINE = True
except ImportError:
    HAS_TOOL_ENGINE = False


@unittest.skipIf(not HAS_TOOL_ENGINE, "ToolEngine not available")
class TestToolEngine(unittest.TestCase):
    """ToolEngine 测试类"""

    def setUp(self) -> None:
        """测试前初始化"""
        self.engine = ToolEngine()

    def _make_definition(self, tool_id, name="Test Tool", description="Test tool",
                         category="general", tags=None):
        """创建ToolDefinition辅助方法"""
        return ToolDefinition(
            id=tool_id,
            name=name,
            description=description,
            parameters=[
                ToolParameter(name="param1", type="string", required=True),
                ToolParameter(name="param2", type="integer", required=False, default=0),
            ],
            category=category,
            tags=tags or [],
            status=ToolStatus.AVAILABLE,
        )

    def test_register_tool(self) -> None:
        """测试注册工具"""
        def test_handler(param1: str, param2: int = 0):
            return {"result": f"{param1}-{param2}"}

        definition = self._make_definition("test_tool", "Test Tool")
        self.engine.register_tool(definition, test_handler)

        tool = self.engine.get_tool("test_tool")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "Test Tool")

    def test_unregister_tool(self) -> None:
        """测试注销工具"""
        def test_handler():
            return "test"

        definition = self._make_definition("test_tool", "Test Tool")
        self.engine.register_tool(definition, test_handler)

        self.assertTrue(self.engine.unregister_tool("test_tool"))
        self.assertIsNone(self.engine.get_tool("test_tool"))

    def test_list_tools(self) -> None:
        """测试列出工具"""
        def handler1():
            pass

        def handler2():
            pass

        self.engine.register_tool(
            self._make_definition("tool1", "Tool 1"), handler1)
        self.engine.register_tool(
            self._make_definition("tool2", "Tool 2"), handler2)

        tools = self.engine.list_tools()
        self.assertEqual(len(tools), 2)

    def test_list_tools_by_category(self) -> None:
        """测试按分类列出工具"""
        def handler1():
            pass

        def handler2():
            pass

        self.engine.register_tool(
            self._make_definition("search_tool", "Search", category="search"), handler1)
        self.engine.register_tool(
            self._make_definition("math_tool", "Math", category="math"), handler2)

        search_tools = self.engine.list_tools(category="search")
        self.assertEqual(len(search_tools), 1)
        self.assertEqual(search_tools[0].name, "Search")

    def test_get_nonexistent_tool(self) -> None:
        """测试获取不存在的工具"""
        tool = self.engine.get_tool("nonexistent")
        self.assertIsNone(tool)

    def test_unregister_nonexistent_tool(self) -> None:
        """测试注销不存在的工具"""
        self.assertFalse(self.engine.unregister_tool("nonexistent"))

    def test_register_duplicate_tool(self) -> None:
        """测试注册重复工具（更新版本）"""
        def handler1():
            return "v1"

        def handler2():
            return "v2"

        self.engine.register_tool(
            self._make_definition("dup_tool"), handler1, version="1.0.0")
        self.engine.register_tool(
            self._make_definition("dup_tool"), handler2, version="2.0.0")

        tool = self.engine.get_tool("dup_tool")
        self.assertEqual(tool.version, "1.0.0")

    def test_tool_versions(self) -> None:
        """测试工具版本管理"""
        def handler():
            pass

        self.engine.register_tool(
            self._make_definition("vtool"), handler, version="1.0.0")

        versions = self.engine.get_tool_versions("vtool")
        self.assertEqual(len(versions), 1)
        self.assertEqual(versions[0].version, "1.0.0")

    def test_discover_tools(self) -> None:
        """测试工具发现"""
        def handler():
            pass

        self.engine.register_tool(
            self._make_definition(
                "search_web", "Web Search",
                description="Search the web for information",
                tags=["search", "web"]
            ),
            handler
        )
        self.engine.register_tool(
            self._make_definition(
                "calculator", "Calculator",
                description="Calculate math expressions",
                tags=["math"]
            ),
            handler
        )

        context = ToolCallingContext(intent="I need to search the web")
        results = self.engine.discover_tools(context)
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].tool_id, "search_web")


if __name__ == "__main__":
    unittest.main()