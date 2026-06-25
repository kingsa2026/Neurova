"""
记忆关联 Mixin - 从 MemoryStorage 中提取的关联/关系图谱相关方法

提供记忆之间的关联建立、查询、删除和图结构漫游。
"""

import datetime
from neurova.core.logger import get_logger
import uuid
from typing import Any, Dict, List, Optional, Set, Tuple

logger = get_logger(__name__)


class RelationMixin:
    """
    记忆关联 Mixin

    提供记忆之间的关联建立、查询、删除和图结构漫游。
    """

    def __init__(self):
        """初始化记忆关联存储"""
        self._relations: Dict[str, Dict[str, Any]] = {}
        self._memory_relations: Dict[str, List[str]] = {}  # memory_id -> [relation_ids]
        logger.info("RelationMixin 初始化完成")

    def create_relation(
        self,
        source_memory_id: str,
        target_memory_id: str,
        relation_type: str = "related",
        strength: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        创建记忆关联

        Args:
            source_memory_id: 源记忆ID
            target_memory_id: 目标记忆ID
            relation_type: 关联类型
            strength: 关联强度
            metadata: 可选的元数据

        Returns:
            创建的关联
        """
        relation_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc)

        relation = {
            "id": relation_id,
            "source_memory_id": source_memory_id,
            "target_memory_id": target_memory_id,
            "relation_type": relation_type,
            "strength": strength,
            "metadata": metadata or {},
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }

        self._relations[relation_id] = relation

        # 更新索引
        if source_memory_id not in self._memory_relations:
            self._memory_relations[source_memory_id] = []
        self._memory_relations[source_memory_id].append(relation_id)

        if target_memory_id not in self._memory_relations:
            self._memory_relations[target_memory_id] = []
        self._memory_relations[target_memory_id].append(relation_id)

        logger.debug("创建关联: %s -> %s (%s)", source_memory_id, target_memory_id, relation_type)

        return relation

    def get_relation(self, relation_id: str) -> Optional[Dict[str, Any]]:
        """
        获取关联

        Args:
            relation_id: 关联ID

        Returns:
            关联数据
        """
        return self._relations.get(relation_id)

    def get_memory_relations(
        self,
        memory_id: str,
        direction: str = "both",
        relation_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取记忆的所有关联

        Args:
            memory_id: 记忆ID
            direction: 方向 (in, out, both)
            relation_type: 按关联类型过滤

        Returns:
            关联列表
        """
        if memory_id not in self._memory_relations:
            return []

        relation_ids = self._memory_relations[memory_id]
        results = []

        for rel_id in relation_ids:
            relation = self._relations.get(rel_id)
            if not relation:
                continue

            # 按方向过滤
            if direction == "out" and relation["source_memory_id"] != memory_id:
                continue
            if direction == "in" and relation["target_memory_id"] != memory_id:
                continue

            # 按类型过滤
            if relation_type and relation["relation_type"] != relation_type:
                continue

            results.append(relation)

        # 按强度排序
        results.sort(key=lambda x: x["strength"], reverse=True)

        return results

    def get_related_memories(
        self,
        memory_id: str,
        depth: int = 1,
        relation_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        获取关联的记忆（支持多层深度）

        Args:
            memory_id: 起始记忆ID
            depth: 搜索深度
            relation_type: 按关联类型过滤

        Returns:
            关联的记忆列表
        """
        visited: Set[str] = set()
        result: List[Dict[str, Any]] = []

        self._traverse_graph(memory_id, depth, relation_type, visited, result)

        return result

    def _traverse_graph(
        self,
        current_id: str,
        remaining_depth: int,
        relation_type: Optional[str],
        visited: Set[str],
        result: List[Dict[str, Any]],
    ) -> None:
        """递归遍历图"""
        if remaining_depth <= 0 or current_id in visited:
            return

        visited.add(current_id)

        # 获取直接关联
        relations = self.get_memory_relations(current_id, direction="both", relation_type=relation_type)

        for relation in relations:
            # 确定关联的记忆ID
            if relation["source_memory_id"] == current_id:
                related_id = relation["target_memory_id"]
            else:
                related_id = relation["source_memory_id"]

            if related_id not in visited:
                result.append(
                    {
                        "memory_id": related_id,
                        "relation": relation,
                        "depth": remaining_depth,
                    }
                )

                # 递归遍历
                self._traverse_graph(related_id, remaining_depth - 1, relation_type, visited, result)

    def update_relation(
        self,
        relation_id: str,
        strength: Optional[float] = None,
        relation_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        更新关联

        Args:
            relation_id: 关联ID
            strength: 新强度
            relation_type: 新类型
            metadata: 新元数据

        Returns:
            更新后的关联
        """
        relation = self._relations.get(relation_id)
        if not relation:
            return None

        if strength is not None:
            relation["strength"] = strength
        if relation_type is not None:
            relation["relation_type"] = relation_type
        if metadata is not None:
            relation["metadata"] = metadata

        relation["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        return relation

    def delete_relation(self, relation_id: str) -> bool:
        """
        删除关联

        Args:
            relation_id: 关联ID

        Returns:
            是否删除成功
        """
        relation = self._relations.get(relation_id)
        if not relation:
            return False

        source_id = relation["source_memory_id"]
        target_id = relation["target_memory_id"]

        # 从索引中移除
        if source_id in self._memory_relations:
            self._memory_relations[source_id] = [rid for rid in self._memory_relations[source_id] if rid != relation_id]

        if target_id in self._memory_relations:
            self._memory_relations[target_id] = [rid for rid in self._memory_relations[target_id] if rid != relation_id]

        # 删除关联
        del self._relations[relation_id]

        logger.debug("删除关联: %s", relation_id)

        return True

    def delete_memory_relations(self, memory_id: str) -> int:
        """
        删除记忆的所有关联

        Args:
            memory_id: 记忆ID

        Returns:
            删除的关联数量
        """
        if memory_id not in self._memory_relations:
            return 0

        relation_ids = self._memory_relations[memory_id].copy()

        for rel_id in relation_ids:
            self.delete_relation(rel_id)

        # 清空索引
        if memory_id in self._memory_relations:
            del self._memory_relations[memory_id]

        logger.debug("删除记忆 %s 的所有关联: %s 个", memory_id, len(relation_ids))

        return len(relation_ids)

    def find_path(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 5,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        查找两个记忆之间的路径

        Args:
            start_id: 起始记忆ID
            end_id: 目标记忆ID
            max_depth: 最大深度

        Returns:
            路径，如果不存在返回None
        """
        if start_id == end_id:
            return []

        # BFS 查找最短路径
        queue: List[Tuple[str, List[Dict[str, Any]]]] = [(start_id, [])]
        visited: Set[str] = {start_id}

        while queue:
            current_id, path = queue.pop(0)

            if len(path) >= max_depth:
                continue

            # 获取直接关联
            relations = self.get_memory_relations(current_id, direction="both")

            for relation in relations:
                if relation["source_memory_id"] == current_id:
                    next_id = relation["target_memory_id"]
                else:
                    next_id = relation["source_memory_id"]

                if next_id == end_id:
                    # 找到目标
                    return path + [relation]

                if next_id not in visited:
                    visited.add(next_id)
                    queue.append((next_id, path + [relation]))

        return None

    def get_relation_statistics(self) -> Dict[str, Any]:
        """
        获取关系统计信息

        Returns:
            统计信息字典
        """
        relations = list(self._relations.values())

        if not relations:
            return {
                "total_relations": 0,
                "type_distribution": {},
                "average_strength": 0,
                "most_connected_memories": [],
                "graph_density": 0,
            }

        # 类型分布
        type_dist: Dict[str, int] = {}
        for relation in relations:
            rt = relation["relation_type"]
            type_dist[rt] = type_dist.get(rt, 0) + 1

        # 平均强度
        total_strength = sum(r["strength"] for r in relations)
        avg_strength = total_strength / len(relations)

        # 最常连接的记忆
        memory_connection_count: Dict[str, int] = {}
        for relation in relations:
            src = relation["source_memory_id"]
            tgt = relation["target_memory_id"]
            memory_connection_count[src] = memory_connection_count.get(src, 0) + 1
            memory_connection_count[tgt] = memory_connection_count.get(tgt, 0) + 1

        most_connected = sorted(memory_connection_count.items(), key=lambda x: x[1], reverse=True)[:5]

        # 图密度
        memory_count = len(self._memory_relations)
        max_possible_relations = memory_count * (memory_count - 1) / 2
        graph_density = len(relations) / max_possible_relations if max_possible_relations > 0 else 0

        return {
            "total_relations": len(relations),
            "type_distribution": type_dist,
            "average_strength": avg_strength,
            "most_connected_memories": most_connected,
            "graph_density": graph_density,
            "unique_memories": memory_count,
        }

    def clear_relations(self) -> int:
        """
        清空所有关联

        Returns:
            删除的关联数量
        """
        count = len(self._relations)
        self._relations.clear()
        self._memory_relations.clear()

        logger.debug("清空所有关联: %s 个", count)

        return count
