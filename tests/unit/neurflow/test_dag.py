"""
Neurflow DAG 测试 — 垂直切片 4
测试拓扑排序、环检测、执行路径验证
"""
import pytest
from neurova.collaboration.neurflow.dag import (
    DAGValidator, TopologicalSorter, CycleDetector,
    get_dag_validator
)
from neurova.collaboration.neurflow.models import WorkflowNode, WorkflowEdge


class TestCycleDetector:
    """环检测测试"""

    def test_no_cycle_simple(self):
        """简单无环图"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="A", target="B")]

        detector = CycleDetector()
        result = detector.detect(nodes, edges)
        assert result.has_cycle is False
        assert result.cycle_nodes == []

    def test_no_cycle_linear(self):
        """线性无环图"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="C", type="builtin:end", position={"x": 200, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="B", target="C"),
        ]

        detector = CycleDetector()
        result = detector.detect(nodes, edges)
        assert result.has_cycle is False

    def test_no_cycle_branching(self):
        """分支无环图"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:condition", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="C", type="builtin:llm", position={"x": 200, "y": -50}, config={}),
            WorkflowNode(id="D", type="builtin:llm", position={"x": 200, "y": 50}, config={}),
            WorkflowNode(id="E", type="builtin:end", position={"x": 300, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="B", target="C", source_handle="true"),
            WorkflowEdge(id="e3", source="B", target="D", source_handle="false"),
            WorkflowEdge(id="e4", source="C", target="E"),
            WorkflowEdge(id="e5", source="D", target="E"),
        ]

        detector = CycleDetector()
        result = detector.detect(nodes, edges)
        assert result.has_cycle is False

    def test_simple_cycle(self):
        """简单环"""
        nodes = [
            WorkflowNode(id="A", type="builtin:llm", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="B", target="A"),
        ]

        detector = CycleDetector()
        result = detector.detect(nodes, edges)
        assert result.has_cycle is True
        assert len(result.cycle_nodes) >= 2
        assert "A" in result.cycle_nodes
        assert "B" in result.cycle_nodes

    def test_self_loop(self):
        """自环"""
        nodes = [
            WorkflowNode(id="A", type="builtin:loop", position={"x": 0, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="A"),
        ]

        detector = CycleDetector()
        result = detector.detect(nodes, edges)
        assert result.has_cycle is True
        assert "A" in result.cycle_nodes

    def test_indirect_cycle(self):
        """间接环 A→B→C→A"""
        nodes = [
            WorkflowNode(id="A", type="builtin:llm", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="C", type="builtin:llm", position={"x": 200, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="B", target="C"),
            WorkflowEdge(id="e3", source="C", target="A"),
        ]

        detector = CycleDetector()
        result = detector.detect(nodes, edges)
        assert result.has_cycle is True

    def test_empty_graph(self):
        """空图"""
        detector = CycleDetector()
        result = detector.detect([], [])
        assert result.has_cycle is False
        assert result.cycle_nodes == []

    def test_single_node_no_edges(self):
        """单节点无边"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
        ]
        detector = CycleDetector()
        result = detector.detect(nodes, [])
        assert result.has_cycle is False


