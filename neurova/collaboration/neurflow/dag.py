"""
Neurflow DAG 处理 — 垂直切片 4
环检测（Tarjan SCC）、拓扑排序（Kahn）、DAG 验证
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .models import WorkflowEdge, WorkflowNode


@dataclass
class CycleResult:
    """环检测结果"""

    has_cycle: bool
    cycle_nodes: List[str] = field(default_factory=list)
    message: str = ""


@dataclass
class SortResult:
    """拓扑排序结果"""

    success: bool
    order: List[str] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class ValidationResult:
    """DAG 验证结果"""

    is_valid: bool
    has_cycle: bool = False
    has_start: bool = False
    has_end: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class CycleDetector:
    """
    环检测器 — 使用 Tarjan 强连通分量算法

    时间复杂度：O(V + E)
    空间复杂度：O(V)
    """

    def detect(self, nodes: List[WorkflowNode], edges: List[WorkflowEdge]) -> CycleResult:
        """
        检测图中是否存在环

        Args:
            nodes: 节点列表
            edges: 边列表

        Returns:
            CycleResult 检测结果
        """
        if not nodes:
            return CycleResult(has_cycle=False)

        # 构建邻接表
        graph: Dict[str, List[str]] = defaultdict(list)
        node_ids = {n.id for n in nodes}

        for edge in edges:
            if edge.source in node_ids and edge.target in node_ids:
                graph[edge.source].append(edge.target)

        # Tarjan 算法状态
        index_counter = [0]
        stack: List[str] = []
        lowlink: Dict[str, int] = {}
        index: Dict[str, int] = {}
        on_stack: Set[str] = set()
        sccs: List[List[str]] = []

        def strongconnect(node: str):
            """Tarjan 强连通分量递归"""
            index[node] = index_counter[0]
            lowlink[node] = index_counter[0]
            index_counter[0] += 1
            stack.append(node)
            on_stack.add(node)

            for successor in graph[node]:
                if successor not in index:
                    strongconnect(successor)
                    lowlink[node] = min(lowlink[node], lowlink[successor])
                elif successor in on_stack:
                    lowlink[node] = min(lowlink[node], index[successor])

            # 如果 node 是 SCC 的根
            if lowlink[node] == index[node]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    scc.append(w)
                    if w == node:
                        break
                sccs.append(scc)

        # 对所有节点运行 Tarjan
        for node_id in node_ids:
            if node_id not in index:
                strongconnect(node_id)

        # 找到大小 > 1 的 SCC（包含环）
        cycle_nodes = []
        for scc in sccs:
            if len(scc) > 1:
                cycle_nodes.extend(scc)
            elif len(scc) == 1:
                # 自环检查
                node_id = scc[0]
                if node_id in graph[node_id]:
                    cycle_nodes.append(node_id)

        has_cycle = len(cycle_nodes) > 0

        return CycleResult(
            has_cycle=has_cycle,
            cycle_nodes=cycle_nodes,
            message=f"检测到 {len(cycle_nodes)} 个环节点" if has_cycle else "无环",
        )


class TopologicalSorter:
    """
    拓扑排序器 — Kahn 算法

    时间复杂度：O(V + E)
    空间复杂度：O(V)
    """

    def sort(self, nodes: List[WorkflowNode], edges: List[WorkflowEdge]) -> SortResult:
        """
        对 DAG 进行拓扑排序

        Args:
            nodes: 节点列表
            edges: 边列表

        Returns:
            SortResult 排序结果
        """
        if not nodes:
            return SortResult(success=True, order=[])

        node_ids = {n.id for n in nodes}

        # 构建邻接表和入度表
        graph: Dict[str, List[str]] = defaultdict(list)
        in_degree: Dict[str, int] = {n.id: 0 for n in nodes}

        for edge in edges:
            if edge.source in node_ids and edge.target in node_ids:
                graph[edge.source].append(edge.target)
                in_degree[edge.target] += 1

        # Kahn 算法
        queue = deque()
        for node_id in node_ids:
            if in_degree[node_id] == 0:
                queue.append(node_id)

        order: List[str] = []

        while queue:
            node_id = queue.popleft()
            order.append(node_id)

            for successor in graph[node_id]:
                in_degree[successor] -= 1
                if in_degree[successor] == 0:
                    queue.append(successor)

        # 如果排序结果不包含所有节点，说明有环
        if len(order) != len(node_ids):
            return SortResult(success=False, order=[], error="图中存在环，无法进行拓扑排序")

        return SortResult(success=True, order=order)


class DAGValidator:
    """
    DAG 验证器

    检查项：
    1. 是否存在环
    2. 是否有开始节点
    3. 是否有结束节点
    4. 是否有悬挂边
    5. 是否有孤立节点（警告）
    """

    def __init__(self):
        self._cycle_detector = CycleDetector()
        self._topo_sorter = TopologicalSorter()

    def validate(self, nodes: List[WorkflowNode], edges: List[WorkflowEdge]) -> ValidationResult:
        """
        验证 DAG 的有效性

        Args:
            nodes: 节点列表
            edges: 边列表

        Returns:
            ValidationResult 验证结果
        """
        errors: List[str] = []
        warnings: List[str] = []

        # 空图检查
        if not nodes:
            return ValidationResult(is_valid=False, errors=["工作流为空，至少需要一个节点"])

        node_ids = {n.id for n in nodes}
        node_types = {n.id: n.type for n in nodes}

        # 1. 检查悬挂边
        for edge in edges:
            if edge.source not in node_ids:
                errors.append(f"边 '{edge.id}' 的源节点 '{edge.source}' 不存在")
            if edge.target not in node_ids:
                errors.append(f"边 '{edge.id}' 的目标节点 '{edge.target}' 不存在")

        # 2. 检查开始/结束节点
        has_start = any("start" in node_types.get(n.id, "") for n in nodes)
        has_end = any("end" in node_types.get(n.id, "") for n in nodes)

        if not has_start:
            errors.append("缺少开始节点（类型包含 'start'）")
        if not has_end:
            errors.append("缺少结束节点（类型包含 'end'）")

        # 3. 环检测
        cycle_result = self._cycle_detector.detect(nodes, edges)
        if cycle_result.has_cycle:
            errors.append(f"检测到环，涉及节点: {', '.join(cycle_result.cycle_nodes)}")

        # 4. 孤立节点检查（警告）
        connected_nodes: Set[str] = set()
        for edge in edges:
            if edge.source in node_ids:
                connected_nodes.add(edge.source)
            if edge.target in node_ids:
                connected_nodes.add(edge.target)

        for node in nodes:
            if node.id not in connected_nodes and len(nodes) > 1:
                warnings.append(f"节点 '{node.id}' ({node.label}) 未连接到任何边")

        return ValidationResult(
            is_valid=len(errors) == 0,
            has_cycle=cycle_result.has_cycle,
            has_start=has_start,
            has_end=has_end,
            errors=errors,
            warnings=warnings,
        )

    def get_execution_path(self, nodes: List[WorkflowNode], edges: List[WorkflowEdge]) -> List[str]:
        """
        获取线性执行路径（拓扑排序）

        Args:
            nodes: 节点列表
            edges: 边列表

        Returns:
            执行顺序的节点 ID 列表
        """
        result = self._topo_sorter.sort(nodes, edges)
        return result.order if result.success else []


# 单例
_dag_validator: Optional[DAGValidator] = None


def get_dag_validator() -> DAGValidator:
    """获取 DAG 验证器单例"""
    global _dag_validator
    if _dag_validator is None:
        _dag_validator = DAGValidator()
    return _dag_validator


__all__ = [
    "CycleResult",
    "SortResult",
    "ValidationResult",
    "CycleDetector",
    "TopologicalSorter",
    "DAGValidator",
    "get_dag_validator",
]
