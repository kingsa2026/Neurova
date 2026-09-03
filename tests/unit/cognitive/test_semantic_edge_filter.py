"""
语义边过滤器测试

TDD: 先写测试，再实现
"""

import pytest
from unittest.mock import Mock, MagicMock
from neurova.cognitive_layers.memory_layer.semantic_edge_filter import (
    SemanticEdgeFilter,
    EnhancedDependencyEdge,
)


class TestEnhancedDependencyEdge:
    """EnhancedDependencyEdge 数据类测试"""
    
    def test_init(self):
        """测试初始化"""
        edge = EnhancedDependencyEdge(
            id="edge_001",
            source_id="entity_a",
            target_id="entity_b",
            dep_type="causal",
            confidence=0.8,
            description="数据库故障导致API异常",
            source_context="用户说数据库挂了",
            extraction_method="conversation",
        )
        assert edge.id == "edge_001"
        assert edge.source_id == "entity_a"
        assert edge.description == "数据库故障导致API异常"
        assert edge.extraction_method == "conversation"
    
    def test_to_dict(self):
        """测试转换为字典"""
        edge = EnhancedDependencyEdge(
            id="edge_001",
            source_id="entity_a",
            target_id="entity_b",
            dep_type="causal",
            confidence=0.8,
        )
        d = edge.to_dict()
        assert "id" in d
        assert "source_id" in d
        assert "dep_type" in d


class TestSemanticEdgeFilter:
    """SemanticEdgeFilter 测试"""
    
    def test_init(self):
        """测试初始化"""
        filter_obj = SemanticEdgeFilter()
        assert filter_obj is not None
    
    def test_filter_without_embedding_model(self):
        """测试无嵌入模型时的过滤"""
        filter_obj = SemanticEdgeFilter()
        
        edges = [
            EnhancedDependencyEdge("e1", "a", "b", "causal", 0.8),
            EnhancedDependencyEdge("e2", "b", "c", "temporal", 0.7),
        ]
        
        result = filter_obj.filter_by_relevance(edges, "test query")
        assert len(result) == 2  # 无嵌入模型时返回所有边
    
    def test_filter_with_mock_embedding(self):
        """测试带mock嵌入模型的过滤"""
        mock_embedding = Mock()
        mock_embedding.encode = Mock(return_value=[0.1, 0.2, 0.3])
        
        filter_obj = SemanticEdgeFilter(embedding_model=mock_embedding)
        
        edges = [
            EnhancedDependencyEdge("e1", "a", "b", "causal", 0.8),
            EnhancedDependencyEdge("e2", "b", "c", "temporal", 0.7),
        ]
        
        result = filter_obj.filter_by_relevance(edges, "test query", threshold=0.3)
        assert len(result) == 2
    
    def test_cosine_similarity(self):
        """测试余弦相似度计算"""
        filter_obj = SemanticEdgeFilter()
        
        # 相同向量
        sim = filter_obj._cosine_similarity([1, 0, 0], [1, 0, 0])
        assert abs(sim - 1.0) < 0.01
        
        # 正交向量
        sim = filter_obj._cosine_similarity([1, 0, 0], [0, 1, 0])
        assert abs(sim - 0.0) < 0.01
        
        # 空向量
        sim = filter_obj._cosine_similarity([], [])
        assert sim == 0.0
        
        # 不同长度向量
        sim = filter_obj._cosine_similarity([1, 0], [1, 0, 0])
        assert sim == 0.0
    
    def test_filter_empty_edges(self):
        """测试空边列表"""
        filter_obj = SemanticEdgeFilter()
        result = filter_obj.filter_by_relevance([], "test query")
        assert len(result) == 0
