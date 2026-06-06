"""
RelationModule — 关系模块

管理记忆之间的关系网络
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class RelationType(str, Enum):
    """关系类型"""
    CAUSE = "cause"  # 因果关系
    SIMILAR = "similar"  # 相似关系
    TEMPORAL = "temporal"  # 时间关系
    SPATIAL = "spatial"  # 空间关系
    ASSOCIATION = "association"  # 联想关系
    PART_OF = "part_of"  # 部分关系
    SEQUENCE = "sequence"  # 序列关系


@dataclass
class Relation:
    """关系记录"""
    relation_id: str
    source_id: str
    target_id: str
    relation_type: RelationType
    strength: float  # 关系强度 [0, 1]
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "relation_id": self.relation_id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "relation_type": self.relation_type.value,
            "strength": self.strength,
            "metadata": self.metadata,
        }


class RelationModule:
    """
    关系模块
    
    管理记忆之间的关系网络，支持：
    - 关系创建和查询
    - 关系强度管理
    - 关系路径查找
    """
    
    def __init__(self):
        self._lock = threading.RLock()
        self._initialized = False
        
        # 关系存储
        self._relations: Dict[str, Relation] = {}  # relation_id -> Relation
        
        # 索引
        self._source_index: Dict[str, List[str]] = {}  # source_id -> [relation_ids]
        self._target_index: Dict[str, List[str]] = {}  # target_id -> [relation_ids]
        self._type_index: Dict[RelationType, List[str]] = {}  # type -> [relation_ids]
    
    @property
    def name(self) -> str:
        """模块名称"""
        return "relation_module"
    
    def init(self) -> bool:
        """初始化模块"""
        self._initialized = True
        logger.info("RelationModule initialized")
        return True
    
    def shutdown(self) -> None:
        """关闭模块"""
        self._initialized = False
        logger.info("RelationModule shutdown")
    
    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: RelationType,
        strength: float = 0.5,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Relation:
        """
        添加关系
        
        Args:
            source_id: 源记忆ID
            target_id: 目标记忆ID
            relation_type: 关系类型
            strength: 关系强度
            metadata: 额外元数据
            
        Returns:
            关系记录
        """
        relation_id = f"{source_id}_{relation_type.value}_{target_id}"
        
        relation = Relation(
            relation_id=relation_id,
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            strength=max(0.0, min(1.0, strength)),
            metadata=metadata or {},
        )
        
        with self._lock:
            self._relations[relation_id] = relation
            
            # 更新索引
            if source_id not in self._source_index:
                self._source_index[source_id] = []
            self._source_index[source_id].append(relation_id)
            
            if target_id not in self._target_index:
                self._target_index[target_id] = []
            self._target_index[target_id].append(relation_id)
            
            if relation_type not in self._type_index:
                self._type_index[relation_type] = []
            self._type_index[relation_type].append(relation_id)
        
        return relation
    
    def get_relation(self, relation_id: str) -> Optional[Relation]:
        """获取关系"""
        with self._lock:
            return self._relations.get(relation_id)
    
    def get_outgoing_relations(self, memory_id: str) -> List[Relation]:
        """获取从记忆出发的关系"""
        with self._lock:
            relation_ids = self._source_index.get(memory_id, [])
            return [self._relations[rid] for rid in relation_ids if rid in self._relations]
    
    def get_incoming_relations(self, memory_id: str) -> List[Relation]:
        """获取指向记忆的关系"""
        with self._lock:
            relation_ids = self._target_index.get(memory_id, [])
            return [self._relations[rid] for rid in relation_ids if rid in self._relations]
    
    def get_all_relations(self, memory_id: str) -> List[Relation]:
        """获取记忆的所有关系"""
        outgoing = self.get_outgoing_relations(memory_id)
        incoming = self.get_incoming_relations(memory_id)
        return outgoing + incoming
    
    def get_related_memories(
        self,
        memory_id: str,
        relation_type: Optional[RelationType] = None,
        min_strength: float = 0.0,
    ) -> List[str]:
        """
        获取相关记忆ID
        
        Args:
            memory_id: 记忆ID
            relation_type: 关系类型过滤
            min_strength: 最小强度
            
        Returns:
            相关记忆ID列表
        """
        with self._lock:
            related = set()
            
            # 从出发的关系
            for rid in self._source_index.get(memory_id, []):
                relation = self._relations.get(rid)
                if relation and relation.strength >= min_strength:
                    if relation_type is None or relation.relation_type == relation_type:
                        related.add(relation.target_id)
            
            # 从指向的关系
            for rid in self._target_index.get(memory_id, []):
                relation = self._relations.get(rid)
                if relation and relation.strength >= min_strength:
                    if relation_type is None or relation.relation_type == relation_type:
                        related.add(relation.source_id)
            
            return list(related)
    
    def get_relations_by_type(
        self,
        relation_type: RelationType,
        limit: int = 10,
    ) -> List[Relation]:
        """按类型获取关系"""
        with self._lock:
            relation_ids = self._type_index.get(relation_type, [])
            relations = [self._relations[rid] for rid in relation_ids if rid in self._relations]
            return relations[:limit]
    
    def find_path(
        self,
        start_id: str,
        end_id: str,
        max_depth: int = 3,
    ) -> Optional[List[str]]:
        """
        查找两个记忆之间的路径
        
        Args:
            start_id: 起始记忆ID
            end_id: 目标记忆ID
            max_depth: 最大深度
            
        Returns:
            路径（记忆ID列表），不存在返回 None
        """
        with self._lock:
            visited = set()
            queue = [(start_id, [start_id])]
            
            while queue:
                current_id, path = queue.pop(0)
                
                if current_id == end_id:
                    return path
                
                if len(path) > max_depth:
                    continue
                
                if current_id in visited:
                    continue
                
                visited.add(current_id)
                
                # 获取相邻记忆
                neighbors = self.get_related_memories(current_id)
                for neighbor in neighbors:
                    if neighbor not in visited:
                        queue.append((neighbor, path + [neighbor]))
            
            return None
    
    def update_strength(self, relation_id: str, new_strength: float) -> bool:
        """更新关系强度"""
        with self._lock:
            relation = self._relations.get(relation_id)
            if relation is None:
                return False
            
            relation.strength = max(0.0, min(1.0, new_strength))
            return True
    
    def remove_relation(self, relation_id: str) -> bool:
        """移除关系"""
        with self._lock:
            relation = self._relations.pop(relation_id, None)
            if relation is None:
                return False
            
            # 清理索引
            if relation.source_id in self._source_index:
                self._source_index[relation.source_id] = [
                    rid for rid in self._source_index[relation.source_id] if rid != relation_id
                ]
            
            if relation.target_id in self._target_index:
                self._target_index[relation.target_id] = [
                    rid for rid in self._target_index[relation.target_id] if rid != relation_id
                ]
            
            if relation.relation_type in self._type_index:
                self._type_index[relation.relation_type] = [
                    rid for rid in self._type_index[relation.relation_type] if rid != relation_id
                ]
            
            return True
    
    def remove_memory_relations(self, memory_id: str) -> int:
        """移除与记忆相关的所有关系"""
        with self._lock:
            relation_ids = set()
            
            # 收集所有相关关系
            for rid in self._source_index.get(memory_id, []):
                relation_ids.add(rid)
            for rid in self._target_index.get(memory_id, []):
                relation_ids.add(rid)
            
            # 移除关系
            count = 0
            for rid in relation_ids:
                if self.remove_relation(rid):
                    count += 1
            
            return count
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        with self._lock:
            type_counts = {t.value: len(ids) for t, ids in self._type_index.items()}
            
            return {
                "total_relations": len(self._relations),
                "by_type": type_counts,
                "memories_with_relations": len(self._source_index) + len(self._target_index),
            }
