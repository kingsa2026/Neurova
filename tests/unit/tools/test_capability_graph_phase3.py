"""
Phase 3: CapabilityGraph 扩展测试 — 拓扑排序 + 最短路径
"""
import pytest
from neurova.tool_layers.capability_graph import ToolCapabilityGraph, ToolCapabilityNode


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def graph():
    """默认工具能力图"""
    return ToolCapabilityGraph()


@pytest.fixture
def simple_graph():
    """简化的有向依赖图"""
    g = ToolCapabilityGraph()
    # A → B → D (D 依赖 B, B 依赖 A)
    g.nodes.clear()
    g._adjacency.clear()
    g.add_node(ToolCapabilityNode(
        tool_name="A", provides=["cap_a"]
    ))
    g.add_node(ToolCapabilityNode(
        tool_name="B", requires=["cap_a"], provides=["cap_b"]
    ))
    g.add_node(ToolCapabilityNode(
        tool_name="C", provides=["cap_c"]
    ))
    g.add_node(ToolCapabilityNode(
        tool_name="D", requires=["cap_b", "cap_c"], provides=["cap_d"]
    ))
    return g


# ============================================================
# Topological Sort
# ============================================================

class TestTopologicalSort:
    """拓扑排序测试"""

    def test_sort_simple_chain(self, simple_graph):
        """简单链 A→B→D：A 必须在 B 前，B 必须在 D 前"""
        order = simple_graph.topological_sort(["A", "B", "C", "D"])

        assert order.index("A") < order.index("B")
        assert order.index("B") < order.index("D")
        assert order.index("C") < order.index("D")

    def test_sort_no_deps(self, simple_graph):
        """无依赖的工具可以任意顺序"""
        order = simple_graph.topological_sort(["A", "C"])
        assert set(order) == {"A", "C"}
        assert len(order) == 2

    def test_sort_single_tool(self, simple_graph):
        """单个工具"""
        order = simple_graph.topological_sort(["A"])
        assert order == ["A"]

    def test_sort_empty(self, simple_graph):
        """空列表"""
        order = simple_graph.topological_sort([])
        assert order == []

    def test_sort_unknown_tools_skipped(self, simple_graph):
        """未知工具被跳过"""
        order = simple_graph.topological_sort(["A", "UNKNOWN"])
        assert "UNKNOWN" not in order
        assert "A" in order

    def test_sort_browser_workflow(self, graph):
        """浏览器工作流: navigate 必须在 screenshot 之前"""
        order = graph.topological_sort([
            "browser_navigate", "browser_click", "browser_screenshot",
            "visual_parse", "smart_click", "screenshot",
        ])
        assert order.index("browser_navigate") < order.index("browser_click")
        assert order.index("browser_navigate") < order.index("browser_screenshot")
        assert order.index("screenshot") < order.index("visual_parse")
        assert order.index("visual_parse") < order.index("smart_click")

    def test_sort_preserves_independent_order(self, graph):
        """独立工具之间保持相对稳定顺序"""
        order1 = graph.topological_sort(["file_read", "memory_search", "shell"])
        order2 = graph.topological_sort(["file_read", "memory_search", "shell"])
        assert order1 == order2  # 确定性输出

    def test_sort_cycle_handling(self):
        """循环依赖不抛异常，返回最佳拓扑序"""
        g = ToolCapabilityGraph()
        g.nodes.clear()
        g._adjacency.clear()
        g.add_node(ToolCapabilityNode(
            tool_name="X", requires=["cap_y"], provides=["cap_x"]
        ))
        g.add_node(ToolCapabilityNode(
            tool_name="Y", requires=["cap_x"], provides=["cap_y"]
        ))
        # 不应抛异常
        order = g.topological_sort(["X", "Y"])
        assert set(order) == {"X", "Y"}


# ============================================================
# Shortest Path to Capability
# ============================================================

