"""条件类推导的读侧治理落在**唯一事实→条目出口**（升级计划 B1 拍板项 2 ＋ B4）。

实测定位（2026-11-05，勿照票面抄）：`FactSurface.search` 是全仓唯一把底座事实
变成检索条目形状的地方（`read_surface.factToItem`，lineage_id＝fact_id）；chat 主路
经 `hybrid`→`search_visible_items` 只出条目，`mergeIntoLegacy` 生产零调用。所以
"推导事实默认不进检索主路"的**唯一非空落点**就是这道读面——它的现役消费者是
`GraphFactWalker._seedAnchors`（图谱路由的种子锚点，图谱路由默认 on）。

本档**不 import** 待建模块（教义第 3 条：红要红在行为断言上，不许整档
collection error 吞掉行为红）；判据全部走真咽喉、真规则引擎、真读面。
契约形状（`derivation` 键）的单元判据在 test_derivationCitation.py。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.read_surface import ENV_FLAG, FactSurface
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

RULE_ID = "high_risk_order"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}],
    )).factId


@pytest.fixture
def seeded(store):
    """视频同款场景：两笔订单，只有高风险那笔会被规则归入 HighRiskOrder。"""
    registry = OntologyTermRegistry(store)
    registry.registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级",
         "domain": ["Order"]},
    ])
    _admit(store, "订单D01", IS_A_PREDICATE, "Order")
    _admit(store, "订单D01", "hasRiskLevel", "High")
    registry.assignSubjectType(store.resolveSubjectKey("default", "订单D01"), "Order")
    ForwardChainingEngine(
        store, gateFactory=lambda st: productionAdmissionGate(st)
    ).registerRule(
        RULE_ID, IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
        headObjectConst="HighRiskOrder")
    derivedIds = {
        f["fact_id"] for f in store.searchableFacts(agentId="default")
        if f["predicate_term_id"] == IS_A_PREDICATE and f["object_term"] == "HighRiskOrder"
    }
    assert len(derivedIds) == 1, "场景没长出推导事实——后面的判据会对着空气断言"
    return {"store": store, "derivedId": derivedIds.pop()}


def _search(store, query="订单D01"):
    """开闸走真读面；关闸态由另一格单独判。"""
    return FactSurface(store).search(query, limit=10, agentId="default")


class TestObserveStateAtFactSurface:
    def test_derivedFactIsNotASurfacedItemByDefault(self, seeded, monkeypatch):
        """观察态（默认）：推导事实不得成为检索条目出口的一员。"""
        monkeypatch.setenv(ENV_FLAG, "on")
        items = _search(seeded["store"])

        assert all(i["lineage_id"] != seeded["derivedId"] for i in items), (
            "观察态下推导事实仍被当成检索条目出去——拍板项 2 的默认态没落地"
        )
        assert items, "读面整池空了：过滤把显式事实一起带走，不是治理是塌方"

    def test_routeFlagLetsTheDerivedFactSurface(self, seeded, monkeypatch):
        """翻主路开关（双向可回滚）：推导事实照常出去。"""
        monkeypatch.setenv(ENV_FLAG, "on")
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        items = _search(seeded["store"])

        assert seeded["derivedId"] in {i["lineage_id"] for i in items}, \
            "开关翻主路后仍被过滤——灰度就成了单向门"

    def testGateOffBehaviourUnchanged(self, seeded, monkeypatch):
        """关闸态逐位等于旧行为：空池，且不是因为过滤。"""
        monkeypatch.delenv(ENV_FLAG, raising=False)
        assert FactSurface(seeded["store"]).search("订单D01", limit=10, agentId="default") == []

    def testExplicitFactsStillSurfaceWithDerivationMark(self, seeded, monkeypatch):
        """显式事实不许被标成推导——溯源失去区分力等于没有溯源。"""
        monkeypatch.setenv(ENV_FLAG, "on")
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        items = _search(seeded["store"])

        assert items and all("derivation" in i for i in items), \
            "读面出口没带溯源标注：调用方无从分辨观察事实与推导事实"
        explicit = [i for i in items if i["lineage_id"] != seeded["derivedId"]]
        assert all(i["derivation"] == {"derived": False} for i in explicit)

    def testDerivedItemCarriesRuleAndPremiseCount(self, seeded, monkeypatch):
        """翻主路后那条推导必须自带规则号与前提数（溯源的最小契约）。"""
        monkeypatch.setenv(ENV_FLAG, "on")
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")
        derived = [i for i in _search(seeded["store"])
                   if i["lineage_id"] == seeded["derivedId"]]

        assert len(derived) == 1
        info = derived[0]["derivation"]
        assert info["derived"] is True
        assert info["ruleId"] == RULE_ID
        assert info["premiseCount"] == 2, "两条前提：is_a Order 与 hasRiskLevel High"
