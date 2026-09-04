"""
知识图谱管理器

提供知识图谱的存储、查询、节点管理和图遍历功能。
基于内存存储的轻量级实现，支持线程安全和持久化。
"""

import json
from neurova.core.logger import get_logger
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = get_logger(__name__)


class NodeType(str, Enum):
    """节点类型"""

    CONCEPT = "concept"  # 概念
    ENTITY = "entity"  # 实体
    EVENT = "event"  # 事件
    MEMORY = "memory"  # 记忆
    SKILL = "skill"  # 技能
    TOOL = "tool"  # 工具
    PERSON = "person"  # 人物
    LOCATION = "location"  # 地点
    TIME = "time"  # 时间
    CUSTOM = "custom"  # 自定义


class RelationType(str, Enum):
    """关系类型"""

    IS_A = "is_a"  # 是一种
    HAS_A = "has_a"  # 拥有
    PART_OF = "part_of"  # 属于
    RELATED_TO = "related_to"  # 相关
    CAUSES = "causes"  # 导致
    SIMILAR_TO = "similar_to"  # 相似
    OPPOSITE_OF = "opposite_of"  # 相反
    TEMPORAL = "temporal"  # 时间关系
    SPATIAL = "spatial"  # 空间关系
    CAUSAL = "causal"  # 因果
    DEPENDS_ON = "depends_on"  # 依赖
    USED_BY = "used_by"  # 被使用
    CONTAINS = "contains"  # 包含
    CUSTOM = "custom"  # 自定义


@dataclass
class GraphNode:
    """图谱节点"""

    node_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    label: str = ""
    node_type: NodeType = NodeType.CONCEPT
    properties: Dict[str, Any] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "node_id": self.node_id,
            "label": self.label,
            "node_type": self.node_type.value,
            "properties": self.properties,
            "aliases": self.aliases,
            "tags": self.tags,
            "weight": self.weight,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        """从字典创建"""
        aliases = data.get("aliases", [])
        return cls(
            node_id=data.get("node_id", str(uuid.uuid4())),
            label=data.get("label", ""),
            node_type=NodeType(data.get("node_type", "concept")),
            properties=data.get("properties", {}),
            aliases=aliases if isinstance(aliases, list) else [],
            tags=data.get("tags", []),
            weight=data.get("weight", 1.0),
            created_at=data.get("created_at", time.time()),
            updated_at=data.get("updated_at", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class GraphEdge:
    """图谱边（关系）"""

    edge_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_id: str = ""
    target_id: str = ""
    relation_type: RelationType = RelationType.RELATED_TO
    label: str = ""
    weight: float = 1.0
    properties: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "edge_id": self.edge_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type.value,
            "label": self.label,
            "weight": self.weight,
            "properties": self.properties,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        """从字典创建"""
        return cls(
            edge_id=data.get("edge_id", str(uuid.uuid4())),
            source_id=data.get("source_id", ""),
            target_id=data.get("target_id", ""),
            relation_type=RelationType(data.get("relation_type", "related_to")),
            label=data.get("label", ""),
            weight=data.get("weight", 1.0),
            properties=data.get("properties", {}),
            created_at=data.get("created_at", time.time()),
            metadata=data.get("metadata", {}),
        )


@dataclass
class GraphPath:
    """图谱路径"""

    nodes: List[GraphNode] = field(default_factory=list)
    edges: List[GraphEdge] = field(default_factory=list)
    total_weight: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
            "total_weight": self.total_weight,
            "length": len(self.edges),
        }


@dataclass
class GraphStats:
    """图谱统计信息"""

    node_count: int = 0
    edge_count: int = 0
    node_type_counts: Dict[str, int] = field(default_factory=dict)
    relation_type_counts: Dict[str, int] = field(default_factory=dict)
    avg_degree: float = 0.0
    max_degree: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "node_type_counts": self.node_type_counts,
            "relation_type_counts": self.relation_type_counts,
            "avg_degree": round(self.avg_degree, 2),
            "max_degree": self.max_degree,
        }