class TestTopologicalSorter:
    """拓扑排序测试"""

    def test_simple_sort(self):
        """简单排序"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="A", target="B")]

        sorter = TopologicalSorter()
        result = sorter.sort(nodes, edges)
        assert result.success is True
        assert result.order == ["A", "B"]

    def test_linear_sort(self):
        """线性排序"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="C", type="builtin:end", position={"x": 200, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="B", target="C"),
        ]

        sorter = TopologicalSorter()
        result = sorter.sort(nodes, edges)
        assert result.success is True
        assert result.order == ["A", "B", "C"]

    def test_diamond_sort(self):
        """菱形拓扑排序"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:llm", position={"x": 100, "y": -50}, config={}),
            WorkflowNode(id="C", type="builtin:llm", position={"x": 100, "y": 50}, config={}),
            WorkflowNode(id="D", type="builtin:end", position={"x": 200, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="A", target="C"),
            WorkflowEdge(id="e3", source="B", target="D"),
            WorkflowEdge(id="e4", source="C", target="D"),
        ]

        sorter = TopologicalSorter()
        result = sorter.sort(nodes, edges)
        assert result.success is True
        # A 必须在 B、C 之前
        assert result.order.index("A") < result.order.index("B")
        assert result.order.index("A") < result.order.index("C")
        # B、C 必须在 D 之前
        assert result.order.index("B") < result.order.index("D")
        assert result.order.index("C") < result.order.index("D")

    def test_sort_with_cycle(self):
        """有环图排序失败"""
        nodes = [
            WorkflowNode(id="A", type="builtin:llm", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="A", target="B"),
            WorkflowEdge(id="e2", source="B", target="A"),
        ]

        sorter = TopologicalSorter()
        result = sorter.sort(nodes, edges)
        assert result.success is False
        assert result.error is not None

    def test_sort_empty_graph(self):
        """空图排序"""
        sorter = TopologicalSorter()
        result = sorter.sort([], [])
        assert result.success is True
        assert result.order == []

    def test_sort_disconnected_nodes(self):
        """不连通图排序"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:end", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="C", type="builtin:llm", position={"x": 0, "y": 100}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="A", target="B")]

        sorter = TopologicalSorter()
        result = sorter.sort(nodes, edges)
        assert result.success is True
        assert len(result.order) == 3
        # A 在 B 之前
        assert result.order.index("A") < result.order.index("B")


class TestDAGValidator:
    """DAG 验证器测试"""

    @pytest.fixture
    def validator(self):
        return DAGValidator()

    def test_valid_dag(self, validator):
        """有效 DAG"""
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="llm", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 200, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="start", target="llm"),
            WorkflowEdge(id="e2", source="llm", target="end"),
        ]

        result = validator.validate(nodes, edges)
        assert result.is_valid is True
        assert result.has_cycle is False
        assert result.has_start is True
        assert result.has_end is True

    def test_missing_start(self, validator):
        """缺少开始节点"""
        nodes = [
            WorkflowNode(id="llm", type="builtin:llm", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="llm", target="end")]

        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        assert result.has_start is False
        assert "start" in result.errors[0].lower() or "开始" in result.errors[0]

    def test_missing_end(self, validator):
        """缺少结束节点"""
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="llm", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="start", target="llm")]

        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        assert result.has_end is False
        assert "end" in result.errors[0].lower() or "结束" in result.errors[0]

    def test_dangling_edge_source(self, validator):
        """悬挂边 — 源节点不存在"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="nonexistent", target="B")]

        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_dangling_edge_target(self, validator):
        """悬挂边 — 目标节点不存在"""
        nodes = [
            WorkflowNode(id="A", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="B", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="A", target="nonexistent")]

        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        assert len(result.errors) > 0

    def test_empty_graph(self, validator):
        """空图验证"""
        result = validator.validate([], [])
        assert result.is_valid is False

    def test_validation_warnings(self, validator):
        """验证警告 — 孤立节点"""
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="orphan", type="builtin:llm", position={"x": 0, "y": 100}, config={}),
        ]
        edges = [WorkflowEdge(id="e1", source="start", target="end")]

        result = validator.validate(nodes, edges)
        # 孤立节点是警告不是错误
        assert len(result.warnings) > 0

    def test_get_execution_path(self, validator):
        """获取执行路径"""
        nodes = [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="llm1", type="builtin:llm", position={"x": 100, "y": 0}, config={}),
            WorkflowNode(id="llm2", type="builtin:llm", position={"x": 200, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 300, "y": 0}, config={}),
        ]
        edges = [
            WorkflowEdge(id="e1", source="start", target="llm1"),
            WorkflowEdge(id="e2", source="llm1", target="llm2"),
            WorkflowEdge(id="e3", source="llm2", target="end"),
        ]

        path = validator.get_execution_path(nodes, edges)
        assert path == ["start", "llm1", "llm2", "end"]


class TestSingleton:
    """单例模式测试"""

    def test_get_dag_validator(self):
        """获取 DAG 验证器"""
        v1 = get_dag_validator()
        v2 = get_dag_validator()
        assert v1 is v2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])