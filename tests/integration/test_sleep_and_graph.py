"""
睡眠整合 + 图遍历模块测试

P1: 增强睡眠功能中记忆整合算法（语义相似度聚类）
P2: 实现图遍历检索（多跳推理）
"""

import pytest
from datetime import datetime

from neurova.cognitive_layers.memory_layer.sleep import (
    SleepConsolidation, MemoryRecord, MergeResult, cosine_similarity
)
from neurova.cognitive_layers.memory_layer.graph_traversal import (
    GraphTraversal, MemoryRelation, TraversalPath, TraversalResult
)


# ============================================================
# P1: 睡眠整合 - 语义相似度聚类
# ============================================================

class TestSleepConsolidation:
    """P1: 记忆整合算法测试"""

    def test_cosine_similarity_identical(self):
        """测试21: 相同向量的余弦相似度为1"""
        vec = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec, vec) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        """测试22: 正交向量的余弦相似度为0"""
        vec_a = [1.0, 0.0]
        vec_b = [0.0, 1.0]
        assert cosine_similarity(vec_a, vec_b) == pytest.approx(0.0)

    def test_cosine_similarity_similar(self):
        """测试23: 相似向量的余弦相似度接近1"""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.1, 2.1, 3.1]
        sim = cosine_similarity(vec_a, vec_b)
        assert sim > 0.99

    def test_cluster_by_similarity(self):
        """测试24: 语义相似度聚类"""
        engine = SleepConsolidation(similarity_threshold=0.8)
        
        # 创建两组相似记忆
        memories = [
            MemoryRecord(id="m1", content="Python编程", embedding=[1.0, 0.0, 0.0]),
            MemoryRecord(id="m2", content="Python语法", embedding=[0.95, 0.05, 0.0]),
            MemoryRecord(id="m3", content="深度学习", embedding=[0.0, 0.0, 1.0]),
            MemoryRecord(id="m4", content="神经网络", embedding=[0.0, 0.05, 0.95]),
        ]
        
        clusters = engine.cluster_by_similarity(memories)
        
        # 应该有2个簇
        assert len(clusters) == 2
        # 每个簇有2条记忆
        assert all(len(c) == 2 for c in clusters)

    def test_merge_cluster_content(self):
        """测试25: 合并簇取最长内容"""
        engine = SleepConsolidation()
        
        cluster = [
            MemoryRecord(id="m1", content="短", temperature=60.0, importance=0.5),
            MemoryRecord(id="m2", content="这是一个较长的内容", temperature=40.0, importance=0.7),
        ]
        
        result = engine.merge_cluster(cluster)
        
        assert result.merged_content == "这是一个较长的内容"
        assert result.avg_temperature == 50.0
        assert result.avg_importance == 0.6

    def test_merge_cluster_categories(self):
        """测试26: 合并簇时分类去重"""
        engine = SleepConsolidation()
        
        cluster = [
            MemoryRecord(id="m1", content="A", categories=["python", "编程"]),
            MemoryRecord(id="m2", content="B", categories=["编程", "算法"]),
        ]
        
        result = engine.merge_cluster(cluster)
        
        assert set(result.combined_categories) == {"python", "编程", "算法"}

    def test_consolidate_reduces_redundancy(self):
        """测试27: 完整整合流程减少冗余"""
        engine = SleepConsolidation(similarity_threshold=0.8)
        
        memories = [
            MemoryRecord(id="m1", content="机器学习入门", embedding=[1.0, 0.0], temperature=80.0, importance=0.6),
            MemoryRecord(id="m2", content="机器学习基础", embedding=[0.98, 0.02], temperature=75.0, importance=0.7),
            MemoryRecord(id="m3", content="机器学习原理", embedding=[0.96, 0.04], temperature=70.0, importance=0.5),
            MemoryRecord(id="m4", content="自然语言处理", embedding=[0.0, 1.0], temperature=60.0, importance=0.4),
        ]
        
        merged, merge_results = engine.consolidate(memories)
        
        # 应该从4条合并到2条（3条相似的合并为1条）
        assert len(merged) == 2
        assert len(merge_results) == 2
        # 有一个合并记录包含3个来源
        assert any(len(mr.source_ids) == 3 for mr in merge_results)

    def test_sleep_decay_applies(self):
        """测试28: 睡眠期间温度衰减"""
        engine = SleepConsolidation(decay_rate=0.2)
        
        memories = [
            MemoryRecord(id="m1", content="高温度", temperature=80.0, importance=0.5),
            MemoryRecord(id="m2", content="低温度", temperature=10.0, importance=0.5),
        ]
        
        decayed = engine.apply_sleep_decay(memories)
        
        # 所有记忆温度都应该降低
        assert decayed[0].temperature < 80.0
        assert decayed[1].temperature < 10.0

    def test_archive_low_temperature(self):
        """测试29: 低温度记忆被归档"""
        engine = SleepConsolidation(archive_threshold=20.0, decay_rate=0.5)
        
        memories = [
            MemoryRecord(id="m1", content="即将归档", temperature=15.0, importance=0.1),
        ]
        
        decayed = engine.apply_sleep_decay(memories)
        
        # 温度低于阈值应被归档
        assert decayed[0].is_archived is True

    def test_empty_cluster_error(self):
        """测试30: 空簇合并应报错"""
        engine = SleepConsolidation()
        
        with pytest.raises(ValueError):
            engine.merge_cluster([])


