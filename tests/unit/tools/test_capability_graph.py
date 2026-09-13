"""
ToolCapabilityGraph 单元测试

测试目标：
1. ToolCapabilityNode 数据类
2. ToolCapabilityGraph 类的图操作
3. 拓扑排序
4. 能力路径查找
5. 执行计划构建
6. LLM 上下文生成
"""

import pytest
from unittest.mock import MagicMock, patch

from neurova.tool_layers.capability_graph import ToolCapabilityNode, ToolCapabilityGraph


class TestToolCapabilityNode:
    """ToolCapabilityNode 数据类测试"""

    def test_node_creation(self):
        """测试节点创建"""
        node = ToolCapabilityNode(
            tool_name="file_read",
            capabilities=["read_file", "read_path"],
            dependencies=["path_resolver"],
            fallbacks=["memory_search"],
            companions=["file_write"],
            metadata={"category": "filesystem"}
        )
        assert node.tool_name == "file_read"
        assert "read_file" in node.capabilities
        assert "path_resolver" in node.dependencies
        assert "memory_search" in node.fallbacks
        assert "file_write" in node.companions
        assert node.metadata["category"] == "filesystem"

    def test_node_defaults(self):
        """测试节点默认值"""
        node = ToolCapabilityNode(tool_name="simple_tool")
        assert node.tool_name == "simple_tool"
        assert node.capabilities == []
        assert node.dependencies == []
        assert node.fallbacks == []
        assert node.companions == []
        assert node.metadata == {}

    def test_node_equality(self):
        """测试节点相等性"""
        node1 = ToolCapabilityNode(tool_name="tool_a", capabilities=["cap1"])
        node2 = ToolCapabilityNode(tool_name="tool_a", capabilities=["cap1"])
        node3 = ToolCapabilityNode(tool_name="tool_b", capabilities=["cap1"])
        assert node1 == node2
        assert node1 != node3


