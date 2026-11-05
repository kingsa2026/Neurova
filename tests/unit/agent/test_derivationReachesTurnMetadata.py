"""推导要真能在对话里被认出来（升级计划 B4 接线，不接死支路）。

链路按**真实装配点**验，不用 MagicMock 冒充业务对象：
真库（咽喉＋规则引擎）→ 真 GraphFactWalker → 真 `_graphRoute` → 真
`_normalize_item` → 真 `ChatPipeline._recordKnowledgeLineage`。
每一段都只验它自己那一环的取数口径，合起来才是「这轮引用里哪条是推的」。

观察态一侧由 test_graphWalkDerivationGovernance.py 钉住（推导进不了走查），
本档钉翻主路一侧：既然放行了，排序依据就必须可辨，不许伪装成观察事实。
"""

from __future__ import annotations

import pytest

from neurova.agent.chat_pipeline import ChatPipeline
from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
from neurova.agent.memory_retrieval_chain import RetrievalContext
from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry


def _admit(store, subject, predicate, obj, mediumRef="unit:test"):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": mediumRef, "statementText": content}],
    )).factId


@pytest.fixture
def bridgedStore(tmp_path, monkeypatch):
    """推导当跳板、把 entry:doc1 接进图谱排序的最小真场景（翻主路态）。"""
    monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
    store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级"},
        {"termId": "requiresAction", "kind": "relation", "label": "需动作"},
    ])
    _admit(store, "HighRiskOrder", "requiresAction", "复核", mediumRef="entry:doc1")
    _admit(store, "订单D01", IS_A_PREDICATE, "Order")
    _admit(store, "订单D01", "hasRiskLevel", "High")
    registry.assignSubjectType(store.resolveSubjectKey("default", "订单D01"), "Order")
    ForwardChainingEngine(
        store, gateFactory=lambda st: productionAdmissionGate(st)
    ).registerRule(
        "high_risk_order", IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
        headObjectConst="HighRiskOrder")
    yield store
    store.close()


def _adapter(store):
    return KnowledgeRetrieverAdapter(
        repo=None, graphWalker=GraphFactWalker(store, agentId="default"))


class TestSupportCarriesDerivation:
    def testGraphRouteMarksTheEntryPromotedThroughADerivedHop(self, bridgedStore):
        ranks, support, weight = _adapter(bridgedStore)._graphRoute(
            RetrievalContext(query="订单D01 风险", limit=5,
                             metadata={"agent_id": "default"}), "default", 5)

        assert [rid for rid, _ in ranks] and "doc1" in [rid for rid, _ in ranks], (
            "场景没把条目带进来，后面判据会对着空气断言")
        assert weight > 0, "图谱权重为 0 时这条支撑进不了排序，判据就不成立"
        assert any(hop["derived"] is True for hop in support["doc1"]), \
            "排序依据里含推导跳却没标出来——对话侧无从分辨"

    def testExplicitOnlySupportIsNotFlagged(self, tmp_path, monkeypatch):
        """非虚设控制：同样两跳到条目，但中间那一跳是显式写的 ⇒ 不许带 derived。

        不这么搭场景就会踩到另一件事：走查只回 hop>=2 的叶子，少了跳板那一条
        根本不成两跳，support 直接空——那不是控制，那是没跑。
        """
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        store = KnowledgeFactStore(str(tmp_path / "explicit.db"))
        registry = OntologyTermRegistry(store)
        registry.registerMany([
            {"termId": "Order", "kind": "concept", "label": "订单"},
            {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
            {"termId": "requiresAction", "kind": "relation", "label": "需动作"},
        ])
        _admit(store, "HighRiskOrder", "requiresAction", "复核", mediumRef="entry:doc1")
        _admit(store, "订单D01", IS_A_PREDICATE, "Order")
        _admit(store, "订单D01", IS_A_PREDICATE, "HighRiskOrder")
        try:
            _ranks, support, _weight = _adapter(store)._graphRoute(
                RetrievalContext(query="订单D01 风险", limit=5,
                                 metadata={"agent_id": "default"}), "default", 5)

            assert support.get("doc1"), "显式两跳没走得到条目——本控制格什么也没控制"
            assert all(hop["derived"] is False for hop in support["doc1"])
        finally:
            store.close()


class TestPayloadAndTurnMetadata:
    def testNormalizeItemCarriesDerivationOnlyWhenKnown(self, bridgedStore):
        adapter = _adapter(bridgedStore)
        derived = adapter._normalize_item({
            "knowledge_id": "doc1", "title": "高风险订单处置", "content": "要复核",
            "graph_support": [{"fact_id": "fact_x", "derived": True}],
        })
        plain = adapter._normalize_item({
            "knowledge_id": "doc2", "title": "普通条目", "content": "正文",
            "graph_support": [{"fact_id": "fact_y", "derived": False}],
        })

        assert derived["derivation"] == {"derived": False, "viaDerived": True}
        assert "derivation" not in plain, "没推导参与时挂个 false 是替账本作伪证"

    def testSurfaceDerivationPassesThroughVerbatim(self):
        """读面自带的标注形状不改写：规则号与前提数是对话里唯一能报出来的东西。"""
        item = KnowledgeRetrieverAdapter._normalize_item({
            "knowledge_id": "fact_1", "lineage_id": "fact_1", "content": "订单D01 is_a HighRiskOrder",
            "derivation": {"derived": True, "ruleId": "high_risk_order", "premiseCount": 2},
        })

        assert item["derivation"] == {
            "derived": True, "ruleId": "high_risk_order", "premiseCount": 2}

    def testRecordKnowledgeLineagePutsDerivationOnTheTurn(self, bridgedStore):
        """本轮引用的溯源按**最终注入**的命中记，与血缘同一口径。"""
        class _Ctx:
            def __init__(self):
                self.relevant_memories = [
                    {"knowledge_id": "doc1", "lineage_id": "",
                     "derivation": {"derived": False, "viaDerived": True}},
                    {"knowledge_id": "doc9", "lineage_id": ""},
                ]
                self.metadata = {}

        ctx = _Ctx()
        ChatPipeline._recordKnowledgeLineage(ctx, result=None)

        assert ctx.metadata["knowledge_derivation"] == {
            "doc1": {"derived": False, "viaDerived": True}}, ctx.metadata
        assert "doc9" not in ctx.metadata["knowledge_derivation"], \
            "没有溯源依据的条目不该被记成'查过、不是推导'"