# ============================================================
# P2: 图遍历检索
# ============================================================

class TestGraphTraversal:
    """P2: 图遍历检索测试"""

    def _build_test_graph(self):
        """构建测试图:
        
        A --related--> B --causes--> C
        A --supports--> D
        B --contradicts--> E
        D --part_of--> F
        """
        graph = GraphTraversal(max_depth=3)
        
        graph.add_relation(MemoryRelation("A", "B", "related", 0.8))
        graph.add_relation(MemoryRelation("B", "C", "causes", 0.9))
        graph.add_relation(MemoryRelation("A", "D", "supports", 0.7))
        graph.add_relation(MemoryRelation("B", "E", "contradicts", 0.6))
        graph.add_relation(MemoryRelation("D", "F", "part_of", 0.8))
        
        return graph

    def test_add_and_get_relations(self):
        """测试31: 添加和获取关联关系"""
        graph = GraphTraversal()
        
        graph.add_relation(MemoryRelation("A", "B", "related", 0.8))
        graph.add_relation(MemoryRelation("A", "C", "supports", 0.9))
        
        # 获取出向关联
        outgoing = graph.get_relations("A", direction="outgoing")
        assert len(outgoing) == 2
        
        # 获取入向关联
        incoming = graph.get_relations("B", direction="incoming")
        assert len(incoming) == 1

    def test_bfs_traversal(self):
        """测试32: BFS遍历能找到所有可达节点"""
        graph = self._build_test_graph()
        
        result = graph.traverse_bfs("A")
        
        # 从A可以到达B, C, D, E, F
        assert result.reachable_ids == {"B", "C", "D", "E", "F"}
        assert len(result.paths) > 0

    def test_dfs_traversal(self):
        """测试33: DFS遍历能找到所有可达节点"""
        graph = self._build_test_graph()
        
        result = graph.traverse_dfs("A")
        
        # 从A可以到达B, C, D, E, F
        assert result.reachable_ids == {"B", "C", "D", "E", "F"}

    def test_find_path(self):
        """测试34: 查找两个节点之间的路径"""
        graph = self._build_test_graph()
        
        path = graph.find_path("A", "C")
        
        assert path is not None
        assert path.nodes[0] == "A"
        assert path.nodes[-1] == "C"
        assert len(path.relations) > 0

    def test_find_path_no_route(self):
        """测试35: 无路径时返回None"""
        graph = GraphTraversal()
        graph.add_relation(MemoryRelation("A", "B", "related", 0.8))
        
        # C与A不连通
        path = graph.find_path("A", "C")
        assert path is None

    def test_max_depth_limits_traversal(self):
        """测试36: max_depth限制遍历深度"""
        graph = GraphTraversal(max_depth=1)
        
        graph.add_relation(MemoryRelation("A", "B", "related", 0.8))
        graph.add_relation(MemoryRelation("B", "C", "related", 0.8))
        
        result = graph.traverse_bfs("A")
        
        # max_depth=1，只能到达B，不能到达C
        assert "B" in result.reachable_ids
        assert "C" not in result.reachable_ids

    def test_min_strength_filters_weak_relations(self):
        """测试37: min_strength过滤弱关联"""
        graph = GraphTraversal(min_strength=0.5)
        
        graph.add_relation(MemoryRelation("A", "B", "related", 0.8))
        graph.add_relation(MemoryRelation("A", "C", "related", 0.2))  # 太弱
        
        result = graph.traverse_bfs("A")
        
        assert "B" in result.reachable_ids
        assert "C" not in result.reachable_ids

    def test_best_path_selection(self):
        """测试38: 选择强度最高的路径"""
        graph = GraphTraversal()
        
        # 两条路径到D：A→D（strength=0.7）和 A→B→D（不存在）
        graph.add_relation(MemoryRelation("A", "B", "related", 0.3))
        graph.add_relation(MemoryRelation("A", "D", "supports", 0.9))
        
        result = graph.traverse_bfs("A")
        
        best = result.best_path
        assert best is not None
        # 最佳路径应该直接到D
        assert "D" in best.nodes

    def test_get_memory_context(self):
        """测试39: 获取记忆上下文信息"""
        graph = self._build_test_graph()
        
        context = graph.get_memory_context("A")
        
        assert context["memory_id"] == "A"
        assert context["total_outgoing"] == 2  # A→B, A→D
        assert context["total_incoming"] == 0  # A没有入向关联

    def test_graph_stats(self):
        """测试40: 图统计信息"""
        graph = self._build_test_graph()
        
        stats = graph.get_stats()
        
        assert stats["total_nodes"] == 6  # A, B, C, D, E, F
        assert stats["total_edges"] == 5  # 5条关联
        assert stats["max_depth"] == 3

    def test_find_path_same_node(self):
        """测试41: 同一节点到自身的路径"""
        graph = GraphTraversal()
        graph.add_relation(MemoryRelation("A", "B", "related", 0.8))
        
        path = graph.find_path("A", "A")
        
        assert path is not None
        assert path.nodes == ["A"]

    def test_traversal_result_best_reachable(self):
        """测试42: 最佳可达节点"""
        graph = GraphTraversal()
        graph.add_relation(MemoryRelation("A", "B", "supports", 0.9))
        graph.add_relation(MemoryRelation("A", "C", "related", 0.3))
        
        result = graph.traverse_bfs("A")
        
        best = result.best_reachable
        # B应该因为supports关系强度更高而成为最佳
        assert best is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])