"""依赖图谱 - 存储实体及其依赖关系

基于 MEEM 基准测试的 NEURON 架构核心组件。
支持 SQLite 持久化、内存索引、BFS/DFS 图查询、缓存机制。

运行时成本: $0（纯规则+图算法，无LLM调用）
"""

import json
from neurova.core.logger import get_logger
import sqlite3
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = get_logger(__name__)


# ────── Enums ──────


class DependencyType(Enum):
    """依赖关系类型"""
    CAUSAL = "causal"           # 因果关系: A导致B
    TEMPORAL = "temporal"       # 时序关系: A在B之前
    CONDITIONAL = "conditional" # 条件关系: 如果A则B
    HIERARCHICAL = "hierarchical"  # 层次关系: A包含B
    CONFLICT = "conflict"       # 冲突关系: A与B矛盾
    SUPPORT = "support"         # 支持关系: A支持B
    PREREQUISITE = "prerequisite"  # 前置条件: A是B的前提


# ────── Data Classes ──────


@dataclass
class EntityNode:
    """实体节点"""
    id: str
    name: str
    entity_type: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


@dataclass
class DependencyEdge:
    """依赖关系边"""
    id: str
    source_id: str
    target_id: str
    dep_type: DependencyType
    confidence: float = 1.0
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)


# ────── Main Graph ──────


