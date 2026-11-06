# -*- coding: utf-8 -*-
"""B9 L1 上层层（升级计划 §12.2）：upper-lite 种子、身份判据、punning 守卫。

upper-lite 是最小上层本体：Entity→Continuant(Agent/Document/Concept)＋Occurrent(Event)。
对齐 BFO 只做 external_iris 导出映射，不整包引入、不做运行时推理。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.identity.subject_resolver import SubjectResolver
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.upper_lite import UPPER_LITE_TERMS, seedUpperLite


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    return OntologyTermRegistry(store)


class TestUpperLiteSeeds:
    def test_seedIsIdempotentAndComplete(self, registry):
        # 构造期已播种（registry.__init__ → seedUpperLite）：首调只补缺＝0 新增，
        # 断言落在完整性与幂等上。
        planted = seedUpperLite(registry)
        again = seedUpperLite(registry)

        assert planted == 0, "构造期已种，首调只补缺＝0"
        assert again == 0, "重复播种零新增（只补缺语义）"
        # 完整性按 kind 分开钉：类只许七个（整包引入 BFO/SUMO 会把这条顶红），
        # 事件/时间那一组是关系词汇（§12.4 设计 3），不与类数混计。
        assert len([t for t in UPPER_LITE_TERMS if t["kind"] == "concept"]) == 7
        assert len([t for t in UPPER_LITE_TERMS if t["kind"] == "relation"]) == 6
        for termId in ("Entity", "Continuant", "Occurrent", "Agent", "Document",
                       "Concept", "Event"):
            assert registry.term(termId) is not None, "%s 该在表里" % termId

    def test_parentChainMatchesUpperStructure(self, registry):
        seedUpperLite(registry)

        assert registry.term("Continuant")["parent_term_id"] == "Entity"
        assert registry.term("Occurrent")["parent_term_id"] == "Entity"
        for child in ("Agent", "Document", "Concept"):
            assert registry.term(child)["parent_term_id"] == "Continuant"
        assert registry.term("Event")["parent_term_id"] == "Occurrent"

    def test_bfoMappingOnlyInExternalIris(self, registry):
        seedUpperLite(registry)

        entity = registry.term("Entity")
        assert "BFO_0000001" in str(entity.get("external_iris")), \
            "BFO 对齐只进导出映射"
        assert registry.term("Event")["external_iris"].get("bfo"), "Event 有 BFO 映射"

    def test_exportCarriesBfoIri(self, store, registry):
        seedUpperLite(registry)
        from neurova.knowledge.ontology.turtle import serializeAll

        doc = serializeAll(store, tenantId="default")
        assert "BFO_0000001" in doc, "BFO 映射可从导出读出"


class TestIdentityKeys:
    def test_identityKeysRoundTrip(self, registry):
        registry.register("customer_account", "concept",
                          identityKeys=["canonical_label", "external_id"])

        assert registry.term("customer_account")["identity_keys"] == \
            ["canonical_label", "external_id"]

    def test_resolverHonoursIdentityKeyExactMatch(self, registry):
        """identity_keys 声明 canonical_label 时，精确同名主体直接命中，不走相似度。"""
        subjects = [
            {"subject_key": "s-1", "canonical_label": "中国工商银行", "type_term_id": "Org",
             "aliases": ["工行"]},
            {"subject_key": "s-2", "canonical_label": "工商银行分行", "type_term_id": "Org",
             "aliases": []},
        ]
        resolver = SubjectResolver()

        outcome = resolver.resolve("中国工商银行", subjects,
                                   identityKeys=["canonical_label"])

        assert outcome.subjectKey == "s-1" and not outcome.needsHumanReview

    def test_resolverIdentityKeyOnAttributes(self, registry):
        """external_id 类判据落在主体 attributes 上；无该属性的走缺省回退。"""
        subjects = [
            {"subject_key": "s-ext", "canonical_label": "客户C01", "type_term_id": "Account",
             "aliases": [], "attributes": {"external_id": "EXT-42"}},
            {"subject_key": "s-other", "canonical_label": "客户C01分身", "type_term_id": "Account",
             "aliases": [], "attributes": {}},
        ]
        resolver = SubjectResolver()

        outcome = resolver.resolve("任意标签", subjects,
                                   identityKeys=["external_id"],
                                   identityValues={"external_id": "EXT-42"})

        assert outcome.subjectKey == "s-ext"
        fallback = resolver.resolve("客户C01", subjects)
        assert fallback.subjectKey in {"s-ext", "s-other"}, "缺省回退仍可用"

    def test_unknownIdentityKeysIgnoredGracefully(self, registry):
        subjects = [{"subject_key": "s-1", "canonical_label": "甲", "type_term_id": "",
                     "aliases": [], "attributes": {}}]
        resolver = SubjectResolver()

        outcome = resolver.resolve("甲", subjects, identityKeys=["warp_drive"])

        assert outcome.subjectKey == "s-1", "未支持的判据键忽略，缺省回退兜住"


class TestPunningGuard:
    def test_termIdAsSubjectKeyIsWarningNotViolation(self, store, registry):
        """term_id 当主体用：记 warning 不阻断——存量与显式同名共存不拒写。"""
        registry.register("Order", "concept")
        registry.register("Entity", "concept")
        from neurova.knowledge.ontology.validation import OntologyValidationReport

        validator = OntologyValidationReport(registry)
        gate = productionAdmissionGate(store, toolVersion="b9")

        receipt = gate.admit(AdmissionRequest(
            agentId="default", subjectLabel="Order", predicateTermId="is_a",
            objectTerm="Entity", content="Order is_a Entity",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test", "statementText": "Order is_a Entity"}],
        ))

        assert receipt.factId, "punning 是 warning，不拒写"
        findings = validator.findings(
            _requestLike(predicate="is_a", objectTerm="Entity"), "Order")
        kinds = {f["kind"] for f in findings}
        assert "warning" in kinds
        assert validator.violations(_requestLike(predicate="is_a", objectTerm="Entity"),
                                    "Order") == [], "warning 不进 violation 子集"


def _requestLike(predicate: str, objectTerm: str):
    """构造 validation.findings 可吃的最小请求形状（与 AdmissionRequest 同字段面）。"""
    from neurova.knowledge.foundation.admission import AdmissionRequest

    return AdmissionRequest(agentId="default", subjectLabel="Order",
                            predicateTermId=predicate, objectTerm=objectTerm,
                            content="", qualifier={})
