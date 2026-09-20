"""事实血缘查看与 Turtle 导出（工单 024，G01 的用户可见面）。

两条判据把"看起来能溯源"和"真能溯源"分开：
- **缺维要显式报缺**：没有断言、没有活动、没有来源介质，各自是一条缺失维；
  回一条空链会被读成"查过了，没有"，那比没查更糟。
- **导出的文本要能自己读回来**：不引第三方校验器，序列化与解析同一份语法定义，
  往返无损才算格式对（中文、引号、换行都在往返里）。
"""

from __future__ import annotations

import json

import pytest

from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.lineage_view import FactLineageView
from neurova.knowledge.ontology.turtle import parseTurtle, serializeFact


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


def _admit(store, subject, predicate, obj, text=None, actorId="u1", medium="unit:test"):
    content = text or "%s %s %s" % (subject, predicate, obj)
    return productionAdmissionGate(store, toolVersion="unit").admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "user", "actorId": actorId, "mediumRef": medium,
                     "statementText": content}],
    ), allowPendingSegments=True).factId


class TestLineageView:
    def test_assertionActivityAndMediumAllPresent(self, store):
        factId = _admit(store, "青海湖", "is_a", "湖泊", text="青海湖是高原湖泊")

        view = FactLineageView(store).trace(factId)

        assert view["provenance_state"] == "evidenced"
        assert view["missing"] == []
        hop = view["hops"][0]
        assert hop["kind"] == "assertion"
        assert hop["actor_id"] == "u1" and hop["medium_ref"] == "unit:test"
        assert hop["statement_text"] == "青海湖是高原湖泊"
        assert hop["activity_kind"] == "admit" and hop["activity_id"]

    def test_factWithoutAssertionsSaysSoInsteadOfAnEmptyChain(self, store):
        key = store.upsertSubject("default", "裸事实")
        factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="is_a",
                                  objectTerm="未知", content="没有断言")

        view = FactLineageView(store).trace(factId)

        assert view["provenance_state"] == "unevidenced"
        assert "assertions" in view["missing"] and view["hops"] == []

    def test_assertionWithoutActivityReportsTheMissingDimension(self, store):
        key = store.upsertSubject("default", "手写")
        factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="is_a",
                                  objectTerm="直写", content="直写的一行")
        store.insertAssertion(factId, actorType="user", actorId="u9", mediumRef="m",
                              statementText="说一句", statementHash="h" * 16)

        view = FactLineageView(store).trace(factId)

        assert "activity" in view["missing"]
        assert view["hops"][0]["kind"] == "assertion"

    def test_derivedFactWalksToItsPremisesOriginalText(self, store):
        """UI 要从一条结论走到"原始陈述文本"：推导跳必须带出前提及其断言。"""
        from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine

        a = _admit(store, "甲", "part_of", "乙", text="甲是乙的一部分")
        b = _admit(store, "乙", "part_of", "丙", text="乙是丙的一部分")
        engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
            st, toolVersion="rule"))
        engine.registerRule("trans", "part_of", [{"atom": "part_of", "subject": "X",
                                                 "object": "Y"},
                                                {"atom": "part_of", "subject": "Y",
                                                 "object": "Z"}])
        engine.fireAll(agentId="default")

        view = FactLineageView(store)
        conclusion = view.findDerivedBy(store, "trans")

        assert conclusion
        hops = view.trace(conclusion)["hops"]
        kinds = [h["kind"] for h in hops]
        assert "derivation" in kinds
        premiseTexts = [t for h in hops if h["kind"] == "derivation"
                        for p in h["premises"] for t in p["statement_texts"]]
        assert "甲是乙的一部分" in premiseTexts and "乙是丙的一部分" in premiseTexts
        assert view.trace(conclusion)["derivation"]["rule_id"] == "trans"

    def test_integrityReadingTravelsWithTheChain(self, store):
        factId = _admit(store, "甲", "is_a", "乙")

        hop = FactLineageView(store).trace(factId)["hops"][0]

        assert hop["seq"] == 1 and hop["digest"], "血缘跳要带上链位与摘要，巡检才接得上"

    def test_unknownFactIsNotFoundNotCrashing(self, store):
        assert FactLineageView(store).trace("fact_nope") is None


class TestTurtleRoundTrip:
    def test_exportedTurtleParsesBackWithEveryField(self, store):
        factId = _admit(store, "青海湖", "is_a", "湖泊", text='他说："青海湖是高原湖泊"\n第二行')

        text = serializeFact(store, factId)
        parsed = parseTurtle(text)

        assert any(p == "kbg:is_a" and o == '"湖泊"@zh' for _, p, o in parsed), parsed
        statement = [o for _, p, o in parsed if p == "kbg:assertedStatement"]
        assert statement == ['"他说：\\"青海湖是高原湖泊\\"\\n第二行"@zh'], statement
        assert "kbg:recordedAt" in {p for _, p, _ in parsed}
        assert text.startswith("@prefix kbg:")

    def test_derivedFactExportsItsRuleAndPremises(self, store):
        from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine

        _admit(store, "甲", "part_of", "乙")
        _admit(store, "乙", "part_of", "丙")
        engine = ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
            st, toolVersion="rule"))
        engine.registerRule("trans", "part_of", [{"atom": "part_of", "subject": "X",
                                                 "object": "Y"},
                                                {"atom": "part_of", "subject": "Y",
                                                 "object": "Z"}])
        engine.fireAll(agentId="default")
        view = FactLineageView(store)
        conclusion = view.findDerivedBy(store, "trans")

        parsed = parseTurtle(serializeFact(store, conclusion))

        predicates = {p for _, p, _ in parsed}
        assert {"kbg:derivedVia", "kbg:derivedFrom"} <= predicates

    def test_unparsableInputIsRefusedNotHalfParsed(self):
        from neurova.knowledge.ontology.turtle import TurtleSyntaxError

        with pytest.raises(TurtleSyntaxError):
            parseTurtle('kbg:x kbg:y "没闭合')

    def test_exportWithoutProvenanceMarksTheGapInText(self, store):
        key = store.upsertSubject("default", "裸事实")
        factId = store.upsertFact(agentId="default", subjectKey=key, predicateTermId="is_a",
                                  objectTerm="未知", content="没有断言")

        text = serializeFact(store, factId)

        assert "kbg:provenanceState \"unevidenced\"" in text, \
            "导出文本也要说清这行没依据，别让读的人以为查过了"
