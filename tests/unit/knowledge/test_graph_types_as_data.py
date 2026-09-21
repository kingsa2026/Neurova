"""工单 018（E3 收缩）：死码退役 + 类型是数据不是 Enum + 图谱节点走身份消解段。

三条判据各自的反面就是它要灭的病：
- B02 的抽取死码留着，读面就有第二条"看起来能写"的路；退役不等于断线，
  所以同时断言在用的那条路（底座时效视图）还在。
- 类型加一种就要改 Python 文件、发一次版；把枚举值一次性导入 `ontology_terms` 之后，
  新类型是表里的一行。图谱存储必须能把没在枚举里出现过的类型原样存回再读出，
  否则"数据即类型"只是写入侧的错觉。
- 按 `(label, type)` 精确复用节点，等于让类型当身份的一部分：同一个"青海湖"
  被判成两个实体。身份归一处只该有一个权威（006 的消解段）。
"""

from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.knowledge_graph import manager as kgModule
from neurova.cognitive_layers.knowledge_graph.manager import (
    GraphNode,
    KnowledgeGraphManager,
    NodeType,
    RelationType,
)
from neurova.knowledge import graph_bridge
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    return OntologyTermRegistry(store)


@pytest.fixture
def graph(tmp_path):
    return KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"), auto_save=True)


def _llm(entities, relations=None):
    payload = {"entities": entities, "relations": relations or []}

    def _call(_prompt):
        return json.dumps(payload, ensure_ascii=False)

    return _call


def _bridge(graph, registry, store, entities, relations=None):
    return graph_bridge.extract_knowledge_to_graph(
        {"knowledge_id": "k1", "title": "青海湖", "content": "青海湖是高原湖泊。"},
        repo=None,
        llm_call=_llm(entities, relations),
        graph_manager=graph,
        termRegistry=registry,
        factStore=store,
    )


class TestB02DeadCodeRetired:
    def test_extractionBridgeIsGone(self):
        from neurova.cognitive_layers.memory_layer import temporal_knowledge_graph as tkg

        assert not hasattr(tkg, "TemporalKGMemoryBridge"), "死码要删掉，不是注释掉"

    def test_liveReadPathIsStillWired(self):
        """退役不能把在用的那条路一起带走：012 之后读面在底座时效视图里。"""
        from neurova.knowledge.foundation.temporal_facts import TemporalFactReader

        assert hasattr(TemporalFactReader, "query_tkg_for_context")


class TestTypesAreData:
    def test_legacyEnumValuesLandAsTerms(self, registry):
        for value in NodeType:
            if value.value == "custom":
                continue
            term = registry.term(value.value)
            assert term and term["kind"] == "concept", "%s 没收编进类型表" % value.value
        for value in RelationType:
            if value.value == "custom":
                continue
            term = registry.term(value.value)
            assert term and term["kind"] == "relation", "%s 没收编进类型表" % value.value

    def test_customIsABackstopNotAType(self, registry):
        """两个枚举都有 custom，而术语 id 全表唯一：它是兜底标记，不是一种类型。"""
        assert registry.term("custom") is None

    def test_newTypeNeedsNoPythonChange(self, graph, registry, store):
        registry.register("vessel", "concept", label="舰船")

        nodeIds = _bridge(graph, registry, store, [{"label": "东风号", "type": "vessel"}])

        assert len(nodeIds) == 1
        assert graph._nodes[nodeIds[0]].nodeTypeValue == "vessel", "新类型不许被抹成 custom"

    def test_unregisteredTypeFallsToCustom(self, graph, registry, store):
        nodeIds = _bridge(graph, registry, store, [{"label": "某物", "type": "definitely_not_a_type"}])

        assert graph._nodes[nodeIds[0]].nodeTypeValue == NodeType.CUSTOM.value

    def test_missingRegistryDegradesToTheReadCompatLayer(self, graph, tmp_path):
        """注册表缺席时抽取消不掉，但类型判据退回枚举读兼容层。

        退回枚举意味着"这一轮认不出新登记的类型"，不是"抽取不写了"——类型词
        `concept` 进了合法集，节点照建，底座落点也照写。
        """
        store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
        try:
            nodeIds = graph_bridge.extract_knowledge_to_graph(
                {"knowledge_id": "k1", "title": "T", "content": "C"},
                repo=None, llm_call=_llm([{"label": "甲", "type": "concept"}]),
                graph_manager=graph, termRegistry=None, factStore=store,
                agentId="agent-a")

            assert len(nodeIds) == 1
            assert graph._nodes[nodeIds[0]].nodeTypeValue == "concept"
            assert "concept" in {n.nodeTypeValue for n in graph._nodes.values()}
        finally:
            store.close()

    def test_bridgeNoLongerBranchesOnTheEnum(self, registry):
        """枚举退成读兼容层：写入侧的合法集合来自表，不来自 enum 成员。"""
        registry.register("protocol", "relation", label="协议")
        allowed = graph_bridge.registeredRelationTypes(registry)

        assert "protocol" in allowed
        assert {t.value for t in RelationType} - {"custom"} <= set(allowed), \
            "旧枚举值仍须在合法集里"