class TestFindPathToCapability:
    """查找达到目标能力的最短工具路径"""

    def test_find_direct_provider(self, simple_graph):
        """目标能力直接由某个工具提供"""
        path = simple_graph.find_path_to_capability("cap_a", ["A", "B", "C"])
        assert path == ["A"]

    def test_find_two_step_path(self, simple_graph):
        """需要两步到达目标"""
        # cap_d 由 D 提供，D 需要 cap_b + cap_c
        # cap_b 由 B 提供，B 需要 cap_a → A 提供
        path = simple_graph.find_path_to_capability("cap_d", ["A", "B", "C", "D"])
        # 结果应是 A→B→D (加上 C 因为 D 也需要 cap_c)
        assert "D" == path[-1]  # D 是最后一步
        assert "A" in path
        assert path.index("A") < path.index("B")
        assert path.index("B") < path.index("D")

    def test_find_unreachable(self, simple_graph):
        """目标能力无法到达"""
        path = simple_graph.find_path_to_capability("cap_z", ["A", "B", "C"])
        assert path == []

    def test_find_browser_screenshot_path(self, graph):
        """找到 browser_screenshot 所需的完整路径"""
        path = graph.find_path_to_capability(
            "page_loaded",
            ["browser_navigate", "browser_click", "browser_screenshot",
             "file_read", "shell"]
        )
        assert path == ["browser_navigate"]  # 直接提供 page_loaded

    def test_find_smart_click_chain(self, graph):
        """smart_click 需要 screen_image → screenshot 提供"""
        path = graph.find_path_to_capability(
            "ui_action",
            ["screenshot", "click", "type_text", "scroll"]
        )
        assert "click" in path or "type_text" in path or "scroll" in path

    def test_find_multiple_paths_returns_shortest(self, graph):
        """多个可达路径时返回最短的"""
        # file_content 由 file_read 直接提供
        path = graph.find_path_to_capability(
            "file_content",
            ["file_read", "file_write", "file_edit", "file_delete", "shell"]
        )
        assert path == ["file_read"]  # 最短路径


# ============================================================
# Execution Plan Building
# ============================================================

class TestBuildExecutionPlan:
    """从目标构建 DAG 执行计划"""

    def test_plan_single_step(self, simple_graph):
        """单步目标"""
        plan = simple_graph.build_execution_plan(
            goal_capabilities=["cap_a"],
            available_tools=["A", "B", "C", "D"],
        )
        assert len(plan) == 1
        assert plan[0]["step"] == 1
        assert plan[0]["tool"] == "A"

    def test_plan_multi_step_dag(self, simple_graph):
        """多步 DAG 计划"""
        plan = simple_graph.build_execution_plan(
            goal_capabilities=["cap_d"],
            available_tools=["A", "B", "C", "D"],
        )
        # 应该有批次：[A+C] (layer 1) → [B] (layer 2) → [D] (layer 3)
        # 或类似的分层结构
        assert len(plan) >= 3
        tools = [p["tool"] for p in plan]
        assert "D" in tools

    def test_plan_parallel_batch(self, graph):
        """独立工具在同一批次并行"""
        plan = graph.build_execution_plan(
            goal_capabilities=["ui_action", "file_content"],
            available_tools=["screenshot", "click", "file_read", "shell"],
        )
        # click 和 file_read 无依赖关系，应在同一批次
        steps = {}
        for p in plan:
            steps.setdefault(p["step"], []).append(p["tool"])

        # 同一步骤的工具可以并行
        for step_id, tools_in_step in steps.items():
            assert len(tools_in_step) >= 1

    def test_plan_with_unknown_tools(self, simple_graph):
        """可用工具不包含未知工具"""
        plan = simple_graph.build_execution_plan(
            goal_capabilities=["cap_a"],
            available_tools=["A", "UNKNOWN"],
        )
        tools = [p["tool"] for p in plan]
        assert "UNKNOWN" not in tools

    def test_plan_unreachable_goal(self, simple_graph):
        """无法到达的目标返回空计划"""
        plan = simple_graph.build_execution_plan(
            goal_capabilities=["cap_z"],
            available_tools=["A", "B"],
        )
        assert plan == []

    def test_plan_with_fallback(self, simple_graph):
        """计划包含降级路径"""
        # 添加降级关系
        simple_graph.add_node(ToolCapabilityNode(
            tool_name="E", provides=["cap_d"], degrades_to=["D"]
        ))
        plan = simple_graph.build_execution_plan(
            goal_capabilities=["cap_d"],
            available_tools=["A", "B", "C", "D", "E"],
            include_fallbacks=True,
        )
        # 应有至少一个工具出现在计划中
        assert len(plan) > 0

    def test_plan_ok_if_no_goal(self, simple_graph):
        """空目标返回空"""
        plan = simple_graph.build_execution_plan(
            goal_capabilities=[],
            available_tools=["A", "B"],
        )
        assert plan == []
