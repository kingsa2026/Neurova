"""
ToolEngine 单元测试

2026-09-13 残留处理：原文件按一套从未存在的契约书写（ToolDefinition 的
id/category 字段、register_tool(definition, handler, version=) 对象式注册、
list_tools(category=)、discover_tools(ToolCallingContext)——实现自
54bc601e 前身即 name-first 契约且从未变过，全史 -S 零命中）。本文件对齐
真实 API（register_tool(name, func, description=/tags=/status=)），
验证意图逐条保留：注册/查询/注销/列表/标签过滤/重复注册/版本累积/发现。
"""

import unittest

from neurova.execution_engine.tool_engine import (
    ToolEngine,
    ToolParameter,
    ToolStatus,
)


class TestToolEngine(unittest.TestCase):
    """ToolEngine 测试类（name-first 真实契约）"""

    def setUp(self) -> None:
        self.engine = ToolEngine()

    def _register(self, name, description="Test tool", tags=None, status=None):
        def handler():
            return name

        self.engine.register_tool(
            name, handler, description=description, tags=tags, status=status
        )
        return handler

    def test_register_tool(self) -> None:
        self.engine.register_tool(
            "test_tool",
            lambda param1, param2=0: {"result": f"{param1}-{param2}"},
            description="Test tool",
        )
        tool = self.engine.get_tool("test_tool")
        self.assertIsNotNone(tool)
        self.assertEqual(tool.name, "test_tool")
        self.assertEqual(tool.description, "Test tool")

    def test_unregister_tool(self) -> None:
        self._register("test_tool")
        self.assertTrue(self.engine.unregister_tool("test_tool"))
        self.assertIsNone(self.engine.get_tool("test_tool"))

    def test_list_tools(self) -> None:
        self._register("tool1")
        self._register("tool2")
        self.assertEqual(len(self.engine.list_tools()), 2)

    def test_list_tools_by_tags(self) -> None:
        """分类语义的真实载体是 tags（实现无 category 概念）"""
        self._register("search_tool", tags=["search"])
        self._register("math_tool", tags=["math"])
        search_tools = self.engine.list_tools(tags=["search"])
        self.assertEqual(len(search_tools), 1)
        self.assertEqual(search_tools[0].name, "search_tool")

    def test_list_tools_by_status(self) -> None:
        self._register("avail")
        self._register("depr", status=ToolStatus.DEPRECATED)
        available = self.engine.list_tools(status=ToolStatus.AVAILABLE)
        self.assertEqual([t.name for t in available], ["avail"])

    def test_get_nonexistent_tool(self) -> None:
        self.assertIsNone(self.engine.get_tool("nonexistent"))

    def test_unregister_nonexistent_tool(self) -> None:
        self.assertFalse(self.engine.unregister_tool("nonexistent"))

    def test_register_duplicate_overwrites_current(self) -> None:
        def handler1():
            return "v1"

        def handler2():
            return "v2"

        self.engine.register_tool("dup_tool", handler1, description="first")
        self.engine.register_tool("dup_tool", handler2, description="second")
        tool = self.engine.get_tool("dup_tool")
        self.assertEqual(tool.description, "second")  # 覆盖现行定义
        self.assertEqual(len(tool.parameters), 0)  # handler2 无参（无残留）

    def test_tool_versions_accumulate(self) -> None:
        """真实版本语义：每次注册追加一条版本记录（现行恒记 1.0.0）"""
        self.engine.register_tool("vtool", lambda: None, description="one")
        self.engine.register_tool("vtool", lambda: None, description="two")
        versions = self.engine.get_tool_versions("vtool")
        self.assertEqual(len(versions), 2)
        self.assertTrue(all(v.version == "1.0.0" for v in versions))
        self.assertEqual(versions[0].definition.description, "one")

    def test_discover_tools(self) -> None:
        self._register(
            "search_web", description="Search the web for information",
            tags=["search", "web"],
        )
        self._register("calculator", description="Calculate math expressions", tags=["math"])

        results = self.engine.discover_tools(query="search")
        self.assertTrue(len(results.tools) > 0)
        self.assertEqual(results.tools[0].name, "search_web")
        self.assertEqual(results.source, "local")

        by_tag = self.engine.discover_tools(tags=["math"])
        self.assertEqual([t.name for t in by_tag.tools], ["calculator"])

    def test_register_params_extracted_from_signature(self) -> None:
        def handler(query: str, limit: int = 10):
            return None

        self.engine.register_tool("auto_params", handler, description="d")
        names = {p.name for p in self.engine.get_tool("auto_params").parameters}
        self.assertEqual(names, {"query", "limit"})

    def test_parameters_explicit(self) -> None:
        self.engine.register_tool(
            "explicit", lambda: None, description="d",
            parameters=[ToolParameter(name="p1", type="string", required=True)],
        )
        params = self.engine.get_tool("explicit").parameters
        self.assertEqual([p.name for p in params], ["p1"])


if __name__ == "__main__":
    unittest.main()
