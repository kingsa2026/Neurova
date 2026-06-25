"""
图遍历检索模块

利用记忆间的关联关系（MemoryRelation表）进行多跳推理。
支持：
- 多跳路径搜索
- 关联强度加权
- 路径排名
- 循环检测
"""

from neurova.core.logger import get_logger
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

logger = get_logger(__name__)


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
        # 原有关系类型
        "related": 0.5,
        "causes": 0.8,
        "contradicts": 0.6,
        "supports": 0.9,
        "part_of": 0.7,
        "derived_from": 0.8,
        "temporal": 0.4,
        # 新增因果关系
        "caused_by": 0.9,
        "enables": 0.7,
        "enabled_by": 0.7,
        "prevents": 0.8,
        "prevented_by": 0.8,
        "requires": 0.6,
        # 新增演化关系
        "evolves_to": 0.8,
        "evolved_from": 0.8,
        "replaces": 0.7,
        "replaced_by": 0.7,
        "version_of": 0.6,
        # 新增层次关系
        "part_of_hierarchy": 0.5,
        "contains": 0.5,
        "instance_of": 0.6,
        "type_of": 0.6,
        # 新增语义关系
        "synonym": 0.9,
        "antonym": 0.8,
        "hypernym": 0.7,
        "hyponym": 0.7,
    }

    def __init__(self, max_depth: int = 3, max_paths: int = 10, min_strength: float = 0.1):
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

        logger.debug("GraphTraversal 初始化: max_depth=%s, max_paths=%s", max_depth, max_paths)

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

    def get_relations(
        self, memory_id: str, relation_type: Optional[str] = None, direction: str = "both"
    ) -> List[MemoryRelation]:
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
                    found_paths.append(
                        TraversalPath(
                            nodes=new_path,
                            relations=new_relations,
                        )
                    )

                    queue.append((neighbor_id, new_path, new_relations, depth + 1))

        # 排序：按强度降序
        found_paths.sort(key=lambda p: p.total_strength, reverse=True)
        found_paths = found_paths[: self.max_paths]

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

                found_paths.append(
                    TraversalPath(
                        nodes=new_path,
                        relations=new_relations,
                    )
                )

                dfs(neighbor_id, new_path, new_relations, depth + 1)
                visited.remove(neighbor_id)  # 允许其他路径访问

        dfs(source_id, [source_id], [], 0)

        # 排序：按强度降序
        found_paths.sort(key=lambda p: p.total_strength, reverse=True)
        found_paths = found_paths[: self.max_paths]

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

    def probabilistic_beam_search(
        self, start_ids: List[str], query_vector: List[float] = None, beam_width: int = 3, max_depth: int = 3
    ) -> TraversalResult:
        """概率束搜索算法

        使用束搜索策略在图中查找最佳路径，支持向量相似度计算。

        Args:
            start_ids: 起始节点ID列表
            query_vector: 查询向量（可选）
            beam_width: 束宽度
            max_depth: 最大深度

        Returns:
            TraversalResult: 遍历结果
        """
        if not start_ids:
            return TraversalResult(
                source_id="",
                paths=[],
                reachable_ids=set(),
                max_depth=max_depth,
            )

        # 初始化束
        beams = []
        for start_id in start_ids:
            beams.append(
                {
                    "current_id": start_id,
                    "path": [start_id],
                    "relations": [],
                    "score": 1.0,
                    "depth": 0,
                }
            )

        all_paths = []
        reachable_ids = set()

        for _ in range(max_depth):
            if not beams:
                break

            new_beams = []

            for beam in beams:
                current_id = beam["current_id"]
                depth = beam["depth"]

                if depth >= max_depth:
                    all_paths.append(beam)
                    continue

                # 获取邻居
                neighbors = self._graph.get(current_id, [])

                for neighbor_id, relation in neighbors:
                    if neighbor_id in beam["path"]:  # 避免循环
                        continue

                    if relation.strength < self.min_strength:
                        continue

                    # 计算新分数
                    new_score = beam["score"] * relation.strength

                    # 如果有查询向量，考虑向量相似度
                    if query_vector is not None:
                        # 这里可以添加向量相似度计算
                        # 目前使用关系强度作为权重
                        pass

                    new_beam = {
                        "current_id": neighbor_id,
                        "path": beam["path"] + [neighbor_id],
                        "relations": beam["relations"] + [relation],
                        "score": new_score,
                        "depth": depth + 1,
                    }

                    new_beams.append(new_beam)
                    reachable_ids.add(neighbor_id)

            # 保留前 beam_width 个最佳路径
            new_beams.sort(key=lambda x: x["score"], reverse=True)
            beams = new_beams[:beam_width]

            # 将完成的路径添加到结果
            for beam in beams:
                if beam["depth"] >= max_depth:
                    all_paths.append(beam)

        # 将剩余的束添加到结果
        all_paths.extend(beams)

        # 转换为 TraversalPath 格式
        found_paths = []
        for beam in all_paths:
            found_paths.append(
                TraversalPath(
                    nodes=beam["path"],
                    relations=beam["relations"],
                )
            )

        # 按分数排序
        found_paths.sort(key=lambda p: p.total_strength, reverse=True)
        found_paths = found_paths[: self.max_paths]

        return TraversalResult(
            source_id=start_ids[0] if start_ids else "",
            paths=found_paths,
            reachable_ids=reachable_ids,
            max_depth=max_depth,
        )

    def compute_attention_weight(
        self, query_vector: List[float], node_vector: List[float], intent_weight: float = 1.0
    ) -> float:
        """计算注意力权重

        基于查询向量和节点向量计算注意力权重。

        Args:
            query_vector: 查询向量
            node_vector: 节点向量
            intent_weight: 意图权重

        Returns:
            float: 注意力权重 (0.0 - 1.0)
        """
        if not query_vector or not node_vector:
            return 0.5

        # 计算余弦相似度
        dot_product = sum(a * b for a, b in zip(query_vector, node_vector))
        norm_a = sum(a * a for a in query_vector) ** 0.5
        norm_b = sum(b * b for b in node_vector) ** 0.5

        if norm_a == 0 or norm_b == 0:
            return 0.0

        cosine_similarity = dot_product / (norm_a * norm_b)

        # 归一化到 [0, 1] 范围
        normalized_similarity = (cosine_similarity + 1) / 2

        # 应用意图权重
        weighted_similarity = normalized_similarity * intent_weight

        # 限制在 [0, 1] 范围内
        return max(0.0, min(1.0, weighted_similarity))

    def get_adaptive_params(self, query_type: str) -> Dict[str, Any]:
        """获取自适应遍历参数

        根据查询类型返回优化的遍历参数。

        Args:
            query_type: 查询类型 ("causal", "temporal", "comparative", "exploratory")

        Returns:
            Dict[str, Any]: 遍历参数
        """
        # 默认参数
        default_params = {
            "max_depth": 3,
            "max_paths": 10,
            "min_strength": 0.1,
            "beam_width": 3,
        }

        # 根据查询类型调整参数
        type_params = {
            "causal": {
                "max_depth": 4,  # 因果链可能需要更深
                "max_paths": 8,
                "min_strength": 0.2,  # 因果关系需要更强的连接
                "beam_width": 4,
            },
            "temporal": {
                "max_depth": 3,
                "max_paths": 12,
                "min_strength": 0.15,
                "beam_width": 3,
                "time_decay": 0.8,  # 时间衰减因子
            },
            "comparative": {
                "max_depth": 2,  # 比较通常不需要太深
                "max_paths": 15,
                "min_strength": 0.1,
                "beam_width": 5,
                "diversity": 0.7,  # 多样性权重
            },
            "exploratory": {
                "max_depth": 3,
                "max_paths": 20,  # 探索需要更多结果
                "min_strength": 0.05,  # 允许更弱的连接
                "beam_width": 6,
                "serendipity": 0.3,  # 偶然发现权重
            },
        }

        # 获取类型特定参数，如果没有则使用默认参数
        params = type_params.get(query_type, default_params)

        # 确保所有默认参数都存在
        for key, value in default_params.items():
            if key not in params:
                params[key] = value

        return params
