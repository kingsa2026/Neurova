# -*- coding: utf-8 -*-
"""事件/时间模式（升级计划 §12.4 设计 3 ＋验收门点名判据）。

票面：`Event` 类型＋`hasParticipant/hasTime` 关系＋Allen 区间关系
（before/after/overlaps/during）作为**受控关系术语**；OWL-Time 只做导出映射，
**不做运行时时间推理**。

为什么判据钉在「登记与校验」而不是「时间算术」：本仓零第三方依赖、不引区间代数
求解器，Allen 关系的价值在于让抽取/检索侧有一套受控词汇可落，而不是在库里推导
"A before B 且 B before C ⇒ A before C"。所以本档同时钉反面：这四条关系**不得**
自动生成传递规则（`testNoRuntimeTimeReasoning`）——引了就越过了 §12 的语义边界。

播种落在 `upper_lite`（B9 L1 的种子 owner），非 default 租户由咽喉首跳补种，
与既有上层术语同一纪律。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology import upper_lite
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.turtle import serializeAll
from neurova.knowledge.ontology.validation import OntologyValidationReport

EVENT_TIME_TERMS = ("hasParticipant", "hasTime", "before", "after", "overlaps", "during")
ALLEN_TERMS = ("before", "after", "overlaps", "during")
OWL_TIME = "https://www.w3.org/2006/time#"


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    return OntologyTermRegistry(store)


def _request(subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate,
        objectTerm=obj, content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit",
                     "mediumRef": "unit:test", "statementText": content}])


class TestEventTimeVocabularyIsSeeded:
    def testAllSixTermsLandAsRelations(self, registry):
        for termId in EVENT_TIME_TERMS:
            term = registry.term(termId, tenantId="default")
            assert term is not None, "%s 没随 upper-lite 播种进来" % termId
            assert term["kind"] == "relation", "%s 不是关系术语" % termId

    def testDomainIsEventForEveryEventTimeRelation(self, registry):
        for termId in EVENT_TIME_TERMS:
            assert registry.domainOf(termId, tenantId="default") == ["Event"], (
                "%s 的定义域不是 Event——事件属性关系挂到别的类型上没人拦" % termId)

    def testAllenRelationsInheritFromTemporal(self, registry):
        """四条 Allen 关系挂在既有 `temporal` 之下（subproperty），不新造第二组时间词汇。"""
        for termId in ALLEN_TERMS:
            assert registry.isSubtypeOf(termId, "temporal", tenantId="default"), (
                "%s 没并到 temporal 父属性下——时间关系词汇分叉成两套" % termId)

    def testSeedingIsIdempotentAndKeepsWriterOverrides(self, store, registry):
        registry.register("hasTime", "relation", label="作者改过的标签",
                          domain=["Event"], tenantId="default")
        assert upper_lite.seedUpperLite(registry) >= 0
        # 只补缺：seedMissing 不许把写入方改过的 label 抹回默认值
        assert registry.term("hasTime", tenantId="default")["label"] == "作者改过的标签"


class TestOwlTimeExportMappingOnly:
    def testAllenRelationsCarryOwlTimeIri(self, registry):
        for termId in ALLEN_TERMS:
            mapping = registry.term(termId, tenantId="default")["external_iris"]
            assert mapping.get("skos_exactMatch") == OWL_TIME + termId, (
                "%s 缺 OWL-Time 精确匹配槽——导出映射没落在唯一那个槽位上" % termId)

    def testExportedTurtleUsesTheExternalIri(self, store, registry):
        text = serializeAll(store, tenantId="default")
        assert (OWL_TIME + "before") in text, (
            "Turtle 导出里看不到 time:before——外部 IRI 只登记没接进互通面")

    def testNoRuntimeTimeReasoningIsSeeded(self, store, registry):
        """反面判据：这四条关系不得自动生成传递/组合规则（不引区间代数）。"""
        heads = {str(rule.get("head_predicate") or "")
                 for rule in ForwardChainingEngine(store).rules(tenantId="default")}
        assert not heads & set(ALLEN_TERMS), (
            "Allen 关系被建成了可推理谓词——§12 语义边界是「不做运行时时间推理」")


class TestDomainEnforcedAtWriteSurface:
    def testHasTimeOnNonEventSubjectIsDomainViolation(self, store, registry):
        report = OntologyValidationReport(registry)
        key = store.upsertSubject("default", "某文档")
        registry.assignSubjectType(key, "Document")

        violations = report.violations(_request("某文档", "hasTime", "2026-11-06"), key)

        assert [v["rule"] for v in violations] == ["domain"], (
            "非事件主体挂 hasTime 没被判 domain 违规——受控词汇只是装饰")

    def testHasTimeOnEventSubjectIsAccepted(self, store, registry):
        report = OntologyValidationReport(registry)
        key = store.upsertSubject("default", "某次下单")
        registry.assignSubjectType(key, "Event")

        violations = report.violations(_request("某次下单", "hasTime", "2026-11-06"), key)

        assert [v for v in violations if v["rule"] == "domain"] == [], (
            "Event 主体挂 hasTime 也被拒——定义域声明写错了")

    def testIntervalBetweenEventsPassesDomainAndRange(self, store, registry):
        report = OntologyValidationReport(registry)
        left = store.upsertSubject("default", "事件甲")
        right = store.upsertSubject("default", "事件乙")
        registry.assignSubjectType(left, "Event")
        registry.assignSubjectType(right, "Event")

        violations = report.violations(_request("事件甲", "before", "事件乙"), left)

        assert [v for v in violations if v["rule"] in ("domain", "range")] == []
