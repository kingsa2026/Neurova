"""
图遍历检索模块

利用记忆间的关联关系（MemoryRelation表）进行多跳推理。
支持：
- 多跳路径搜索
- 关联强度加权
- 路径排名
- 循环检测
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Set, Optional, Tuple, Any
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

@dataclass
class MemoryRelation:
    """记忆关联"""
    source_id: str
    target_id: str
    relation_type: str  # "related", "causes", "contradicts", "supports", "part_of", "derived_from", "temporal"
    strength: float = 1.0  # 关联强度 (0.0 - 1.0)
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TraversalPath:
    """遍历路径"""
    nodes: List[str]
    relations: List[MemoryRelation]
    total_strength: float = 0.0
    path_length: int = 0

    def __post_init__(self):
        self.path_length = len(self.nodes)
        if self.relations:
            self.total_strength = sum(r.strength for r in self.relations) / len(self.relations)

@dataclass
class TraversalResult:
    """遍历结果"""
    source_id: str
    paths: List[TraversalPath]
    reachable_ids: Set[str]
    max_depth: int

    @property
    def best_path(self) -> Optional[TraversalPath]:
        """最佳路径（强度最高的路径）"""
        if not self.paths:
            return None
        return max(self.paths, key=lambda p: p.total_strength)

    @property
    def best_reachable(self) -> Optional[str]:
        """最佳可达节点"""
        best = self.best_path
        if best and len(best.nodes) > 1:
            return best.nodes[-1]
        return None

class GraphTraversal:
    """图遍历引擎

    在记忆关联图上执行多跳推理。
    支持：
    - BFS 宽度优先搜索
    - DFS 深度优先搜索
    - 加权路径搜索
    - 循环检测
    """

    # 关系类型权重
    RELATION_WEIGHTS = {
        "related": 0.5,
        "causes": 0.8,
        "contradicts": 0.6,
        "supports": 0.9,
        "part_of": 0.7,
        "derived_from": 0.8,
        "temporal": 0.4,
    }

    def __init__(self,
                 max_depth: int = 3,
                 max_paths: int = 10,
                 min_strength: float = 0.1):
        """初始化图遍历引擎

        Args:
            max_depth: 最大跳数
            max_paths: 最大返回路径数
            min_strength: 最小关联强度阈值
        """
        self.max_depth = max_depth
        self.max_paths = max_paths
        self.min_strength = min_strength

        # 关联图: source_id → [(target_id, relation)]
        self._graph: Dict[str, List[Tuple[str, MemoryRelation]]] = defaultdict(list)
        # 反向图: target_id → [(source_id, relation)]
        self._reverse_graph: Dict[str, List[Tuple[str, MemoryRelation]]] = defaultdict(list)

        logger.debug(f"GraphTraversal 初始化: max_depth={max_depth}, max_paths={max_paths}")

    def add_relation(self, relation: MemoryRelation) -> None:
        """添加关联关系

        Args:
            relation: 关联关系
        """
        self._graph[relation.source_id].append((relation.target_id, relation))
        self._reverse_graph[relation.target_id].append((relation.source_id, relation))

    def add_relations(self, relations: List[MemoryRelation]) -> None:
        """批量添加关联关系

        Args:
            relations: 关联关系列表
        """
        for relation in relations:
            self.add_relation(relation)

    def get_relations(self, memory_id: str,
                     relation_type: Optional[str] = None,
                     direction: str = "both") -> List[MemoryRelation]:
        """获取记忆的关联关系

        Args:
            memory_id: 记忆ID
            relation_type: 关联类型过滤
            direction: 方向 ("outgoing", "incoming", "both")

        Returns:
            List[MemoryRelation]: 关联关系列表
        """
        relations = []

        if direction in ("outgoing", "both"):
            for target_id, rel in self._graph.get(memory_id, []):
                if relation_type is None or rel.relation_type == relation_type:
                    relations.append(rel)

        if direction in ("incoming", "both"):
            for source_id, rel in self._reverse_graph.get(memory_id, []):
                if relation_type is None or rel.relation_type == relation_type:
                    relations.append(rel)

        return relations

    def traverse_bfs(self, source_id: str) -> TraversalResult:
        """BFS 宽度优先遍历

        从源节点开始，逐层遍历关联记忆。

        Args:
            source_id: 源记忆ID

        Returns:
            TraversalResult: 遍历结果
        """
        visited: Set[str] = {source_id}
        queue: deque[Tuple[str, List[str], List[MemoryRelation], int]] = deque()
        queue.append((source_id, [source_id], [], 0))

        found_paths: List[TraversalPath] = []
        reachable_ids: Set[str] = set()

        while queue:
            current_id, path, relations, depth = queue.popleft()

            if depth >= self.max_depth:
                continue

            # 遍历邻居
            for neighbor_id, relation in self._graph.get(current_id, []):
                if neighbor_id in visited:
                    continue

                if relation.strength < self.min_strength:
                    continue

                visited.add(neighbor_id)
                reachable_ids.add(neighbor_id)

                new_path = path + [neighbor_id]
                new_relations = relations + [relation]

                if depth + 1 <= self.max_depth:
                    found_paths.append(TraversalPath(
                        nodes=new_path,
                        relations=new_relations,
                    ))

                    queue.append((neighbor_id, new_path, new_relations, depth + 1))

        # 排序：按强度降序
        found_paths.sort(key=lambda p: p.total_strength, reverse=True)
        found_paths = found_paths[:self.max_paths]

        return TraversalResult(
            source_id=source_id,
            paths=found_paths,
            reachable_ids=reachable_ids,
            max_depth=self.max_depth,
        )

    def traverse_dfs(self, source_id: str) -> TraversalResult:
        """DFS 深度优先遍历

        从源节点开始，深度优先遍历关联记忆。

        Args:
            source_id: 源记忆ID

        Returns:
            TraversalResult: 遍历结果
        """
        visited: Set[str] = {source_id}
        found_paths: List[TraversalPath] = []
        reachable_ids: Set[str] = set()

        def dfs(current_id: str, path: List[str], relations: List[MemoryRelation], depth: int):
            if depth >= self.max_depth:
                return

            for neighbor_id, relation in self._graph.get(current_id, []):
                if neighbor_id in visited:
                    continue

                if relation.strength < self.min_strength:
                    continue

                visited.add(neighbor_id)
                reachable_ids.add(neighbor_id)

                new_path = path + [neighbor_id]
                new_relations = relations + [relation]

                found_paths.append(TraversalPath(
                    nodes=new_path,
                    relations=new_relations,
                ))

                dfs(neighbor_id, new_path, new_relations, depth + 1)
                visited.remove(neighbor_id)  # 允许其他路径访问

        dfs(source_id, [source_id], [], 0)

        # 排序：按强度降序
        found_paths.sort(key=lambda p: p.total_strength, reverse=True)
        found_paths = found_paths[:self.max_paths]

        return TraversalResult(
            source_id=source_id,
            paths=found_paths,
            reachable_ids=reachable_ids,
            max_depth=self.max_depth,
        )

    def find_path(self, source_id: str, target_id: str) -> Optional[TraversalPath]:
        """查找两个记忆之间的路径

        Args:
            source_id: 源记忆ID
            target_id: 目标记忆ID

        Returns:
            Optional[TraversalPath]: 最短路径（如果存在）
        """
        if source_id == target_id:
            return TraversalPath(nodes=[source_id], relations=[])

        visited: Set[str] = {source_id}
        queue: deque[Tuple[str, List[str], List[MemoryRelation]]] = deque()
        queue.append((source_id, [source_id], []))

        while queue:
            current_id, path, relations = queue.popleft()

            for neighbor_id, relation in self._graph.get(current_id, []):
                if neighbor_id == target_id:
                    return TraversalPath(
                        nodes=path + [neighbor_id],
                        relations=relations + [relation],
                    )

                if neighbor_id not in visited and relation.strength >= self.min_strength:
                    visited.add(neighbor_id)
                    queue.append((neighbor_id, path + [neighbor_id], relations + [relation]))

        return None

    def get_memory_context(self, memory_id: str, depth: int = 1) -> Dict[str, Any]:
        """获取记忆的上下文信息（用于LLM推理）

        返回记忆及其直接关联记忆的摘要信息。

        Args:
            memory_id: 记忆ID
            depth: 遍历深度

        Returns:
            Dict[str, Any]: 上下文信息
        """
        # 获取直接关联
        outgoing = self.get_relations(memory_id, direction="outgoing")
        incoming = self.get_relations(memory_id, direction="incoming")

        return {
            "memory_id": memory_id,
            "outgoing_relations": [
                {
                    "target_id": r.target_id,
                    "type": r.relation_type,
                    "strength": r.strength,
                }
                for r in outgoing
            ],
            "incoming_relations": [
                {
                    "source_id": r.source_id,
                    "type": r.relation_type,
                    "strength": r.strength,
                }
                for r in incoming
            ],
            "total_outgoing": len(outgoing),
            "total_incoming": len(incoming),
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取图遍历统计信息

        Returns:
            Dict[str, Any]: 统计信息
        """
        total_nodes = len(set(list(self._graph.keys()) + list(self._reverse_graph.keys())))
        total_edges = sum(len(rels) for rels in self._graph.values())

        return {
            "total_nodes": total_nodes,
            "total_edges": total_edges,
            "max_depth": self.max_depth,
            "max_paths": self.max_paths,
            "min_strength": self.min_strength,
        }