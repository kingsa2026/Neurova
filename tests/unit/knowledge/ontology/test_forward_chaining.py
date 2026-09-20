"""前向链推理（工单 021，G09）：规则是数据、推导可解释、循环报错不静默截断。

判据都走真写入口：推导事实必须经咽喉落库（带 `derived_by` 与规则断言），
否则推理产出的那批行就是"没有主体消解、没有血缘、没有置信"的孤儿——
B03/G12 换了个入口复活。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine, RuleError

PART_OF = [{"atom": "part_of", "subject": "X", "object": "Y"},
           {"atom": "part_of", "subject": "Y", "object": "Z"}]


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


def _chain(store):
    """甲 part_of 乙，乙 part_of 丙：传递一步，推出 甲 part_of 丙。"""
    _admit(store, "甲", "part_of", "乙")
    _admit(store, "乙", "part_of", "丙")


class TestRuleRegistryIsData:
    def test_v9LandsAndRulesTableExists(self, store, engine):
        names = {r[0] for r in store._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"ontology_terms", "ontology_rules"} <= names
        assert int(store._conn.execute("PRAGMA user_version").fetchone()[0]) >= 9

    def test_transitiveRuleProducesExactlyTheExpectedFacts(self, store, engine):
        _chain(store)
        engine.registerRule("part_of_transitive", "part_of", PART_OF)
        before = store.factCount()

        report = engine.fireAll(agentId="default")
        derived = store.searchableFacts(agentId="default")

        assert len(report["derived"]) == 1
        assert store.factCount() == before + 1, "两条原始事实只该多出一条 甲 part_of 丙"
        assert any(f["object_term"] == "丙" and "甲" in f["canonical_label"] for f in derived)

    def test_secondFireAddsNothing(self, store, engine):
        _chain(store)
        engine.registerRule("part_of_transitive", "part_of", PART_OF)
        first = engine.fireAll(agentId="default")
        second = engine.fireAll(agentId="default")

        assert first["derived"] and second["derived"] == [], "同内容必须折回同一行，不产生新事实"

    def test_derivedFactIsExplainable(self, store, engine):
        _chain(store)
        engine.registerRule("part_of_transitive", "part_of", PART_OF)
        factId = engine.fireAll(agentId="default")["derived"][0]

        fact = store.fact(factId)

        assert "part_of_transitive" in str(fact.get("qualifier", {}))
        assertions = store.assertions(factId)
        assert assertions[-1]["medium_ref"] == "rule:part_of_transitive", \
            "推导事实的来源要指到规则，不能伪装成观察"


class TestStratifiedNegation:
    def test_negationBlocksTheConclusion(self, store, engine):
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "甲", "excluded_from", "丙")
        engine.registerRule("part_of_transitive", "part_of", PART_OF + [
            {"not": "excluded_from", "subject": "X", "object": "Z"}])
        _admit(store, "乙", "part_of", "丙")

        engine.fireAll(agentId="default")

        assert store.factCount() == 3, "被否定的那条结论不许落地"

    def test_negationThroughCycleIsRefusedWithTheLoopNamed(self, store, engine):
        """p 的成立依赖"非 q"，而 q 又由 p 推出来：分层无解，必须报错并指出环。"""
        engine.registerRule("from_p", "q", [{"atom": "p", "subject": "X", "object": "Y"}])

        with pytest.raises(RuleError, match="循环"):
            engine.registerRule("from_q", "p", [
                {"atom": "p", "subject": "X", "object": "Y"},
                {"not": "q", "subject": "X", "object": "Y"},
            ])
        assert engine.rule("from_q") is None, "被拒的规则不许留下半行"

    def test_positiveSelfRecursionIsAllowedAndTerminates(self, store, engine):
        _chain(store)
        engine.registerRule("part_of_transitive", "part_of", PART_OF)

        report = engine.fireAll(agentId="default")

        assert report["iterations"] <= 3, "正递归靠不动点收敛，不是靠截断"


class TestRuleShapeIsEnforcedAtWrite:
    def test_brokenShapesRefused(self, engine):
        with pytest.raises(RuleError, match="没有任何肯定正文"):
            engine.registerRule("r", "p", [{"not": "q", "subject": "X", "object": "Y"}])
        with pytest.raises(RuleError, match="超过 2 个原子"):
            engine.registerRule("r", "p", PART_OF + [{"atom": "p", "subject": "Z", "object": "W"}])
        with pytest.raises(RuleError, match="接不上"):
            engine.registerRule("r", "p", [{"atom": "a", "subject": "X", "object": "Y"},
                                           {"atom": "b", "subject": "Z", "object": "W"}])
        with pytest.raises(RuleError, match="单个大写字母"):
            engine.registerRule("r", "p", [{"atom": "a", "subject": "x", "object": "Y"}])
        with pytest.raises(RuleError, match="atom 或 not"):
            engine.registerRule("r", "p", [{"atom": "a", "or": "b", "subject": "X",
                                            "object": "Y"}])
        assert engine.rules() == []


class TestTransitiveClosure:
    def test_closureIsComputedInOneQuery(self, store, engine):
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "丙")
        _admit(store, "丙", "part_of", "丁")
        keyJia = store.resolveSubjectKey("default", "甲")

        pairs = engine.transitiveClosure("default", "part_of")

        reached = {obj for subj, obj in pairs if subj == keyJia}
        assert reached == {"乙", "丙", "丁"}, "闭包要一次查到全链，而不是只到下一跳"

    def test_cycleInDataDoesNotHangTheClosure(self, store, engine):
        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "甲")

        pairs = engine.transitiveClosure("default", "part_of")

        assert len(pairs) == 2, "回环必须被 path 判重挡住"
