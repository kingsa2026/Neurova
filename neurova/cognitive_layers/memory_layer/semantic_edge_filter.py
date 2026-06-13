"""
语义边过滤器

为 DependencyEdge 添加语义描述，实现主动过滤。
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class EnhancedDependencyEdge:
    """增强的依赖关系边"""
    id: str
    source_id: str
    target_id: str
    dep_type: str
    confidence: float = 1.0
    evidence: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    
    # 新增字段
    description: str = ""          # 语义描述
    source_context: str = ""       # 提取来源上下文
    extraction_method: str = ""    # 提取方式
    last_verified: float = 0.0     # 最后验证时间戳
    verification_count: int = 0    # 验证次数
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "dep_type": self.dep_type,
            "confidence": self.confidence,
            "description": self.description,
            "source_context": self.source_context,
            "extraction_method": self.extraction_method,
            "created_at": self.created_at,
        }


class SemanticEdgeFilter:
    """语义边过滤器"""
    
    def __init__(self, embedding_model: Any = None):
        """
        初始化语义边过滤器
        
        Args:
            embedding_model: 嵌入模型（可选）
        """
        self.embedding_model = embedding_model
        logger.info("SemanticEdgeFilter 初始化完成")
    
    def filter_by_relevance(
        self, 
        edges: List[EnhancedDependencyEdge], 
        query: str,
        threshold: float = 0.5
    ) -> List[EnhancedDependencyEdge]:
        """
        根据查询语义相关性过滤边
        
        Args:
            edges: 边列表
            query: 查询文本
            threshold: 相似度阈值
            
        Returns:
            过滤后的边列表（按相似度排序）
        """
        if not self.embedding_model:
            # 无嵌入模型时返回所有边
            return edges
        
        # 获取查询嵌入
        try:
            query_embedding = self.embedding_model.encode(query)
        except Exception as e:
            logger.warning("获取查询嵌入失败: %s", e)
            return edges
        
        scored_edges = []
        
        for edge in edges:
            try:
                # 构建边的文本描述
                edge_text = f"{edge.source_id} {edge.dep_type} {edge.target_id}"
                if edge.description:
                    edge_text += f" {edge.description}"
                
                # 获取边的嵌入
                edge_embedding = self.embedding_model.encode(edge_text)
                
                # 计算相似度（余弦相似度）
                similarity = self._cosine_similarity(query_embedding, edge_embedding)
                
                if similarity >= threshold:
                    scored_edges.append((edge, similarity))
            except Exception as e:
                logger.warning("计算边相似度失败: %s", e)
                # 保留边但标记为低相似度
                scored_edges.append((edge, 0.0))
        
        # 按相似度排序
        scored_edges.sort(key=lambda x: x[1], reverse=True)
        
        return [edge for edge, _ in scored_edges]
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
