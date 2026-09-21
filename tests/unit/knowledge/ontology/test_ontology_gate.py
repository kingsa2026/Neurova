"""本体注册表 + 五条入库校验（工单 020，G08）。

判据要的是两件事：**加类型不改 Python**，以及**脏事实进不了底座**。
两条都用真写入口验，不用假对象——校验挂在咽喉段3，绕开咽喉的测试等于没测。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.ontology.validation import OntologyValidationReport


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def registry(store):
    return OntologyTermRegistry(store)


@pytest.fixture
def report(registry):
    return OntologyValidationReport(registry)


def _request(subject, predicate, obj, content="正文", **kw):
    payload = dict(agentId="default", subjectLabel=subject, predicateTermId=predicate,
                   objectTerm=obj, content=content,
                   assertions=[{"actorType": "pipeline", "actorId": "unit",
                                "mediumRef": "unit:test", "statementText": content}])
    payload.update(kw)
    return AdmissionRequest(**payload)


class TestRegistryIsData:
    def test_v8LandsAndSeedsTheNarrativePredicate(self, store, registry):
        # v9（规则表）之后链尾还在往前走，这里只验"至少到 v8、且 v8 建的表在"
        assert int(store._conn.execute("PRAGMA user_version").fetchone()[0]) >= 8
        term = registry.term("documented_as")
        assert term and term["kind"] == "relation"
        assert registry.maxCardinality("documented_as") is None, "同一主体可以有很多份文档"

    def test_newTypeFromDataAloneChangesWhatIsRejected(self, store, registry, report):
        """纯数据用例：只写一个 dict 就多出一条校验，不改任何 .py。"""
        registry.registerMany([
            {"termId": "device", "kind": "concept", "label": "设备"},
            {"termId": "router", "kind": "concept", "label": "路由器", "parentTermId": "device"},
            {"termId": "runs_on", "kind": "relation", "label": "运行于",
             "domain": ["device"], "rangeTerms": ["device"], "cardinality": 1,
             "requiredProps": ["env"]},
        ])
        key = store.upsertSubject("default", "边缘盒子")
        registry.assignSubjectType(key, "router")       # 子类经父类匹配定义域
        subject, predicate, obj = "边缘盒子", "runs_on", "device"

        assert report.violations(_request(subject, predicate, obj, qualifier={}), key), \
            "缺必填属性就该被拦下"
        findings = report.findings(_request(subject, predicate, obj,
                                           qualifier={"env": "prod"}), key)
        assert [f["rule"] for f in findings] == [], "补齐属性后同一条应当放行"

    def test_brokenStructureRefusedAtWriteTime(self, registry):
        with pytest.raises(ValueError, match="术语类别"):
            registry.register("x", "verb")
        with pytest.raises(ValueError, match="自己的父类"):
            registry.register("x", "concept", parentTermId="x")
        with pytest.raises(ValueError, match="父类未登记"):
            registry.register("y", "concept", parentTermId="nobody")
        with pytest.raises(ValueError, match="cardinality"):
            registry.register("z", "relation", cardinality=0)
        registry.register("person", "concept")
        with pytest.raises(ValueError, match="只有 concept"):
            registry.register("r", "relation", parentTermId="person")
        with pytest.raises(ValueError, match="类型未登记"):
            registry.assignSubjectType("subj_x", "ghost")
        assert [registry.term(bad) for bad in ("x", "y", "z", "r")] == [None] * 4, \
            "被拒的登记不许留下半行"
        for kept in ("person", "documented_as", "is_a"):
            assert registry.term(kept) is not None, "%s 该在表里" % kept

    def test_unregisteredTermsAreReportedNotRejected(self, registry, report):
        """把"没登记"当"不合法"，注册表覆盖率一变写入可用性就跟着抖。"""
        kinds = {f["kind"] for f in report.findings(
            _request("某主体", "undeclared_pred", "obj"), "subj_missing")}
        assert kinds == {"unregistered"}
        assert report.violations(_request("某主体", "undeclared_pred", "obj"), "subj_missing") == []


class TestFiveRules:
    def _setup(self, store, registry):
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "city", "kind": "concept", "disjointWith": ["person"]},
            {"termId": "married_to", "kind": "relation", "domain": ["person"],
             "rangeTerms": ["person"], "cardinality": 1},
        ])
        key = store.upsertSubject("default", "甲")
        registry.assignSubjectType(key, "person")
        return key

    def test_domainViolationNamesTheSubjectAndTerm(self, store, registry, report):
        key = self._setup(store, registry)
        registry.register("lives_in", "relation", domain=["city"], rangeTerms=["city"])

        violations = report.violations(_request("甲", "lives_in", "city"), key)

        assert [v["rule"] for v in violations] == ["domain"]
        assert violations[0]["subject_key"] == key
        assert "person" in violations[0]["message"] and "city" in violations[0]["message"]

    def test_rangeViolation(self, store, registry, report):
        key = self._setup(store, registry)
        registry.register("born_in", "relation", domain=["person"], rangeTerms=["city"])

        violations = report.violations(_request("甲", "born_in", "not_a_term"), key)

        assert violations == [], "客体不是已登记术语时值域免检，只记 unregistered"
        assert {f["rule"] for f in report.findings(_request("甲", "born_in", "not_a_term"), key)} \
            == {"range"}

    def test_cardinalityOneRejectsASecondActiveObject(self, store, registry, report):
        key = self._setup(store, registry)
        gate = productionAdmissionGate(store, toolVersion="unit")
        gate.admit(_request("甲", "married_to", "乙", qualifier={"env": "x"}),
                   allowPendingSegments=True)

        assert [v["rule"] for v in report.violations(
            _request("甲", "married_to", "丙", qualifier={"env": "x"}), key)] == ["cardinality"]
        assert report.violations(_request("甲", "married_to", "乙", qualifier={"env": "x"}), key) \
            == [], "重放同一说法不是基数违规"

    def test_disjointTypesOnOneSubjectAreRefused(self, store, registry, report):
        key = self._setup(store, registry)
        store.upsertFact("default", key, "is_a", "city", "甲也是个城市")

        violations = report.violations(_request("甲", "married_to", "乙", qualifier={"env": "x"}), key)

        assert "disjoint" in [v["rule"] for v in violations], "同一主体被断言成 person 与 city"

    def test_oneTypeIsNeverDisjointWithItself(self, store, registry, report):
        key = self._setup(store, registry)
        store.upsertFact("default", key, "is_a", "person", "甲是人")

        assert "disjoint" not in [v["rule"] for v in report.violations(
            _request("甲", "married_to", "乙", qualifier={"env": "x"}), key)]

    def test_parentConsistencyCatchesDanglingAncestor(self, store, registry, report):
        """悬空父类只能来自存量或手工改库——register 已经挡了新登记。"""
        key = self._setup(store, registry)
        registry.register("was_built_in", "relation", domain=["person"])
        registry.register("artifact", "concept")
        store._conn.execute(
            "UPDATE ontology_terms SET parent_term_id = 'gone' WHERE term_id = 'artifact'")
        store._conn.commit()
        store.upsertFact("default", key, "is_a", "artifact", "甲是个工件")

        violations = report.violations(_request("甲", "was_built_in", "车间"), key)

        assert "parentConsistency" in [v["rule"] for v in violations]


class TestGateIntegration:
    def test_gateRefusesDomainViolationBeforeWritingAnything(self, store, registry):
        registry.registerMany([
            {"termId": "person", "kind": "concept"},
            {"termId": "city", "kind": "concept"},
            {"termId": "lives_in", "kind": "relation", "domain": ["person"],
             "rangeTerms": ["city"]},
        ])
        key = store.upsertSubject("default", "某城市")
        registry.assignSubjectType(key, "city")
        gate = productionAdmissionGate(store, toolVersion="unit")

        with pytest.raises(ValueError, match="本体校验未过"):
            gate.admit(_request("某城市", "lives_in", "巴黎"), allowPendingSegments=True)

        assert store.factCount() == 0, "被拒的写入不得留下半条事实"

    def test_ontologySegmentIsNowHonestlyConnected(self, store):
        from neurova.knowledge.foundation.admission import SEGMENTS

        gate = productionAdmissionGate(store, toolVersion="unit")

        assert "ontology_adjudication" not in gate.pendingSegments()
        assert gate.pendingSegments() == [], "已实现的段接齐即无缺段"
        assert "indexing" in gate.plannedSegments(), "尚未建成的段如实另报"
        assert SEGMENTS.index("ontology_adjudication") < SEGMENTS.index("conflict_judgement"), \
            "段序是设计定的：本体裁决在冲突判定之前"