class TestToolCapabilityGraph:
    """ToolCapabilityGraph 类测试"""

    def setup_method(self):
        """每个测试前重置图（空图，不加载默认工具）"""
        self.graph = ToolCapabilityGraph(load_defaults=False)

    def test_add_node(self):
        """测试添加节点"""
        node = ToolCapabilityNode(tool_name="test_tool")
        self.graph.add_node(node)
        assert self.graph.get_node("test_tool") == node

    def test_get_nonexistent_node(self):
        """测试获取不存在的节点"""
        assert self.graph.get_node("nonexistent") is None

    def test_add_co_occurrence(self):
        """测试添加共现关系"""
        node1 = ToolCapabilityNode(tool_name="tool_a")
        node2 = ToolCapabilityNode(tool_name="tool_b")
        self.graph.add_node(node1)
        self.graph.add_node(node2)

        self.graph.add_co_occurrence("tool_a", "tool_b", weight=0.8)
        # 验证关系已添加（具体实现可能需要访问内部数据结构）

    def test_get_prerequisites(self):
        """测试获取前置依赖"""
        node1 = ToolCapabilityNode(tool_name="base_tool")
        node2 = ToolCapabilityNode(tool_name="dependent_tool", dependencies=["base_tool"])
        self.graph.add_node(node1)
        self.graph.add_node(node2)

        prereqs = self.graph.get_prerequisites("dependent_tool")
        assert "base_tool" in prereqs

    def test_suggest_fallback(self):
        """测试建议降级工具"""
        node1 = ToolCapabilityNode(tool_name="primary_tool", fallbacks=["fallback1", "fallback2"])
        self.graph.add_node(node1)

        fallbacks = self.graph.suggest_fallback("primary_tool")
        assert "fallback1" in fallbacks
        assert "fallback2" in fallbacks

    def test_suggest_companion_tools(self):
        """测试建议协作工具"""
        node1 = ToolCapabilityNode(tool_name="tool_a", companions=["tool_b", "tool_c"])
        self.graph.add_node(node1)

        companions = self.graph.suggest_companion_tools("tool_a")
        assert "tool_b" in companions
        assert "tool_c" in companions

    def test_topological_sort_simple(self):
        """测试简单拓扑排序"""
        node1 = ToolCapabilityNode(tool_name="base")
        node2 = ToolCapabilityNode(tool_name="middle", dependencies=["base"])
        node3 = ToolCapabilityNode(tool_name="top", dependencies=["middle"])

        self.graph.add_node(node1)
        self.graph.add_node(node2)
        self.graph.add_node(node3)

        order = self.graph.topological_sort()
        assert order.index("base") < order.index("middle")
        assert order.index("middle") < order.index("top")

    def test_topological_sort_cycle_detection(self):
        """测试拓扑排序循环检测"""
        node1 = ToolCapabilityNode(tool_name="a", dependencies=["b"])
        node2 = ToolCapabilityNode(tool_name="b", dependencies=["a"])

        self.graph.add_node(node1)
        self.graph.add_node(node2)

        with pytest.raises(ValueError, match="cycle"):
            self.graph.topological_sort()

    def test_find_path_to_capability(self):
        """测试查找能力路径"""
        node1 = ToolCapabilityNode(tool_name="reader", capabilities=["read_file"])
        node2 = ToolCapabilityNode(tool_name="analyzer", capabilities=["analyze_text"], dependencies=["reader"])
        node3 = ToolCapabilityNode(tool_name="summarizer", capabilities=["summarize"], dependencies=["analyzer"])

        self.graph.add_node(node1)
        self.graph.add_node(node2)
        self.graph.add_node(node3)

        path = self.graph.find_path_to_capability("summarize")
        assert path == ["reader", "analyzer", "summarizer"]

    def test_build_execution_plan(self):
        """测试构建执行计划"""
        node1 = ToolCapabilityNode(tool_name="input_parser")
        node2 = ToolCapabilityNode(tool_name="data_processor", dependencies=["input_parser"])
        node3 = ToolCapabilityNode(tool_name="output_formatter", dependencies=["data_processor"])

        self.graph.add_node(node1)
        self.graph.add_node(node2)
        self.graph.add_node(node3)

        plan = self.graph.build_execution_plan(["output_formatter"])
        # 验证计划包含正确的执行顺序
        assert len(plan) >= 3
        assert plan[0] == "input_parser"
        assert plan[-1] == "output_formatter"

    def test_to_llm_context(self):
        """测试生成 LLM 上下文"""
        node = ToolCapabilityNode(
            tool_name="weather_tool",
            capabilities=["get_weather"],
            metadata={"description": "获取天气信息"}
        )
        self.graph.add_node(node)

        context = self.graph.to_llm_context("weather_tool")
        assert isinstance(context, str)
        assert "weather_tool" in context
        assert "get_weather" in context

    def test_build_default_graph(self):
        """测试构建默认图"""
        # 测试默认图构建是否正常工作
        self.graph._build_default_graph()
        # 验证默认图包含一些基本工具
        assert len(self.graph._nodes) > 0

    def test_graph_contains_multiple_tools(self):
        """测试图包含多个工具"""
        tools = ["tool_a", "tool_b", "tool_c"]
        for tool in tools:
            self.graph.add_node(ToolCapabilityNode(tool_name=tool))

        assert len(self.graph._nodes) == 3
        for tool in tools:
            assert self.graph.get_node(tool) is not None

    def test_complex_dependency_chain(self):
        """测试复杂依赖链"""
        # 创建一个更复杂的依赖图
        nodes = [
            ToolCapabilityNode(tool_name="init"),
            ToolCapabilityNode(tool_name="step1", dependencies=["init"]),
            ToolCapabilityNode(tool_name="step2a", dependencies=["step1"]),
            ToolCapabilityNode(tool_name="step2b", dependencies=["step1"]),
            ToolCapabilityNode(tool_name="final", dependencies=["step2a", "step2b"]),
        ]

        for node in nodes:
            self.graph.add_node(node)

        order = self.graph.topological_sort()
        assert order.index("init") < order.index("step1")
        assert order.index("step1") < order.index("step2a")
        assert order.index("step1") < order.index("step2b")
        assert order.index("step2a") < order.index("final")
        assert order.index("step2b") < order.index("final")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])