class KnowledgeGraphManager:
    """
    知识图谱管理器

    特性:
    - 节点和边的增删改查
    - 多种查询方式（按类型、标签、属性）
    - 图遍历（BFS、DFS、最短路径）
    - 线程安全
    - JSON 持久化
    - 子图提取

    使用示例:
        kg = KnowledgeGraphManager(storage_dir="./data/knowledge_graph")
        node = kg.add_node(label="Python", node_type=NodeType.CONCEPT, tags=["programming"])
        kg.add_edge(source_id=node.node_id, target_id=other_node.node_id, relation_type=RelationType.RELATED_TO)
        neighbors = kg.get_neighbors(node.node_id)
    """

    def __init__(
        self,
        storage_dir: Optional[str] = None,
        auto_save: bool = True,
    ):
        """
        初始化知识图谱管理器

        Args:
            storage_dir: 存储目录
            auto_save: 修改后自动保存
        """
        self._storage_dir = Path(storage_dir) if storage_dir else None
        self._auto_save = auto_save

        # 节点和边的存储
        self._nodes: Dict[str, GraphNode] = {}
        self._edges: Dict[str, GraphEdge] = {}

        # 索引
        self._node_type_index: Dict[str, Set[str]] = defaultdict(set)
        self._label_index: Dict[str, Set[str]] = defaultdict(set)
        self._tag_index: Dict[str, Set[str]] = defaultdict(set)
        self._adjacency: Dict[str, Set[str]] = defaultdict(set)  # node_id -> edge_ids
        self._source_index: Dict[str, Set[str]] = defaultdict(set)  # source_id -> edge_ids
        self._target_index: Dict[str, Set[str]] = defaultdict(set)  # target_id -> edge_ids

        # 线程安全
        self._lock = threading.RLock()

        # P1-1 实体消解合并台账：source_id -> {target_id, moved_edge_ids,
        # source_snapshot, reason, merged_at}。独立结构而非删除——undo 按
        # 名单原路读回，此前已删的边不在名单不会被误救（Utopia 0005）。
        self._merge_log: Dict[str, Dict[str, Any]] = {}

        # 加载已有数据
        if self._storage_dir:
            self._storage_dir.mkdir(parents=True, exist_ok=True)
            self._load()

        logger.info("KnowledgeGraphManager initialized: %s nodes, %s edges", len(self._nodes), len(self._edges))

    def _load(self):
        """从存储加载数据"""
        if not self._storage_dir:
            return

        nodes_file = self._storage_dir / "nodes.json"
        edges_file = self._storage_dir / "edges.json"
        merges_file = self._storage_dir / "merges.json"

        if merges_file.exists():
            try:
                data = json.loads(merges_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self._merge_log = {k: v for k, v in data.items() if isinstance(v, dict)}
            except Exception as e:
                logger.warning("Failed to load merge log: %s", e)

        if nodes_file.exists():
            try:
                data = json.loads(nodes_file.read_text(encoding="utf-8"))
                for node_data in data:
                    node = GraphNode.from_dict(node_data)
                    self._nodes[node.node_id] = node
                    self._node_type_index[node.node_type.value].add(node.node_id)
                    self._label_index[node.label.lower()].add(node.node_id)
                    for tag in node.tags:
                        self._tag_index[tag.lower()].add(node.node_id)
            except Exception as e:
                logger.warning("Failed to load nodes: %s", e)

        if edges_file.exists():
            try:
                data = json.loads(edges_file.read_text(encoding="utf-8"))
                for edge_data in data:
                    edge = GraphEdge.from_dict(edge_data)
                    self._edges[edge.edge_id] = edge
                    self._adjacency[edge.source_id].add(edge.edge_id)
                    self._adjacency[edge.target_id].add(edge.edge_id)
                    self._source_index[edge.source_id].add(edge.edge_id)
                    self._target_index[edge.target_id].add(edge.edge_id)
            except Exception as e:
                logger.warning("Failed to load edges: %s", e)

    def _save(self):
        """保存数据到存储"""
        if not self._storage_dir or not self._auto_save:
            return

        try:
            nodes_file = self._storage_dir / "nodes.json"
            edges_file = self._storage_dir / "edges.json"

            nodes_data = [node.to_dict() for node in self._nodes.values()]
            edges_data = [edge.to_dict() for edge in self._edges.values()]

            nodes_file.write_text(
                json.dumps(nodes_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            edges_file.write_text(
                json.dumps(edges_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save knowledge graph: %s", e)

    def _save_merges(self):
        """合并台账持久化（与 nodes/edges 分文件， undo 依赖它）。"""
        if not self._storage_dir or not self._auto_save:
            return
        try:
            merges_file = self._storage_dir / "merges.json"
            merges_file.write_text(
                json.dumps(self._merge_log, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("Failed to save merge log: %s", e)

    def _rebuild_indexes(self):
        """重建索引"""
        self._node_type_index.clear()
        self._label_index.clear()
        self._tag_index.clear()
        self._adjacency.clear()
        self._source_index.clear()
        self._target_index.clear()

        for node in self._nodes.values():
            self._node_type_index[node.node_type.value].add(node.node_id)
            self._label_index[node.label.lower()].add(node.node_id)
            for tag in node.tags:
                self._tag_index[tag.lower()].add(node.node_id)

        for edge in self._edges.values():
            self._adjacency[edge.source_id].add(edge.edge_id)
            self._adjacency[edge.target_id].add(edge.edge_id)
            self._source_index[edge.source_id].add(edge.edge_id)
            self._target_index[edge.target_id].add(edge.edge_id)

    # ============================================================
    # 节点操作
    # ============================================================

    def add_node(
        self,
        label: str,
        node_type: NodeType = NodeType.CONCEPT,
        properties: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        weight: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GraphNode:
        """
        添加节点

        Args:
            label: 节点标签
            node_type: 节点类型
            properties: 属性
            tags: 标签列表
            weight: 权重
            metadata: 元数据

        Returns:
            创建的节点
        """
        with self._lock:
            node = GraphNode(
                label=label,
                node_type=node_type,
                properties=properties or {},
                tags=tags or [],
                weight=weight,
                metadata=metadata or {},
            )
            self._nodes[node.node_id] = node

            # 更新索引
            self._node_type_index[node_type.value].add(node.node_id)
            self._label_index[label.lower()].add(node.node_id)
            for tag in node.tags:
                self._tag_index[tag.lower()].add(node.node_id)

            self._save()
            return node

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        """
        获取节点

        Args:
            node_id: 节点 ID

        Returns:
            节点或 None
        """
        with self._lock:
            return self._nodes.get(node_id)

    def update_node(
        self,
        node_id: str,
        label: Optional[str] = None,
        properties: Optional[Dict[str, Any]] = None,
        tags: Optional[List[str]] = None,
        weight: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[GraphNode]:
        """
        更新节点

        Args:
            node_id: 节点 ID
            label: 新标签
            properties: 新属性
            tags: 新标签列表
            weight: 新权重
            metadata: 新元数据

        Returns:
            更新后的节点或 None
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return None

            if label is not None:
                self._label_index[node.label.lower()].discard(node_id)
                node.label = label
                self._label_index[label.lower()].add(node_id)

            if properties is not None:
                node.properties.update(properties)

            if tags is not None:
                for old_tag in node.tags:
                    self._tag_index[old_tag.lower()].discard(node_id)
                node.tags = tags
                for tag in tags:
                    self._tag_index[tag.lower()].add(node_id)

            if weight is not None:
                node.weight = weight

            if metadata is not None:
                node.metadata.update(metadata)

            node.updated_at = time.time()
            self._save()
            return node

    def delete_node(self, node_id: str) -> bool:
        """
        删除节点（同时删除相关边）

        Args:
            node_id: 节点 ID

        Returns:
            是否删除成功
        """
        with self._lock:
            node = self._nodes.pop(node_id, None)
            if not node:
                return False

            # 删除相关边
            edge_ids = list(self._adjacency.get(node_id, set()))
            for edge_id in edge_ids:
                self._edges.pop(edge_id, None)

            # 更新索引
            self._node_type_index[node.node_type.value].discard(node_id)
            self._label_index[node.label.lower()].discard(node_id)
            for tag in node.tags:
                self._tag_index[tag.lower()].discard(node_id)
            self._adjacency.pop(node_id, None)
            self._source_index.pop(node_id, None)
            self._target_index.pop(node_id, None)

            # 清理其他节点的邻接表
            for edge_id in edge_ids:
                edge = self._edges.get(edge_id)
                if edge:
                    self._adjacency[edge.source_id].discard(edge_id)
                    self._adjacency[edge.target_id].discard(edge_id)
                    self._source_index[edge.source_id].discard(edge_id)
                    self._target_index[edge.target_id].discard(edge_id)

            self._save()
            return True

    # ============================================================
    # P1-1 实体消解：合并原语（可回滚，Utopia 0005 裁剪版）
    # ============================================================

    def merge_nodes(self, source_id: str, target_id: str, reason: str = "") -> bool:
        """source 并入 target：source 出图（快照进台账），触及边端点原位改挂
        target；并入后成自环的边摘除入名单。undo_merge 按名单原路读回。"""
        with self._lock:
            src = self._nodes.get(source_id)
            dst = self._nodes.get(target_id)
            if not src or not dst or source_id == target_id:
                return False

            moved: Dict[str, Dict[str, str]] = {}
            dropped: Dict[str, Dict[str, Any]] = {}
            for edge_id in list(self._adjacency.get(source_id, set())):
                edge = self._edges.get(edge_id)
                if not edge:
                    continue
                orig = {"orig_source": edge.source_id, "orig_target": edge.target_id}
                new_source = target_id if edge.source_id == source_id else edge.source_id
                new_target = target_id if edge.target_id == source_id else edge.target_id
                if new_source == new_target:
                    # 并入即自环：从图摘除，undo 时原路放回
                    dropped[edge_id] = edge.to_dict()
                    self._edges.pop(edge_id, None)
                    continue
                moved[edge_id] = orig
                edge.source_id = new_source
                edge.target_id = new_target

            # source 出图（索引清理与 delete_node 同法）
            self._node_type_index[src.node_type.value].discard(source_id)
            self._label_index[src.label.lower()].discard(source_id)
            for tag in src.tags:
                self._tag_index[tag.lower()].discard(source_id)
            self._adjacency.pop(source_id, None)
            self._source_index.pop(source_id, None)
            self._target_index.pop(source_id, None)
            self._nodes.pop(source_id, None)
            self._rebuild_indexes()

            self._merge_log[source_id] = {
                "target_id": target_id,
                "source_snapshot": src.to_dict(),
                "moved_edges": moved,
                "dropped_edges": dropped,
                "reason": str(reason or ""),
                "merged_at": time.time(),
            }
            self._save()
            self._save_merges()
            return True

    def undo_merge(self, source_id: str) -> bool:
        """按台账把 source 原路读回：节点复活、moved 边端点翻回原值、dropped
        边放回。边已被第三方删除/再次改挂的不在补救范围（现存为准）。"""
        with self._lock:
            rec = self._merge_log.get(source_id)
            if not rec:
                return False

            node = GraphNode.from_dict(rec.get("source_snapshot") or {})
            self._nodes[node.node_id] = node
            self._node_type_index[node.node_type.value].add(node.node_id)
            self._label_index[node.label.lower()].add(node.node_id)
            for tag in node.tags:
                self._tag_index[tag.lower()].add(node.node_id)

            for edge_id, orig in (rec.get("moved_edges") or {}).items():
                edge = self._edges.get(edge_id)
                if edge is None:
                    continue
                if edge.source_id == rec.get("target_id"):
                    edge.source_id = orig["orig_source"]
                if edge.target_id == rec.get("target_id"):
                    edge.target_id = orig["orig_target"]
            for edge_id, snapshot in (rec.get("dropped_edges") or {}).items():
                if edge_id in self._edges:
                    continue
                edge = GraphEdge.from_dict(snapshot)
                self._edges[edge.edge_id] = edge

            del self._merge_log[source_id]
            self._rebuild_indexes()
            self._save()
            self._save_merges()
            return True

    def search_nodes(
        self,
        query: str,
        node_type: Optional[NodeType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[GraphNode]:
        """
        搜索节点

        Args:
            query: 搜索查询（匹配标签）
            node_type: 节点类型过滤
            tags: 标签过滤
            limit: 返回数量限制

        Returns:
            匹配的节点列表
        """
        with self._lock:
            candidates: Set[str] = set()
            query_lower = query.lower()

            # 按标签匹配
            for label, node_ids in self._label_index.items():
                if query_lower in label:
                    candidates.update(node_ids)

            # 按类型过滤
            if node_type:
                type_ids = self._node_type_index.get(node_type.value, set())
                candidates &= type_ids

            # 按标签过滤
            if tags:
                for tag in tags:
                    tag_ids = self._tag_index.get(tag.lower(), set())
                    if candidates:
                        candidates &= tag_ids

            results = [self._nodes[nid] for nid in candidates if nid in self._nodes]
            # 已并入其他节点的实体不出现在检索（merge_nodes 时已出图，此为
            # 台账旁路/加载竞态的双保险）
            results = [n for n in results if n.node_id not in self._merge_log]
            results.sort(key=lambda n: n.weight, reverse=True)
            return results[:limit]

    def get_nodes_by_type(
        self,
        node_type: NodeType,
        limit: int = 100,
    ) -> List[GraphNode]:
        """
        按类型获取节点

        Args:
            node_type: 节点类型
            limit: 返回数量限制

        Returns:
            节点列表
        """
        with self._lock:
            node_ids = self._node_type_index.get(node_type.value, set())
            nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
            return nodes[:limit]

    def get_nodes_by_tag(self, tag: str, limit: int = 100) -> List[GraphNode]:
        """
        按标签获取节点

        Args:
            tag: 标签
            limit: 返回数量限制

        Returns:
            节点列表
        """
        with self._lock:
            node_ids = self._tag_index.get(tag.lower(), set())
            nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
            return nodes[:limit]

    def get_node_details(self, node_id: str) -> Optional[Dict[str, Any]]:
        """
        获取节点详情（包括连接的边和邻居节点）

        Args:
            node_id: 节点 ID

        Returns:
            节点详情字典或 None
        """
        with self._lock:
            node = self._nodes.get(node_id)
            if not node:
                return None

            # 获取关联的边
            edge_ids = self._adjacency.get(node_id, set())
            edges = [self._edges[eid].to_dict() for eid in edge_ids if eid in self._edges]

            # 获取邻居节点
            neighbor_ids = set()
            for eid in edge_ids:
                edge = self._edges.get(eid)
                if edge:
                    if edge.source_id == node_id:
                        neighbor_ids.add(edge.target_id)
                    else:
                        neighbor_ids.add(edge.source_id)

            neighbors = [self._nodes[nid].to_dict() for nid in neighbor_ids if nid in self._nodes]

            return {
                "node": node.to_dict(),
                "edges": edges,
                "neighbors": neighbors,
                "degree": len(edge_ids),
            }

    # ============================================================
    # 边操作
    # ============================================================

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType = RelationType.RELATED_TO,
        label: str = "",
        weight: float = 1.0,
        properties: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[GraphEdge]:
        """
        添加边

        Args:
            source_id: 源节点 ID
            target_id: 目标节点 ID
            relation_type: 关系类型
            label: 标签
            weight: 权重
            properties: 属性
            metadata: 元数据

        Returns:
            创建的边或 None
        """
        with self._lock:
            if source_id not in self._nodes or target_id not in self._nodes:
                logger.warning("Cannot add edge: node not found (%s or %s)", source_id, target_id)
                return None

            edge = GraphEdge(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                label=label,
                weight=weight,
                properties=properties or {},
                metadata=metadata or {},
            )
            self._edges[edge.edge_id] = edge

            # 更新索引
            self._adjacency[source_id].add(edge.edge_id)
            self._adjacency[target_id].add(edge.edge_id)
            self._source_index[source_id].add(edge.edge_id)
            self._target_index[target_id].add(edge.edge_id)

            self._save()
            return edge

    def get_edge(self, edge_id: str) -> Optional[GraphEdge]:
        """获取边"""
        with self._lock:
            return self._edges.get(edge_id)

    def delete_edge(self, edge_id: str) -> bool:
        """
        删除边

        Args:
            edge_id: 边 ID

        Returns:
            是否删除成功
        """
        with self._lock:
            edge = self._edges.pop(edge_id, None)
            if not edge:
                return False

            self._adjacency[edge.source_id].discard(edge_id)
            self._adjacency[edge.target_id].discard(edge_id)
            self._source_index[edge.source_id].discard(edge_id)
            self._target_index[edge.target_id].discard(edge_id)

            self._save()
            return True

    def get_edges_between(self, source_id: str, target_id: str) -> List[GraphEdge]:
        """获取两个节点之间的所有边"""
        with self._lock:
            source_edges = self._source_index.get(source_id, set())
            target_edges = self._target_index.get(target_id, set())
            common = source_edges & target_edges
            return [self._edges[eid] for eid in common if eid in self._edges]

    def get_neighbors(
        self,
        node_id: str,
        direction: str = "both",
        relation_type: Optional[RelationType] = None,
    ) -> List[GraphNode]:
        """
        获取邻居节点

        Args:
            node_id: 节点 ID
            direction: 方向（out/in/both）
            relation_type: 关系类型过滤

        Returns:
            邻居节点列表
        """
        with self._lock:
            edge_ids = self._adjacency.get(node_id, set())
            neighbor_ids = set()

            for eid in edge_ids:
                edge = self._edges.get(eid)
                if not edge:
                    continue

                if relation_type and edge.relation_type != relation_type:
                    continue

                if direction in ("out", "both") and edge.source_id == node_id:
                    neighbor_ids.add(edge.target_id)
                if direction in ("in", "both") and edge.target_id == node_id:
                    neighbor_ids.add(edge.source_id)

            return [self._nodes[nid] for nid in neighbor_ids if nid in self._nodes]

    # ============================================================
    # 图遍历
    # ============================================================

    def bfs(
        self,
        start_id: str,
        max_depth: int = 3,
        relation_type: Optional[RelationType] = None,
    ) -> List[GraphNode]:
        """
        广度优先遍历

        Args:
            start_id: 起始节点 ID
            max_depth: 最大深度
            relation_type: 关系类型过滤

        Returns:
            遍历到的节点列表
        """
        with self._lock:
            if start_id not in self._nodes:
                return []

            visited = {start_id}
            queue = deque([(start_id, 0)])
            result = []

            while queue:
                node_id, depth = queue.popleft()
                if depth > max_depth:
                    continue

                result.append(self._nodes[node_id])

                for eid in self._adjacency.get(node_id, set()):
                    edge = self._edges.get(eid)
                    if not edge:
                        continue
                    if relation_type and edge.relation_type != relation_type:
                        continue

                    neighbor_id = edge.target_id if edge.source_id == node_id else edge.source_id
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        queue.append((neighbor_id, depth + 1))

            return result

    def find_shortest_path(
        self,
        start_id: str,
        end_id: str,
    ) -> Optional[GraphPath]:
        """
        查找最短路径（BFS）

        Args:
            start_id: 起始节点 ID
            end_id: 结束节点 ID

        Returns:
            最短路径或 None
        """
        with self._lock:
            if start_id not in self._nodes or end_id not in self._nodes:
                return None

            if start_id == end_id:
                return GraphPath(
                    nodes=[self._nodes[start_id]],
                    edges=[],
                    total_weight=0.0,
                )

            visited = {start_id}
            queue = deque([(start_id, [start_id], [])])

            while queue:
                current, path_nodes, path_edges = queue.popleft()

                for eid in self._adjacency.get(current, set()):
                    edge = self._edges.get(eid)
                    if not edge:
                        continue

                    neighbor = edge.target_id if edge.source_id == current else edge.source_id

                    if neighbor in visited:
                        continue

                    new_nodes = path_nodes + [neighbor]
                    new_edges = path_edges + [eid]

                    if neighbor == end_id:
                        nodes = [self._nodes[nid] for nid in new_nodes]
                        edges = [self._edges[eid] for eid in new_edges]
                        total_weight = sum(e.weight for e in edges)
                        return GraphPath(
                            nodes=nodes,
                            edges=edges,
                            total_weight=total_weight,
                        )

                    visited.add(neighbor)
                    queue.append((neighbor, new_nodes, new_edges))

            return None

    # ============================================================
    # 查询和统计
    # ============================================================

    def get_graph(
        self,
        node_type: Optional[NodeType] = None,
        tags: Optional[List[str]] = None,
        limit: int = 100,
    ) -> Dict[str, Any]:
        """
        获取图谱数据

        Args:
            node_type: 节点类型过滤
            tags: 标签过滤
            limit: 返回数量限制

        Returns:
            图谱数据字典
        """
        with self._lock:
            # 过滤节点
            if node_type:
                node_ids = self._node_type_index.get(node_type.value, set())
                nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
            elif tags:
                node_ids = set()
                for tag in tags:
                    node_ids |= self._tag_index.get(tag.lower(), set())
                nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
            else:
                nodes = list(self._nodes.values())

            nodes = nodes[:limit]

            # 获取相关边
            node_id_set = {n.node_id for n in nodes}
            edges = [
                edge for edge in self._edges.values() if edge.source_id in node_id_set and edge.target_id in node_id_set
            ]

            return {
                "nodes": [n.to_dict() for n in nodes],
                "edges": [e.to_dict() for e in edges],
                "stats": self.get_stats().to_dict(),
            }

    def get_stats(self) -> GraphStats:
        """获取图谱统计信息"""
        with self._lock:
            # 合并出图的节点不计入统计（台账旁路双保险）
            node_type_counts = {
                k: len(v - set(self._merge_log.keys())) for k, v in self._node_type_index.items()
            }
            relation_type_counts = {}
            degrees = defaultdict(int)

            for edge in self._edges.values():
                rt = edge.relation_type.value
                relation_type_counts[rt] = relation_type_counts.get(rt, 0) + 1
                degrees[edge.source_id] += 1
                degrees[edge.target_id] += 1

            avg_degree = sum(degrees.values()) / len(degrees) if degrees else 0.0
            max_degree = max(degrees.values()) if degrees else 0

            return GraphStats(
                node_count=len(self._nodes) - len(self._merge_log),
                edge_count=len(self._edges),
                node_type_counts=node_type_counts,
                relation_type_counts=relation_type_counts,
                avg_degree=avg_degree,
                max_degree=max_degree,
            )

    def get_subgraph(
        self,
        node_ids: List[str],
        include_edges: bool = True,
    ) -> Dict[str, Any]:
        """
        提取子图

        Args:
            node_ids: 节点 ID 列表
            include_edges: 是否包含边

        Returns:
            子图数据
        """
        with self._lock:
            nodes = [self._nodes[nid] for nid in node_ids if nid in self._nodes]
            node_id_set = set(node_ids)

            edges = []
            if include_edges:
                edges = [
                    edge
                    for edge in self._edges.values()
                    if edge.source_id in node_id_set and edge.target_id in node_id_set
                ]

            return {
                "nodes": [n.to_dict() for n in nodes],
                "edges": [e.to_dict() for e in edges],
            }

    def clear(self):
        """清空图谱"""
        with self._lock:
            self._nodes.clear()
            self._edges.clear()
            self._node_type_index.clear()
            self._label_index.clear()
            self._tag_index.clear()
            self._adjacency.clear()
            self._source_index.clear()
            self._target_index.clear()
            self._save()

    def __len__(self) -> int:
        """获取节点数量"""
        return len(self._nodes)

    def __repr__(self) -> str:
        """字符串表示"""
        return f"KnowledgeGraphManager(nodes={len(self._nodes)}, edges={len(self._edges)})"


# ============================================================
# 全局实例
# ============================================================

_global_manager: Optional[KnowledgeGraphManager] = None
_manager_lock = threading.Lock()


def get_knowledge_graph_manager(
    storage_dir: Optional[str] = None,
) -> KnowledgeGraphManager:
    """
    获取全局知识图谱管理器

    Args:
        storage_dir: 存储目录

    Returns:
        全局管理器实例
    """
    global _global_manager
    with _manager_lock:
        if _global_manager is None:
            _global_manager = KnowledgeGraphManager(
                storage_dir=storage_dir or "./data/knowledge_graph",
            )
        return _global_manager


def reset_knowledge_graph_manager():
    """重置全局管理器（用于测试）"""
    global _global_manager
    with _manager_lock:
        _global_manager = None
