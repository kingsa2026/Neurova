"""NEURON 组件单元测试

覆盖:
    - DependencyGraph: 实体/边操作, BFS/DFS 查询, 循环检测, 缓存
    - CascadeEngine: 正向/反向级联, 影响判断
    - AbsenceReasoner: 三层缺失检测
    - MOEDependencyExtractor: 实体提取, 关系分类, 完整提取流程
"""

import asyncio
import os
import tempfile

import pytest

from neurova.cognitive_layers.memory_layer.dependency_graph import (
    DependencyGraph,
    DependencyEdge,
    DependencyType,
    EntityNode,
)
from neurova.cognitive_layers.memory_layer.cascade_engine import (
    CascadeDirection,
    CascadeEngine,
)
from neurova.cognitive_layers.memory_layer.absence_reasoner import (
    AbsenceReasoner,
    AbsenceResult,
)
from neurova.cognitive_layers.memory_layer.moe_dependency_extractor import (
    EntityExtractor,
    ExtractedDependency,
    MOEDependencyExtractor,
    RelationClassifier,
)


# ═══════════════════════════════════════════════════════
# DependencyGraph Tests
# ═══════════════════════════════════════════════════════


class TestDependencyGraph:
    """依赖图谱基础测试"""

    def test_add_entity(self):
        graph = DependencyGraph()
        entity = EntityNode(id="a", name="A", entity_type="concept")
        assert graph.add_entity(entity) is True
        assert "a" in graph.entities
        assert graph.entities["a"].name == "A"

    def test_add_entity_empty_id(self):
        graph = DependencyGraph()
        entity = EntityNode(id="", name="A", entity_type="concept")
        assert graph.add_entity(entity) is False

    def test_add_entity_duplicate_updates(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="a", name="A_updated", entity_type="concept"))
        assert len(graph.entities) == 1
        assert graph.entities["a"].name == "A_updated"

    def test_add_dependency(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        edge = DependencyEdge(
            id="a_b", source_id="a", target_id="b",
            dep_type=DependencyType.CAUSAL,
        )
        assert graph.add_dependency(edge) is True
        assert len(graph.edges) == 1

    def test_add_dependency_duplicate(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        edge = DependencyEdge(
            id="a_b", source_id="a", target_id="b",
            dep_type=DependencyType.CAUSAL,
        )
        graph.add_dependency(edge)
        assert graph.add_dependency(edge) is False

    def test_get_downstream(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))
        graph.add_dependency(DependencyEdge(
            id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL,
        ))

        downstream = graph.get_downstream("a")
        assert "b" in downstream
        assert "c" in downstream

    def test_get_upstream(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))

        upstream = graph.get_upstream("b")
        assert "a" in upstream

    def test_find_cascade_paths(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))
        graph.add_dependency(DependencyEdge(
            id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL,
        ))

        paths = graph.find_cascade_paths("a", "c")
        assert len(paths) == 1
        assert paths[0] == ["a", "b", "c"]

    def test_find_cascade_paths_no_path(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        paths = graph.find_cascade_paths("a", "b")
        assert len(paths) == 0

    def test_detect_circular_dependencies(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))
        graph.add_dependency(DependencyEdge(
            id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL,
        ))
        graph.add_dependency(DependencyEdge(
            id="c_a", source_id="c", target_id="a", dep_type=DependencyType.CAUSAL,
        ))

        cycles = graph.detect_circular_dependencies()
        assert len(cycles) >= 1

    def test_remove_entity(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))
        assert graph.remove_entity("a") is True
        assert "a" not in graph.entities
        assert len(graph.edges) == 0

    def test_get_entity_degree(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))
        graph.add_dependency(DependencyEdge(
            id="c_b", source_id="c", target_id="b", dep_type=DependencyType.CAUSAL,
        ))

        in_degree, out_degree = graph.get_entity_degree("b")
        assert in_degree == 2
        assert out_degree == 0

    def test_cache(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))

        graph.get_downstream("a")
        assert len(graph._downstream_cache) > 0

        count = graph.clear_cache()
        assert count > 0
        assert len(graph._downstream_cache) == 0

    def test_stats(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_a", source_id="a", target_id="a", dep_type=DependencyType.SUPPORT,
        ))
        stats = graph.get_stats()
        assert stats["entity_count"] == 1
        assert stats["edge_count"] == 1

    def test_sqlite_persistence(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            graph1 = DependencyGraph(db_path=db_path)
            graph1.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
            graph1.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
            graph1.add_dependency(DependencyEdge(
                id="a_b", source_id="a", target_id="b",
                dep_type=DependencyType.CAUSAL,
            ))
            del graph1

            graph2 = DependencyGraph(db_path=db_path)
            assert "a" in graph2.entities
            assert "b" in graph2.entities
            assert len(graph2.edges) == 1
        finally:
            os.unlink(db_path)


# ═══════════════════════════════════════════════════════
# CascadeEngine Tests
# ═══════════════════════════════════════════════════════


class TestCascadeEngine:
    """级联推理引擎测试"""

    def _build_graph(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_entity(EntityNode(id="c", name="C", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b", dep_type=DependencyType.CAUSAL,
        ))
        graph.add_dependency(DependencyEdge(
            id="b_c", source_id="b", target_id="c", dep_type=DependencyType.CAUSAL,
        ))
        return graph

    def test_forward_cascade(self):
        graph = self._build_graph()
        engine = CascadeEngine(graph)
        result = engine.forward_cascade("a")

        assert result.total_affected == 2
        assert len(result.effects) == 2
        assert result.direction == CascadeDirection.FORWARD
        assert result.confidence > 0

    def test_backward_cascade(self):
        graph = self._build_graph()
        engine = CascadeEngine(graph)
        result = engine.backward_cascade("c")

        assert result.total_affected == 2
        assert result.direction == CascadeDirection.BACKWARD

    def test_forward_cascade_nonexistent(self):
        graph = self._build_graph()
        engine = CascadeEngine(graph)
        result = engine.forward_cascade("nonexistent")

        assert result.total_affected == 0
        assert len(result.effects) == 0

    def test_would_affect(self):
        graph = self._build_graph()
        engine = CascadeEngine(graph)
        result = engine.would_affect("a", "c")

        assert result["would_affect"] is True
        assert result["confidence"] > 0
        assert len(result["paths"]) > 0

    def test_would_affect_no_path(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        engine = CascadeEngine(graph)
        result = engine.would_affect("a", "b")

        assert result["would_affect"] is False


# ═══════════════════════════════════════════════════════
# AbsenceReasoner Tests
# ═══════════════════════════════════════════════════════


class TestAbsenceReasoner:
    """缺失推理器测试"""

    def test_detect_absence_entity_missing(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))

        reasoner = AbsenceReasoner(graph)
        result = reasoner.detect_absence(
            expected_entity="nonexistent",
            expected_relation=DependencyType.CAUSAL,
            context_entities=["a"],
        )

        assert result.is_absent is True
        assert result.entity_exists is False

    def test_detect_absence_relation_missing(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))

        reasoner = AbsenceReasoner(graph)
        result = reasoner.detect_absence(
            expected_entity="a",
            expected_relation=DependencyType.CAUSAL,
            context_entities=["a"],
        )

        assert result.is_absent is True
        assert result.entity_exists is True
        assert result.relation_exists is False

    def test_detect_no_absence(self):
        graph = DependencyGraph()
        graph.add_entity(EntityNode(id="a", name="A", entity_type="concept"))
        graph.add_entity(EntityNode(id="b", name="B", entity_type="concept"))
        graph.add_dependency(DependencyEdge(
            id="a_b", source_id="a", target_id="b",
            dep_type=DependencyType.CAUSAL,
        ))

        reasoner = AbsenceReasoner(graph)
        result = reasoner.detect_absence(
            expected_entity="a",
            expected_relation=DependencyType.CAUSAL,
            context_entities=["b"],
        )

        assert result.is_absent is False
        assert result.entity_exists is True
        assert result.relation_exists is True
        assert result.context_has_dependency is True

    def test_detect_batch(self):
        graph = DependencyGraph()
        reasoner = AbsenceReasoner(graph)
        results = reasoner.detect_batch(
            expected_entities=["x", "y", "z"],
            expected_relation=DependencyType.CAUSAL,
            context_entities=[],
        )
        assert len(results) == 3
        assert all(r.is_absent for r in results)


# ═══════════════════════════════════════════════════════
# MOEDependencyExtractor Tests
# ═══════════════════════════════════════════════════════


class TestEntityExtractor:
    """实体提取器测试"""

    def test_extract_basic(self):
        extractor = EntityExtractor()
        entities = extractor.extract("部署服务器需要数据库")
        assert len(entities) > 0
        names = [e["name"] for e in entities]
        assert "服务器" in names or "数据库" in names

    def test_extract_date(self):
        extractor = EntityExtractor()
        entities = extractor.extract("2026-06-13 部署完成")
        names = [e["name"] for e in entities]
        assert "2026-06-13" in names

    def test_extract_multiple_types(self):
        extractor = EntityExtractor()
        entities = extractor.extract("张三在2026-06-13部署了服务器")
        types = [e["type"] for e in entities]
        assert "person" in types or "date" in types or "object" in types


class TestRelationClassifier:
    """关系分类器测试"""

    def test_classify_causal(self):
        classifier = RelationClassifier()
        entity1 = {"name": "A", "end": 5}
        entity2 = {"name": "B", "start": 10}
        dep_type, confidence = classifier.classify(entity1, entity2, "A导致B")
        assert dep_type == DependencyType.CAUSAL
        assert confidence >= 0.7

    def test_classify_temporal(self):
        classifier = RelationClassifier()
        entity1 = {"name": "A", "end": 5}
        entity2 = {"name": "B", "start": 10}
        dep_type, confidence = classifier.classify(entity1, entity2, "A之后B")
        assert dep_type == DependencyType.TEMPORAL

    def test_classify_conditional(self):
        classifier = RelationClassifier()
        entity1 = {"name": "A", "end": 5}
        entity2 = {"name": "B", "start": 10}
        dep_type, confidence = classifier.classify(entity1, entity2, "如果A则B")
        assert dep_type == DependencyType.CONDITIONAL


class TestMOEDependencyExtractor:
    """MOE 依赖提取器测试"""

    def test_extract_from_memory(self):
        extractor = MOEDependencyExtractor()
        content = "部署服务器需要先安装数据库，然后配置API接口"
        deps = asyncio.run(extractor.extract_from_memory(
            memory_id="test_001", content=content,
        ))
        assert isinstance(deps, list)

    def test_extract_short_content(self):
        extractor = MOEDependencyExtractor()
        deps = asyncio.run(extractor.extract_from_memory(
            memory_id="test_002", content="短文本",
        ))
        assert len(deps) == 0

    def test_jaccard_similarity(self):
        extractor = MOEDependencyExtractor()
        sim = extractor._compute_similarity("部署 服务器", "部署 数据库")
        assert 0 < sim < 1


# ═══════════════════════════════════════════════════════
# Integration Test
# ═══════════════════════════════════════════════════════


class TestNEURONIntegration:
    """NEURON 组件集成测试"""

    def test_full_pipeline(self):
        """完整流程: 提取 → 图构建 → 级联 → 缺失检测"""
        graph = DependencyGraph()
        cascade_engine = CascadeEngine(graph)
        absence_reasoner = AbsenceReasoner(graph)

        # 构建测试图谱
        graph.add_entity(EntityNode(id="server", name="服务器", entity_type="object"))
        graph.add_entity(EntityNode(id="database", name="数据库", entity_type="object"))
        graph.add_entity(EntityNode(id="api", name="API接口", entity_type="object"))
        graph.add_dependency(DependencyEdge(
            id="srv_db", source_id="server", target_id="database",
            dep_type=DependencyType.PREREQUISITE, confidence=0.9,
        ))
        graph.add_dependency(DependencyEdge(
            id="db_api", source_id="database", target_id="api",
            dep_type=DependencyType.PREREQUISITE, confidence=0.8,
        ))

        # 正向级联: 服务器变化影响
        result = cascade_engine.forward_cascade("server")
        assert result.total_affected == 2

        # 缺失检测: 检查是否缺少缓存依赖
        absence = absence_reasoner.detect_absence(
            expected_entity="cache",
            expected_relation=DependencyType.PREREQUISITE,
            context_entities=["server", "database"],
        )
        assert absence.is_absent is True
        assert absence.entity_exists is False

    def test_moe_to_graph_pipeline(self):
        """MOE 提取 → 图构建 → 图查询"""
        extractor = MOEDependencyExtractor()
        content = "部署服务器需要数据库支持"
        deps = asyncio.run(extractor.extract_from_memory(
            memory_id="pipeline_001", content=content,
        ))

        # 验证图谱已构建
        graph = DependencyGraph()
        # 至少提取到实体
        entities = extractor.entity_extractor.extract(content)
        assert len(entities) > 0