class DependencyGraph:
    """
    依赖图谱 - SQLite 持久化的有向图

    Features:
        - 实体/边的增删查改
        - 下游/上游 BFS 遍历
        - 级联路径 DFS 搜索
        - 循环依赖检测
        - TTL 缓存机制
        - 线程安全 (RLock)
        - SQLite WAL 模式
    """

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path
        self._lock = threading.RLock()

        # 内存索引
        self.entities: Dict[str, EntityNode] = {}
        self.edges: List[DependencyEdge] = []
        self.adjacency: Dict[str, List[DependencyEdge]] = defaultdict(list)
        self.reverse_adjacency: Dict[str, List[DependencyEdge]] = defaultdict(list)
        self._edge_index: Dict[str, DependencyEdge] = {}

        # 缓存
        self._downstream_cache: Dict[str, Tuple[List[str], float]] = {}
        self._upstream_cache: Dict[str, Tuple[List[str], float]] = {}
        self._cache_ttl: float = 300  # 5 分钟

        # 持久化
        if db_path:
            self._init_db()
            self._load_from_db()
            logger.info("DependencyGraph 初始化完成 (db=%s, entities=%d, edges=%d)",
                        db_path, len(self.entities), len(self.edges))
        else:
            logger.info("DependencyGraph 初始化完成 (内存模式)")

    # ────── Database ──────

    def _init_db(self) -> None:
        """初始化 SQLite 数据库"""
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                created_at REAL,
                updated_at REAL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                dep_type TEXT NOT NULL,
                confidence REAL DEFAULT 1.0,
                evidence TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at REAL,
                FOREIGN KEY (source_id) REFERENCES entities(id),
                FOREIGN KEY (target_id) REFERENCES entities(id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)")
        conn.commit()
        conn.close()

    def _load_from_db(self) -> None:
        """从 SQLite 加载到内存"""
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            for row in conn.execute("SELECT * FROM entities"):
                self.entities[row["id"]] = EntityNode(
                    id=row["id"],
                    name=row["name"],
                    entity_type=row["entity_type"],
                    metadata=json.loads(row["metadata"] or "{}"),
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
            for row in conn.execute("SELECT * FROM edges"):
                edge = DependencyEdge(
                    id=row["id"],
                    source_id=row["source_id"],
                    target_id=row["target_id"],
                    dep_type=DependencyType(row["dep_type"]),
                    confidence=row["confidence"],
                    evidence=json.loads(row["evidence"] or "[]"),
                    metadata=json.loads(row["metadata"] or "{}"),
                    created_at=row["created_at"],
                )
                self.edges.append(edge)
                self.adjacency[edge.source_id].append(edge)
                self.reverse_adjacency[edge.target_id].append(edge)
                self._edge_index[edge.id] = edge
        finally:
            conn.close()

    def _save_entity_to_db(self, entity: EntityNode) -> None:
        """保存实体到 SQLite"""
        if not self._db_path:
            return
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO entities VALUES (?,?,?,?,?,?)",
                (entity.id, entity.name, entity.entity_type,
                 json.dumps(entity.metadata), entity.created_at, entity.updated_at)
            )
            conn.commit()
        finally:
            conn.close()

    def _save_edge_to_db(self, edge: DependencyEdge) -> None:
        """保存边到 SQLite"""
        if not self._db_path:
            return
        conn = sqlite3.connect(self._db_path)
        try:
            conn.execute(
                "INSERT OR REPLACE INTO edges VALUES (?,?,?,?,?,?,?,?)",
                (edge.id, edge.source_id, edge.target_id, edge.dep_type.value,
                 edge.confidence, json.dumps(edge.evidence),
                 json.dumps(edge.metadata), edge.created_at)
            )
            conn.commit()
        finally:
            conn.close()

    # ────── Entity Operations ──────

    def add_entity(self, entity: EntityNode) -> bool:
        """添加实体节点"""
        with self._lock:
            if not entity.id or not entity.name:
                logger.warning("实体 ID 或名称为空")
                return False

            if entity.id in self.entities:
                existing = self.entities[entity.id]
                existing.name = entity.name
                existing.entity_type = entity.entity_type
                existing.metadata.update(entity.metadata)
                existing.updated_at = time.time()
                self._save_entity_to_db(existing)
                return True

            self.entities[entity.id] = entity
            self._save_entity_to_db(entity)
            return True

    def get_entity(self, entity_id: str) -> Optional[EntityNode]:
        """获取实体"""
        return self.entities.get(entity_id)

    def remove_entity(self, entity_id: str) -> bool:
        """移除实体及其所有关联边"""
        with self._lock:
            if entity_id not in self.entities:
                return False

            del self.entities[entity_id]

            # 移除关联边
            outgoing = list(self.adjacency.get(entity_id, []))
            incoming = list(self.reverse_adjacency.get(entity_id, []))

            for edge in outgoing + incoming:
                self._remove_edge_internal(edge)

            self.adjacency.pop(entity_id, None)
            self.reverse_adjacency.pop(entity_id, None)

            return True

    # ────── Edge Operations ──────

    def add_dependency(self, edge: DependencyEdge) -> bool:
        """添加依赖关系边"""
        with self._lock:
            if not edge.source_id or not edge.target_id:
                logger.warning("边的 source_id 或 target_id 为空")
                return False

            if edge.id in self._edge_index:
                return False

            self.edges.append(edge)
            self.adjacency[edge.source_id].append(edge)
            self.reverse_adjacency[edge.target_id].append(edge)
            self._edge_index[edge.id] = edge

            self._save_edge_to_db(edge)
            self._invalidate_cache()
            return True

    def _remove_edge_internal(self, edge: DependencyEdge) -> None:
        """内部移除边（不加锁）"""
        if edge.id in self._edge_index:
            del self._edge_index[edge.id]

        if edge.source_id in self.adjacency:
            self.adjacency[edge.source_id] = [
                e for e in self.adjacency[edge.source_id] if e.id != edge.id
            ]

        if edge.target_id in self.reverse_adjacency:
            self.reverse_adjacency[edge.target_id] = [
                e for e in self.reverse_adjacency[edge.target_id] if e.id != edge.id
            ]

        self.edges = [e for e in self.edges if e.id != edge.id]

    def remove_dependency(self, edge_id: str) -> bool:
        """移除依赖关系边"""
        with self._lock:
            edge = self._edge_index.get(edge_id)
            if not edge:
                return False
            self._remove_edge_internal(edge)
            self._invalidate_cache()
            return True

    # ────── Query Operations ──────

    def get_downstream(self, entity_id: str, max_depth: int = 5) -> List[str]:
        """BFS 获取下游实体（受影响的实体）"""
        cache_key = f"down:{entity_id}:{max_depth}"
        cached = self._downstream_cache.get(cache_key)
        if cached:
            val, ts = cached
            if time.time() - ts < self._cache_ttl:
                return val

        if entity_id not in self.entities:
            return []

        visited = {entity_id}
        result: List[str] = []
        queue: deque = deque([(entity_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for edge in self.adjacency.get(current_id, []):
                if edge.target_id not in visited:
                    visited.add(edge.target_id)
                    result.append(edge.target_id)
                    queue.append((edge.target_id, depth + 1))

        self._downstream_cache[cache_key] = (result, time.time())
        return result

    def get_upstream(self, entity_id: str, max_depth: int = 5) -> List[str]:
        """BFS 获取上游实体（影响源实体）"""
        cache_key = f"up:{entity_id}:{max_depth}"
        cached = self._upstream_cache.get(cache_key)
        if cached:
            val, ts = cached
            if time.time() - ts < self._cache_ttl:
                return val

        if entity_id not in self.entities:
            return []

        visited = {entity_id}
        result: List[str] = []
        queue: deque = deque([(entity_id, 0)])

        while queue:
            current_id, depth = queue.popleft()
            if depth >= max_depth:
                continue

            for edge in self.reverse_adjacency.get(current_id, []):
                if edge.source_id not in visited:
                    visited.add(edge.source_id)
                    result.append(edge.source_id)
                    queue.append((edge.source_id, depth + 1))

        self._upstream_cache[cache_key] = (result, time.time())
        return result

    def find_cascade_paths(
        self, source_id: str, target_id: str, max_paths: int = 5
    ) -> List[List[str]]:
        """DFS 查找级联路径"""
        if source_id not in self.entities or target_id not in self.entities:
            return []

        paths: List[List[str]] = []
        visited: set = set()

        def dfs(current_id: str, path: List[str]) -> None:
            if len(paths) >= max_paths:
                return
            if current_id == target_id:
                paths.append(path.copy())
                return
            if current_id in visited:
                return
            visited.add(current_id)
            for edge in self.adjacency.get(current_id, []):
                path.append(edge.target_id)
                dfs(edge.target_id, path)
                path.pop()
            visited.remove(current_id)

        dfs(source_id, [source_id])
        return paths

    def detect_circular_dependencies(self) -> List[List[str]]:
        """检测循环依赖"""
        visited: set = set()
        recursion_stack: set = set()
        cycles: List[List[str]] = []

        def dfs(node: str, path: List[str]) -> None:
            visited.add(node)
            recursion_stack.add(node)
            path.append(node)
            for edge in self.adjacency.get(node, []):
                if edge.target_id not in visited:
                    dfs(edge.target_id, path)
                elif edge.target_id in recursion_stack:
                    cycle_start = path.index(edge.target_id)
                    cycles.append(path[cycle_start:] + [edge.target_id])
            path.pop()
            recursion_stack.remove(node)

        for node in list(self.entities.keys()):
            if node not in visited:
                dfs(node, [])

        return cycles

    def get_edges_between(self, source_id: str, target_id: str) -> List[DependencyEdge]:
        """获取两个实体之间的所有边"""
        return [
            edge for edge in self.adjacency.get(source_id, [])
            if edge.target_id == target_id
        ]

    def get_entity_degree(self, entity_id: str) -> Tuple[int, int]:
        """获取实体的入度和出度"""
        out_degree = len(self.adjacency.get(entity_id, []))
        in_degree = len(self.reverse_adjacency.get(entity_id, []))
        return in_degree, out_degree

    # ────── Cache ──────

    def _invalidate_cache(self) -> None:
        """清除所有缓存"""
        self._downstream_cache.clear()
        self._upstream_cache.clear()

    def clear_cache(self) -> int:
        """清除缓存并返回清除条目数"""
        count = len(self._downstream_cache) + len(self._upstream_cache)
        self._invalidate_cache()
        return count

    # ────── Stats ──────

    def get_stats(self) -> Dict[str, Any]:
        """获取图谱统计信息"""
        return {
            "entity_count": len(self.entities),
            "edge_count": len(self.edges),
            "cache_size": len(self._downstream_cache) + len(self._upstream_cache),
            "entity_types": self._count_entity_types(),
            "edge_types": self._count_edge_types(),
        }

    def _count_entity_types(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for entity in self.entities.values():
            counts[entity.entity_type] += 1
        return dict(counts)

    def _count_edge_types(self) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for edge in self.edges:
            counts[edge.dep_type.value] += 1
        return dict(counts)


# ────── Factory ──────

_graph_instance: Optional[DependencyGraph] = None
_graph_lock = threading.Lock()


def get_dependency_graph(db_path: Optional[str] = None) -> DependencyGraph:
    """获取 DependencyGraph 单例"""
    global _graph_instance
    if _graph_instance is None:
        with _graph_lock:
            if _graph_instance is None:
                _graph_instance = DependencyGraph(db_path=db_path)
    return _graph_instance


def reset_dependency_graph() -> None:
    """重置 DependencyGraph 单例"""
    global _graph_instance
    with _graph_lock:
        _graph_instance = None
