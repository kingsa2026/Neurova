"""
GraphChannel — 图通道（关系图谱）

通过知识图谱进行检索，支持：
- 基于实体的图谱搜索
- BFS/DFS图遍历
- 最短路径查找
- 关联记忆检索

基于KnowledgeGraphManager实现。
"""

import logging
import re
from typing import Dict, List, Optional, Set

from ..base import BaseChannel, ChannelMetadata, ChannelResult

logger = logging.getLogger(__name__)


class GraphChannel(BaseChannel):
    """图通道：基于知识图谱检索关联记忆"""

    def __init__(self):
        super().__init__()
        self._knowledge_graph = None
        self._entity_cache: Dict[str, List[str]] = {}
    
    def set_knowledge_graph(self, knowledge_graph):
        """设置知识图谱管理器"""
        self._knowledge_graph = knowledge_graph
    
    @property
    def metadata(self) -> ChannelMetadata:
        return ChannelMetadata(
            name="graph",
            display_name="图通道",
            description="基于知识图谱检索关联记忆",
            capabilities=["graph", "relation", "entity", "path"],
        )

    async def retrieve(self, query: str, limit: int = 10, weight: float = 1.0, **kwargs) -> List[ChannelResult]:
        """
        基于图谱的检索
        
        Args:
            query: 查询文本
            limit: 返回结果数量
            weight: 权重
            **kwargs: 额外参数（memory_manager等）
        """
        memory_manager = kwargs.get("memory_manager")
        
        # 优先使用KnowledgeGraphManager
        if self._knowledge_graph:
            return self._retrieve_from_knowledge_graph(query, limit, weight)
        
        # 降级到简单的内存图谱
        if memory_manager:
            return self._retrieve_from_memory_relations(query, limit, weight, memory_manager)
        
        return []

    def _retrieve_from_knowledge_graph(
        self, 
        query: str, 
        limit: int, 
        weight: float,
    ) -> List[ChannelResult]:
        """从KnowledgeGraphManager检索"""
        results = []
        
        try:
            # 1. 从查询中提取实体
            entities = self._extract_entities(query)
            
            # 2. 在图谱中搜索匹配节点
            matched_nodes = []
            for entity in entities:
                nodes = self._knowledge_graph.search_nodes(entity)
                matched_nodes.extend(nodes)
            
            # 3. 限制种子节点数
            seed_nodes = matched_nodes[:5]
            
            # 4. BFS获取关联节点
            all_related = []
            for node in seed_nodes:
                related = self._knowledge_graph.bfs(node.node_id, max_depth=2)
                all_related.extend(related)
            
            # 5. 转换为ChannelResult
            seen_ids: Set[str] = set()
            for node in all_related:
                if node.node_id in seen_ids:
                    continue
                seen_ids.add(node.node_id)
                
                # 计算分数（基于权重和距离）
                score = node.weight * weight
                
                results.append(ChannelResult(
                    memory_id=node.node_id,
                    content=node.label,
                    score=score,
                    channel="graph",
                    metadata={
                        "node_type": node.node_type.value,
                        "tags": node.tags,
                        "properties": node.properties,
                    },
                ))
            
            # 6. 按分数排序
            results.sort(key=lambda x: x.score, reverse=True)
            
        except Exception as e:
            logger.warning("知识图谱检索失败: %s", e)
        
        return results[:limit]

    def _retrieve_from_memory_relations(
        self, 
        query: str, 
        limit: int, 
        weight: float,
        memory_manager,
    ) -> List[ChannelResult]:
        """从记忆关系中检索（降级方案）"""
        try:
            all_memories = memory_manager.get_all_memories()
            scored = []

            for mem in all_memories:
                relations = mem.get("metadata", {}).get("relations", [])
                content = mem.get("content", "")
                
                # 关系数量作为分数
                rel_count = len(relations) if isinstance(relations, list) else 0
                score = min(1.0, rel_count * 0.1) * weight

                scored.append(
                    ChannelResult(
                        memory_id=mem.get("id", ""),
                        content=content,
                        score=score,
                        channel="graph",
                        metadata={"relation_count": rel_count},
                    )
                )

            scored.sort(key=lambda m: m.score, reverse=True)
            return scored[:limit]

        except Exception as e:
            logger.debug("图通道检索失败: %s", e)
            return []

    def _extract_entities(self, text: str) -> List[str]:
        """从文本中提取实体"""
        entities = []
        
        # 英文人名
        name_pattern = r'\b[A-Z][a-z]+ [A-Z][a-z]+\b'
        entities.extend(re.findall(name_pattern, text))
        
        # 中文人名（简单规则：2-4个汉字 + 称谓）
        cn_name_pattern = r'[\u4e00-\u9fa5]{2,4}(?:老师|同学|先生|女士|教授|博士)'
        entities.extend(re.findall(cn_name_pattern, text))
        
        # 中文词语（2-4个汉字）
        if not entities:
            cn_word_pattern = r'[\u4e00-\u9fa5]{2,4}'
            entities.extend(re.findall(cn_word_pattern, text))
        
        # 去重
        return list(set(entities))
    
    def find_related_memories(
        self, 
        memory_id: str, 
        max_depth: int = 2,
        limit: int = 10,
    ) -> List[ChannelResult]:
        """
        查找关联记忆
        
        Args:
            memory_id: 起始记忆ID
            max_depth: 最大遍历深度
            limit: 返回结果数量
            
        Returns:
            List[ChannelResult]: 关联记忆列表
        """
        if not self._knowledge_graph:
            return []
        
        results = []
        
        try:
            # BFS获取关联节点
            related_nodes = self._knowledge_graph.bfs(memory_id, max_depth=max_depth)
            
            for node in related_nodes:
                if node.node_id == memory_id:
                    continue  # 跳过自身
                
                results.append(ChannelResult(
                    memory_id=node.node_id,
                    content=node.label,
                    score=node.weight,
                    channel="graph",
                    metadata={
                        "node_type": node.node_type.value,
                        "depth": max_depth,
                    },
                ))
            
            results.sort(key=lambda x: x.score, reverse=True)
            
        except Exception as e:
            logger.warning("查找关联记忆失败: %s", e)
        
        return results[:limit]
    
    def find_shortest_path(
        self, 
        from_id: str, 
        to_id: str,
    ) -> Optional[List[str]]:
        """
        查找两个节点间的最短路径
        
        Args:
            from_id: 起始节点ID
            to_id: 目标节点ID
            
        Returns:
            List[str]: 路径节点ID列表，如果不存在返回None
        """
        if not self._knowledge_graph:
            return None
        
        try:
            path_result = self._knowledge_graph.find_shortest_path(from_id, to_id)
            if path_result is None:
                return None
            # GraphPath对象包含nodes属性
            if hasattr(path_result, 'nodes'):
                return [node.node_id for node in path_result.nodes]
            # 如果是列表，直接返回
            if isinstance(path_result, list):
                return path_result
            return None
        except Exception as e:
            logger.warning("查找最短路径失败: %s", e)
            return None
