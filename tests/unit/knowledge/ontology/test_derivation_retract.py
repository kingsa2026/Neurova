"""推导账本与精确撤销（工单 022，G09 收口）：撤一条前提，只退该退的结论。

判据的形状：
- 撤销沿推导边往下走，**原始事实一律不碰**——把"改规则"和"删用户说过的话"混成
  一套动作，是这类引擎最典型的事故。
- 让前提离开 active 的每一条路径（撤回 / 取代 / 到期）都必须触发同一套级联，
  漏一条就是"结论踩在已死的前提上继续被检索"。
- 规则改版不留旧结论；多退的结论在前提恢复后能长回来，不是永久伤残。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.derivation_ledger import DerivationLedger
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine

PART_OF = [{"atom": "part_of", "subject": "X", "object": "Y"},
           {"atom": "part_of", "subject": "Y", "object": "Z"}]
RULE_ID = "part_of_transitive"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion="rule-engine"))


def _gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ), allowPendingSegments=True).factId


def _live(store):
    """当前可检索的 (主体, 谓词, 客体) 集合——断言只看这个，不数行数。"""
    return {(f["canonical_label"], f["predicate_term_id"], f["object_term"])
            for f in store.searchableFacts(agentId="default")}


def _fourLinkChain(store):
    """甲→乙→丙→丁：传递闭包两跳，产出一条二层结论，级联深度为 2。"""
    a = _admit(store, "甲", "part_of", "乙")
    b = _admit(store, "乙", "part_of", "丙")
    c = _admit(store, "丙", "part_of", "丁")
    return a, b, c


def _fired(store, engine):
    a, b, c = _fourLinkChain(store)
    engine.registerRule(RULE_ID, "part_of", PART_OF)
    report = engine.fireAll(agentId="default")
    return a, b, c, report


class TestLedgerIsAttached:
    def test_storeCarriesItsOwnLedgerAndV10Lands(self, store):
        assert isinstance(store._derivationLedger, DerivationLedger)
        assert int(store._conn.execute("PRAGMA user_version").fetchone()[0]) >= 10
        names = {r[0] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"knowledge_derivation_edges", "ontology_rule_fires"} <= names

    def test_derivationEdgesAndFireLogAreWritten(self, store, engine):
        a, b, c, report = _fired(store, engine)
        derivedJiaBing = _idOf(store, "甲", "part_of", "丙")

        premises = {e["premise_fact_id"] for e in store._derivationLedger.premisesOf(derivedJiaBing)}
        assert premises == {a, b}, "二层结论 甲→丙 的依据就是那两条原始事实"
        backs = {e["derived_fact_id"] for e in store._derivationLedger.derivationsOf(a)}
        assert derivedJiaBing in backs
        fires = store._derivationLedger.fires(RULE_ID)
        assert fires and derivedJiaBing in fires[-1]["derived_fact_ids"]


class TestPreciseRetraction:
    def test_retractingAPremiseRetiresOnlyItsDependents(self, store, engine):
        a, b, c, report = _fired(store, engine)
        assert _live(store) >= {("甲", "part_of", "丙"), ("乙", "part_of", "丁"),
                                ("甲", "part_of", "丁")}

        store.retract(a, reason="说法收回")

        live = _live(store)
        assert ("甲", "part_of", "乙") not in live
        assert ("甲", "part_of", "丙") not in live, "直接依赖被撤前提的结论要退"
        assert ("甲", "part_of", "丁") not in live, "二层结论的依据已退，它自己也必须退"
        assert ("乙", "part_of", "丙") in live and ("丙", "part_of", "丁") in live, \
            "原始事实从不被级联碰"
        assert ("乙", "part_of", "丁") in live, "与甲无关的结论不许陪葬"

    def test_rowsAreNeverDeletedByACascade(self, store, engine):
        a, b, c, report = _fired(store, engine)
        before = store.factCount()

        store.retract(a)

        assert store.factCount() == before, "撤销是状态推进不是删除，溯源要读得到"
        assert store.fact(_idOf(store, "甲", "part_of", "丁"))["status"] == "retracted"

    def test_retiringAnUnrelatedFactTouchesNothing(self, store, engine):
        a, b, c, report = _fired(store, engine)
        loose = _admit(store, "猫", "is_a", "动物")

        store.retract(loose)

        assert _live(store) == {("甲", "part_of", "乙"), ("乙", "part_of", "丙"),
                                ("丙", "part_of", "丁"), ("甲", "part_of", "丙"),
                                ("乙", "part_of", "丁"), ("甲", "part_of", "丁")}

    def testSupersedingAPremiseAlsoRetires(self, store, engine):
        a, b, c, report = _fired(store, engine)
        # 真走裁决路径：同一 (主体, 谓词) 上的新说法把旧说法顶掉（007 的 value 冲突），
        # 取代落地后旧说法的依据链必须一起退。
        rival = _admit(store, "甲", "part_of", "乙支")

        assert store.fact(a)["status"] == "superseded"
        live = _live(store)
        assert ("甲", "part_of", "丙") not in live and ("甲", "part_of", "丁") not in live
        assert ("甲", "part_of", "乙支") in live and ("乙", "part_of", "丁") in live

    def testExpiringAPremiseAlsoRetires(self, store, engine):
        a, b, c, report = _fired(store, engine)
        store.setValidUntil(a, "2000-01-01T00:00:00+00:00")

        store.expireDueFacts()

        live = _live(store)
        assert ("甲", "part_of", "乙") not in live
        assert ("甲", "part_of", "丙") not in live, "到期同样是前提离场"
        assert ("乙", "part_of", "丁") in live

    def testCascadeIsNotRunTwicePerFact(self, store, engine):
        """级联只走一遍：嵌套回调里再走一次会把层序打乱，也会把计数翻倍。"""
        a, b, c, report = _fired(store, engine)
        seen = []
        original = store._derivationLedger._retractDerived

        def spy(factId, reason):
            seen.append(factId)
            return original(factId, reason)

        store._derivationLedger._retractDerived = spy
        store.retract(a)

        assert len(seen) == len(set(seen)), "同一结论被退了两次"


class TestRuleRevision:
    def testNewVersionRetiresOldConclusions(self, store, engine):
        a, b, c, report = _fired(store, engine)
        assert ("甲", "part_of", "丁") in _live(store)

        engine.registerRule(RULE_ID, "part_of", PART_OF, version="v2")

        live = _live(store)
        assert ("甲", "part_of", "丙") not in live and \
            ("甲", "part_of", "丁") not in live and ("乙", "part_of", "丁") not in live, \
            "改版后旧版结论一条都不许留"
        assert ("甲", "part_of", "乙") in live, "改版只清推导，不清原始事实"

        engine.fireAll(agentId="default")

        assert ("甲", "part_of", "丙") in _live(store), "重推要把结论长回来"
        ledger = store._derivationLedger
        versions = {e["rule_version"] for e in ledger.premisesOf(_idOf(store, "甲", "part_of", "丙"))}
        assert versions == {"v1", "v2"}, "推导边是追加的账：改版前那一次留痕，重推这一次也记着"
        assert ledger.fires(RULE_ID)[-1]["rule_version"] == "v2"

    def testSameVersionReRegisterKeepsConclusions(self, store, engine):
        a, b, c, report = _fired(store, engine)

        engine.registerRule(RULE_ID, "part_of", PART_OF, version="v1")

        assert ("甲", "part_of", "丁") in _live(store), "同版本重写规则不是改版"


class TestConclusionCanComeBack:
    def testRefireAfterPremiseRevivedRestoresTheConclusion(self, store, engine):
        a, b, c, report = _fired(store, engine)
        store.retract(a)
        assert ("甲", "part_of", "丙") not in _live(store)

        store.reviveRetracted(a, reason="收回我的话")
        engine.fireAll(agentId="default")

        assert ("甲", "part_of", "丙") in _live(store), "前提回来了，结论不该永久伤残"
        assert ("甲", "part_of", "丁") in _live(store)


def _idOf(store, label, predicate, obj):
    """按 (主体, 谓词, 客体) 找行——不看 status，撤销后的行正是这些用例要看的东西。"""
    with store._lock:
        rows = store._conn.execute(
            "SELECT f.fact_id AS fact_id, s.canonical_label AS label FROM knowledge_facts f"
            " JOIN knowledge_subjects s ON s.subject_key = f.subject_key"
            " WHERE f.predicate_term_id = ? AND f.object_term = ?", (predicate, obj)).fetchall()
    for r in rows:
        if r["label"] == label:
            return r["fact_id"]
    raise AssertionError("没有这条在库事实: %s %s %s" % (label, predicate, obj))
