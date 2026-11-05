"""观察态灰度必须落在图谱走查上——这才是推导事实进对话的真实路径（B1 拍板项 2 ＋ B4）。

实测定位（2026-11-05，桥接场景亲验）：条件类推导 `订单D01 is_a HighRiskOrder` 自己不
带条目（推导行的 medium_ref 是 `rule:<id>`），但走查把它当**跳板**——第二跳落到
挂在条目上的显式事实，于是 `entry:doc1` 以图谱权重（默认 on，0.10）进 RRF 排序，
最后随条目注入对话。所以只在读面 `FactSurface.search` 摘条目不够：那条管的是种子锚点，
管不到递归段。

判据三条各钉一件事：
1. 观察态（默认）：经推导跳板才走得到的条目，不许出现在走查结果里；
2. 翻主路：同一条目照旧走得到（灰度是双向的，不是单向门）；
3. 非虚设控制：把那一跳换成**显式** is_a，同一条目必须仍在——
   证明本档挡的是"推导"这件事，不是把走查整个掐死。

本档不 import 待建模块（红要红在行为断言上）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import IS_A_PREDICATE, OntologyTermRegistry

ENTRY_ID = "doc1"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, mediumRef="unit:test"):
    content = "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": mediumRef, "statementText": content}],
    )).factId


def _terms(store):
    OntologyTermRegistry(store).registerMany([
        {"termId": "Order", "kind": "concept", "label": "订单"},
        {"termId": "HighRiskOrder", "kind": "concept", "label": "高风险订单"},
        {"termId": "hasRiskLevel", "kind": "relation", "label": "风险等级"},
        {"termId": "requiresAction", "kind": "relation", "label": "需动作"},
    ])
    return OntologyTermRegistry(store)


def _bridgeToEntry(store, registry):
    """挂在那种类上的显式事实——它的断言介质里带 entry:，是条目进排序的唯一通道。"""
    _admit(store, "HighRiskOrder", "requiresAction", "复核",
           mediumRef="entry:%s" % ENTRY_ID)


def _deriveViaRule(store):
    """走得到的那一跳由规则推导产生。"""
    _admit(store, "订单D01", IS_A_PREDICATE, "Order")
    _admit(store, "订单D01", "hasRiskLevel", "High")
    OntologyTermRegistry(store).assignSubjectType(
        store.resolveSubjectKey("default", "订单D01"), "Order")
    ForwardChainingEngine(
        store, gateFactory=lambda st: productionAdmissionGate(st)
    ).registerRule(
        "high_risk_order", IS_A_PREDICATE,
        [{"atom": IS_A_PREDICATE, "subject": "X", "objectConst": "Order"},
         {"atom": "hasRiskLevel", "subject": "X", "objectConst": "High"}],
        headObjectConst="HighRiskOrder")


def _walkEntries(store):
    hops = GraphFactWalker(store, agentId="default").walkFromQuery(
        "订单D01 风险", limit=10)
    return [h for h in hops if h.get("entry_id") == ENTRY_ID]


class TestObserveStateAtGraphWalk:
    def testDerivedBridgeDoesNotPromoteEntryByDefault(self, store):
        registry = _terms(store)
        _bridgeToEntry(store, registry)
        _deriveViaRule(store)

        assert _walkEntries(store) == [], (
            "观察态下推导仍能把条目顶进图谱排序——灰度没作用在真实路径上"
        )

    def testRouteFlagLetsTheDerivedBridgeThrough(self, store, monkeypatch):
        registry = _terms(store)
        _bridgeToEntry(store, registry)
        _deriveViaRule(store)
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")

        assert _walkEntries(store), "翻主路后这条跳板仍被摘掉——灰度成了单向门"

    def testExplicitBridgeIsNeverCollateralDamage(self, store):
        """非虚设控制：同一跳换成显式 is_a，条目必须照旧走得到。"""
        registry = _terms(store)
        _bridgeToEntry(store, registry)
        _admit(store, "订单D01", IS_A_PREDICATE, "Order")
        _admit(store, "订单D01", IS_A_PREDICATE, "HighRiskOrder")

        assert _walkEntries(store), (
            "显式声明的类归属也被过滤带走了——那是掐死走查，不是治理"
        )

    def testDerivedBridgeIsFlaggedOnTheEntryItPromotes(self, store, monkeypatch):
        """翻主路时，被推导跳板带进来的那条条目要带得出「这跳是推的」。

        走查只回 hop>=2 的叶子行，跳板那一跳不在返回里 ⇒ 标注必须长在**路径来源**上，
        长不到跳板上。把标志挂在叶子上，图谱路由才知道自己顶上来的是推导还是观察。
        """
        registry = _terms(store)
        _bridgeToEntry(store, registry)
        _deriveViaRule(store)
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")

        entryHops = _walkEntries(store)

        assert entryHops, "翻主路后这条跳板该把条目带进来"
        assert entryHops[0]["via_derived"] is True, entryHops[0]

    def testExplicitBridgeCarriesNoDerivedFlag(self, store, monkeypatch):
        """同一跳换成显式声明时不许带上 via_derived——否则标注失去区分力。"""
        registry = _terms(store)
        _bridgeToEntry(store, registry)
        _admit(store, "订单D01", IS_A_PREDICATE, "Order")
        _admit(store, "订单D01", IS_A_PREDICATE, "HighRiskOrder")
        monkeypatch.setenv("NEUROVA_CONDITION_CLASSES_ROUTE", "1")

        entryHops = _walkEntries(store)

        assert entryHops and all(h["via_derived"] is False for h in entryHops), \
            [h["via_derived"] for h in entryHops]