class TestGraphStoreCarriesAnyType:
    def test_plainStringTypeRoundTrips(self, graph):
        node = graph.add_node(label="Python", node_type="vessel")

        assert node.to_dict()["node_type"] == "vessel"
        assert GraphNode.from_dict(node.to_dict()).nodeTypeValue == "vessel"
        assert [n.node_id for n in graph.get_nodes_by_type("vessel")] == [node.node_id]

    def test_legacyEnumInputStillWorks(self, graph):
        node = graph.add_node(label="Go", node_type=NodeType.CONCEPT)

        assert graph.get_nodes_by_type(NodeType.CONCEPT)[0].node_id == node.node_id
        assert graph.get_nodes_by_type("concept")[0].node_id == node.node_id
        assert node.nodeTypeValue == "concept"

    def test_oldRowsWithoutEnumValueStillLoad(self):
        node = GraphNode.from_dict({"node_id": "n1", "label": "L", "node_type": "vessel"})

        assert node.nodeTypeValue == "vessel"

    def test_edgesCarryAnyRelationType(self, graph):
        a = graph.add_node(label="A")
        b = graph.add_node(label="B")

        edge = graph.add_edge(source_id=a.node_id, target_id=b.node_id,
                              relation_type="vessel_of")

        assert edge.relationTypeValue == "vessel_of"
        assert edge.to_dict()["relation_type"] == "vessel_of"


class TestIdentitySegmentReplacesLabelTypeKey:
    def test_sameLabelDifferentTypeReusesTheNode(self, graph, registry, store):
        existing = graph.add_node(label="青海湖", node_type=NodeType.CONCEPT)

        nodeIds = _bridge(graph, registry, store, [{"label": "青海湖", "type": "location"}])

        assert nodeIds == [existing.node_id], "类型不是身份的一部分，同一湖泊只能有一个节点"
        assert len(graph._nodes) == 1

    def test_differentLabelStillGetsItsOwnNode(self, graph, registry, store):
        graph.add_node(label="青海", node_type=NodeType.CONCEPT)

        nodeIds = _bridge(graph, registry, store, [{"label": "茶卡盐湖", "type": "location"}])

        assert len(nodeIds) == 1
        assert len(graph._nodes) == 2

    def test_reloadKeepsTheSameIdentityRules(self, graph, tmp_path):
        """写盘再读回，判据不变：索引与类型都按字符串口径，不给"重载后成两个"留缝。"""
        graph.add_node(label="倒淌河", node_type="river")
        registry = OntologyTermRegistry(
            KnowledgeFactStore(str(tmp_path / "knowledge_facts.db")))
        registry.register("river", "concept")

        reopened = KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"), auto_save=False)

        assert [n.nodeTypeValue for n in reopened.get_nodes_by_type("river")] == ["river"]
