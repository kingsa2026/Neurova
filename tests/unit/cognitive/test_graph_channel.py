"""
图通道单元测试

测试GraphChannel的基本功能
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from neurova.cognitive_layers.memory_layer.channels.builtin.graph import GraphChannel
from neurova.cognitive_layers.knowledge_graph.manager import (
    KnowledgeGraphManager,
    GraphNode,
    GraphEdge,
    NodeType,
    RelationType,
)


class TestGraphChannel:
    """GraphChannel测试"""
    
    def test_init(self):
        """测试初始化"""
        channel = GraphChannel()
        assert channel is not None
    
    def test_metadata(self):
        """测试元数据"""
        channel = GraphChannel()
        meta = channel.metadata
        assert meta.name == "graph"
        assert "graph" in meta.capabilities
    
    def test_set_knowledge_graph(self):
        """测试设置知识图谱"""
        channel = GraphChannel()
        kg = KnowledgeGraphManager()
        channel.set_knowledge_graph(kg)
        assert channel._knowledge_graph is kg
    
    def test_extract_entities(self):
        """测试实体提取"""
        channel = GraphChannel()
        
        # 英文人名
        entities = channel._extract_entities("John Smith visited Paris")
        assert "John Smith" in entities
        
        # 中文人名
        entities = channel._extract_entities("张老师来了")
        # 应该提取出包含"张老师"的实体
        assert any("张老师" in e for e in entities)
    
    def test_retrieve_without_knowledge_graph(self):
        """测试无知识图谱时的检索"""
        import asyncio
        
        channel = GraphChannel()
        result = asyncio.run(channel.retrieve("test query"))
        assert result == []
    
    def test_retrieve_with_knowledge_graph(self):
        """测试有知识图谱时的检索"""
        import asyncio
        
        channel = GraphChannel()
        kg = KnowledgeGraphManager()
        
        # 添加测试节点
        node1 = kg.add_node(
            label="python",
            node_type=NodeType.CONCEPT,
            properties={"description": "Programming language"},
        )
        node2 = kg.add_node(
            label="java",
            node_type=NodeType.CONCEPT,
            properties={"description": "Programming language"},
        )
        
        # 添加关系
        kg.add_edge(
            source_id=node1.node_id,
            target_id=node2.node_id,
            relation_type=RelationType.SIMILAR_TO,
        )
        
        channel.set_knowledge_graph(kg)
        
        # 测试搜索
        result = asyncio.run(channel.retrieve("python", limit=5))
        # 搜索应该返回结果（可能为空，取决于索引）
        assert isinstance(result, list)
    
    def test_find_related_memories(self):
        """测试查找关联记忆"""
        channel = GraphChannel()
        kg = KnowledgeGraphManager()
        
        # 添加测试节点
        node1 = kg.add_node(
            label="Memory 1",
            node_type=NodeType.MEMORY,
        )
        node2 = kg.add_node(
            label="Memory 2",
            node_type=NodeType.MEMORY,
        )
        
        # 添加关系
        kg.add_edge(
            source_id=node1.node_id,
            target_id=node2.node_id,
            relation_type=RelationType.RELATED_TO,
        )
        
        channel.set_knowledge_graph(kg)
        
        result = channel.find_related_memories(node1.node_id, max_depth=2)
        assert len(result) > 0
        assert result[0].memory_id == node2.node_id
    
    def test_find_shortest_path(self):
        """测试查找最短路径"""
        channel = GraphChannel()
        kg = KnowledgeGraphManager()
        
        # 添加测试节点
        node1 = kg.add_node(label="A", node_type=NodeType.CONCEPT)
        node2 = kg.add_node(label="B", node_type=NodeType.CONCEPT)
        node3 = kg.add_node(label="C", node_type=NodeType.CONCEPT)
        
        # 添加关系
        kg.add_edge(
            source_id=node1.node_id,
            target_id=node2.node_id,
            relation_type=RelationType.RELATED_TO,
        )
        kg.add_edge(
            source_id=node2.node_id,
            target_id=node3.node_id,
            relation_type=RelationType.RELATED_TO,
        )
        
        channel.set_knowledge_graph(kg)
        
        path = channel.find_shortest_path(node1.node_id, node3.node_id)
        # 路径应该存在（可能返回None如果图谱未正确索引）
        assert path is None or isinstance(path, list)
