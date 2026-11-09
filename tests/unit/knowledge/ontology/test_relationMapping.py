# -*- coding: utf-8 -*-
"""B8 关系映射层（升级计划 §5 B8）：层级/逆/对称/传递/函数/别名/候选/外部 IRI。

十组判据全部走真装配（productionAdmissionGate / 真注册表 / 真引擎），
不许造裸门绕过咽喉；种子收口要求新旧结论集逐条一致（A/B 对拍）。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.foundation.admission import (
    AdmissionRequest,
    productionAdmissionGate,
)
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine
from neurova.knowledge.ontology.term_registry import (
    IS_A_PREDICATE,
    OntologyTermRegistry,
)


@pytest.fixture
def store(tmp_path):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture
def engine(store):
    return ForwardChainingEngine(store, gateFactory=lambda st: productionAdmissionGate(
        st, toolVersion="b8"))


def _gate(store):
    return productionAdmissionGate(store, toolVersion="unit")


def _admit(store, subject, predicate, obj):
    content = "%s %s %s" % (subject, predicate, obj)
    return _gate(store).admit(AdmissionRequest(
        agentId="default", subjectLabel=subject, predicateTermId=predicate, objectTerm=obj,
        content=content,
        assertions=[{"actorType": "pipeline", "actorId": "unit", "mediumRef": "unit:test",
                     "statementText": content}],
    ))


def _facts(store, predicate, obj=None):
    rows = [f for f in store.searchableFacts(agentId="default")
            if f["predicate_term_id"] == predicate]
    if obj is not None:
        rows = [f for f in rows if f["object_term"] == obj]
    return rows


def _relation(store, termId, **kw):
    registry = OntologyTermRegistry(store)
    return registry.register(termId, "relation", **kw)


class TestRelationHierarchy:
    def test_relationParentAllowedAndSubpropertyDerived(self, store, engine):
        """① `part_of ⊑ related_to` 登记成功，自动生成 subproperty 搬移规则。"""
        registry = OntologyTermRegistry(store)
        registry.register("related_to", "relation")
        registry.register("part_of", "relation", parentTermId="related_to")

        engine.ensureAutoRules()

        rule = engine.rule("auto_subproperty:part_of")
        assert rule is not None, "关系父属性必须生成搬移规则"
        assert rule["head_predicate"] == "related_to"

        _admit(store, "房间A", "part_of", "楼B")
        derived = _facts(store, "related_to")
        assert len(derived) == 1, "X part_of Y ⇒ X related_to Y 自动成立"

    def test_relationParentCycleRejected(self, store):
        """① 成环拒：A ⊑ B、B ⊑ A 必须在登记处报错。"""
        registry = OntologyTermRegistry(store)
        registry.register("rel_a", "relation")
        registry.register("rel_b", "relation", parentTermId="rel_a")
        with pytest.raises(ValueError, match="环"):
            registry.register("rel_a", "relation", parentTermId="rel_b")

    def test_parentKindMustMatch(self, store):
        """① 父子 kind 必须一致：relation 不能挂 concept 父类。"""
        registry = OntologyTermRegistry(store)
        registry.register("device", "concept")
        with pytest.raises(ValueError, match="kind"):
            registry.register("part_of", "relation", parentTermId="device")


class TestInverseRelation:
    def test_inverseFillsBothSidesAndDerivesSwapped(self, store, engine):
        """② `depends_on inverse_of used_by`：双向补齐，方向不照抄。"""
        registry = OntologyTermRegistry(store)
        registry.register("used_by", "relation")
        registry.register("depends_on", "relation", inverseOf="used_by")

        assert registry.term("depends_on")["inverse_of"] == "used_by"
        assert registry.term("used_by")["inverse_of"] == "depends_on", \
            "登记时双向补齐，单边态不存在"

        engine.ensureAutoRules()
        _admit(store, "服务A", "depends_on", "库B")

        assert len(_facts(store, "used_by")) == 1, "X depends_on Y ⇒ Y used_by X"

    def test_inverseTargetMustBeRegisteredRelation(self, store):
        """② 逆关系目标不存在/非 relation，登记处拒绝。"""
        registry = OntologyTermRegistry(store)
        registry.register("ghost_target", "concept")
        with pytest.raises(ValueError, match="逆关系"):
            registry.register("depends_on", "relation", inverseOf="ghost_target")

    def test_inverseOfSelfWithoutSymmetricRejected(self, store):
        """② `inverse_of` 指自身但未声明 symmetric：拒绝。"""
        registry = OntologyTermRegistry(store)
        registry.register("same_as", "relation")
        with pytest.raises(ValueError, match="symmetric"):
            registry.register("same_as", "relation", inverseOf="same_as")


class TestSymmetricRelation:
    def test_symmetricMaterializesBothDirections(self, store, engine):
        """③ `similar_to` 对称：双向物化。"""
        registry = OntologyTermRegistry(store)
        registry.register("similar_to", "relation", symmetric=True)

        engine.ensureAutoRules()
        _admit(store, "甲", "similar_to", "乙")

        assert len(_facts(store, "similar_to")) == 2, "对称关系双向落库"


class TestTransitiveRelation:
    def test_transitiveClosureDerived(self, store, engine):
        """④ `part_of` 传递：闭包自动推出。"""
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", transitive=True)

        engine.ensureAutoRules()
        _admit(store, "房间", "part_of", "楼层")
        _admit(store, "楼层", "part_of", "大楼")

        assert len(_facts(store, "part_of")) == 3, "房间→大楼 由传递闭包推出"

    def test_disablingTransitiveRetractsDerivationsPrecisely(self, store, engine):
        """④ 撤声明：auto 规则退场，其推导经账本精确消失，原始事实不陪葬。"""
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", transitive=True)
        engine.ensureAutoRules()
        _admit(store, "房间", "part_of", "楼层")
        _admit(store, "楼层", "part_of", "大楼")
        assert len(_facts(store, "part_of")) == 3
        originalCount = 2

        registry.register("part_of", "relation", transitive=False)
        engine.ensureAutoRules()

        assert len(_facts(store, "part_of")) == originalCount, \
            "撤声明后推导事实经账本精确消失"
        assert engine.rule("auto_transitive:part_of") is None or \
            not engine.rule("auto_transitive:part_of").get("enabled"), \
            "auto 规则随声明退场"


class TestFunctionalProperty:
    def test_cardinalityOneConflictRejectedWithoutNewColumn(self, store):
        """⑤ 函数属性 = cardinality=1：冲突沿用既有基数判定，不加 functional 列。"""
        registry = OntologyTermRegistry(store)
        registry.register("has_status", "relation", domain=["Order"], cardinality=1)
        columns = {r[1] for r in store._conn.execute(
            "PRAGMA table_info(ontology_terms)").fetchall()}
        assert "functional" not in columns, "函数属性不新增列"

        _admit(store, "订单D01", "has_status", "open")
        with pytest.raises(ValueError, match="本体校验未过"):
            _admit(store, "订单D01", "has_status", "closed")


class TestRelationAlias:
    def test_aliasResolvesToTerm(self, store):
        """⑥ 别名"属于"归一为 part_of。"""
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", aliases=["属于", "隶属于"])

        assert registry.resolveRelationAlias("属于") == "part_of"
        assert registry.resolveRelationAlias("隶属于") == "part_of"
        assert registry.resolveRelationAlias("part_of") == "part_of"

    def test_aliasConflictRejectedNotOverwritten(self, store):
        """⑥ 别名按租户唯一：同一 surface 归另一术语必须拒绝，不覆盖。"""
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", aliases=["属于"])
        with pytest.raises(ValueError, match="别名"):
            registry.register("contains", "relation", aliases=["属于"])

    def test_aliasNormalizedSurfaceMatches(self, store):
        """⑥ 规范化 surface（大小写/空白/标点）也能命中。"""
        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", aliases=["Part Of"])

        assert registry.resolveRelationAlias("  part  of! ") == "part_of"


class TestUnknownRelationCandidate:
    def test_unknownRelationGoesToCandidateOnly(self, store):
        """⑦ 未登记关系只进候选表：事实与投影均无。"""
        from neurova.knowledge.graph_bridge import admitExtractedFacts
        from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

        registry = OntologyTermRegistry(store)
        registry.register("person", "concept")
        registry.register("company", "concept")
        data = {"entities": [{"label": "张三", "type": "person"},
                             {"label": "甲公司", "type": "company"}],
                "relations": [{"source": "张三", "type": "telepathizes",
                               "target": "甲公司"}]}
        item = {"agent_id": "default", "tenant_id": "default",
                "knowledge_id": "k1", "title": "t", "content": "c"}

        admitExtractedFacts(data, item, store, termRegistry=registry)

        assert _facts(store, "telepathizes") == [], "未登记关系不许落事实"
        pending = RelationCandidateStore(store).list(tenantId="default", status="pending")
        assert len(pending) == 1 and pending[0]["surface"] == "telepathizes", \
            "未知关系落候选表等人工审批"

    def test_approvingCandidatePromotesTerm(self, store):
        """⑦ 批准候选 → 术语登记 + promoted_term_id 回填，后续抽取可命中。"""
        from neurova.knowledge.graph_bridge import admitExtractedFacts
        from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

        registry = OntologyTermRegistry(store)
        registry.register("person", "concept")
        registry.register("company", "concept")
        data = {"entities": [{"label": "张三", "type": "person"},
                             {"label": "甲公司", "type": "company"}],
                "relations": [{"source": "张三", "type": "telepathizes",
                               "target": "甲公司"}]}
        item = {"agent_id": "default", "tenant_id": "default",
                "knowledge_id": "k1", "title": "t", "content": "c"}
        admitExtractedFacts(data, item, store, termRegistry=registry)

        candidates = RelationCandidateStore(store)
        pending = candidates.list(tenantId="default", status="pending")
        promoted = candidates.approve(pending[0]["candidate_id"], tenantId="default",
                                      termRegistry=registry)

        assert promoted["promoted_term_id"] == "telepathizes"
        assert registry.term("telepathizes") is not None, "批准即登记术语"
        assert registry.resolveRelationAlias("telepathizes") == "telepathizes"

    def test_rejectedCandidateKeptForAudit(self, store):
        """⑦ 拒绝保留审计行，不删除。"""
        from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

        candidates = RelationCandidateStore(store)
        candidates.record(tenantId="default", surface="念力传送",
                          sourceEntryId="k9", sourceText="张三念力传送行李", confidence=0.4)
        pending = candidates.list(tenantId="default", status="pending")

        candidates.reject(pending[0]["candidate_id"], tenantId="default")

        rejected = candidates.list(tenantId="default", status="rejected")
        assert len(rejected) == 1 and rejected[0]["surface"] == "念力传送"


class TestExternalIriExport:
    def test_exportUsesExternalIriAndStandardSlots(self, store):
        """⑧ 导出：rdfs:subPropertyOf / owl:inverseOf / 外部 IRI，逐字节确定。"""
        from neurova.knowledge.ontology.turtle import serializeAll

        registry = OntologyTermRegistry(store)
        registry.register("related_to", "relation",
                          externalIris=[{"kind": "skos_exactMatch", "iri": "http://example.org/vocab#relatedTo"}])
        registry.register("part_of", "relation", parentTermId="related_to",
                          externalIris=[{"kind": "skos_exactMatch", "iri": "http://example.org/vocab#partOf"}])
        registry.register("depends_on", "relation", inverseOf="used_by")
        registry.register("used_by", "relation")

        first = serializeAll(store, tenantId="default")
        second = serializeAll(store, tenantId="default")

        assert first == second, "导出逐字节确定"
        assert "rdfs:subPropertyOf" in first
        assert "owl:inverseOf" in first
        assert "http://example.org/vocab#partOf" in first, "有外部 IRI 用外部 IRI"

    def test_isAFactsExportAsRdfType(self, store):
        """⑧ `is_a` 事实导出为实例类型 rdf:type，概念父类导出 rdfs:subClassOf。"""
        from neurova.knowledge.ontology.turtle import serializeAll

        registry = OntologyTermRegistry(store)
        registry.register("Order", "concept", parentTermId=None)
        registry.register("HighRiskOrder", "concept", parentTermId="Order")
        _admit(store, "订单D01", IS_A_PREDICATE, "HighRiskOrder")

        doc = serializeAll(store, tenantId="default")

        assert "rdf:type" in doc, "is_a 事实导出为实例类型"
        assert "rdfs:subClassOf" in doc, "概念父类导出 subClassOf"


class TestTenantIsolationAndCompat:
    def test_candidatesAndFeaturesAreTenantScoped(self, store):
        """⑨ 候选与关系特征按租户隔离。"""
        from neurova.knowledge.ontology.relation_candidates import RelationCandidateStore

        registry = OntologyTermRegistry(store)
        registry.register("part_of", "relation", aliases=["属于"], tenantId="default")
        registry.register("part_of", "relation", transitive=True, tenantId="tenant-b")

        assert registry.resolveRelationAlias("属于", tenantId="tenant-b") is None, \
            "别名按租户隔离"
        assert registry.term("part_of", tenantId="default")["transitive"] == 0, \
            "特征按租户隔离：default 租户不带 tenant-b 的传递声明"

        candidates = RelationCandidateStore(store)
        candidates.record(tenantId="default", surface="x1", sourceEntryId="k1",
                          sourceText="t", confidence=0.5)
        assert candidates.list(tenantId="tenant-b", status="pending") == []


class TestSeedRuleAbsorption:
    def test_isATransitiveGeneratedFromTermFeature(self, store, engine):
        """⑩ `is_a_transitive` 由 is_a.transitive 生成：同 id 单行，结论与旧种子一致。"""
        registry = OntologyTermRegistry(store)
        assert registry.term(IS_A_PREDICATE)["transitive"] == 1, \
            "is_a 种子术语自带传递声明"

        engine.ensureAutoRules()

        rules = [r for r in engine.rules() if r["rule_id"] == "is_a_transitive"]
        assert len(rules) == 1, "同一蕴含只允许一条规则（教义第 6 条）"

        _admit(store, "甲类", IS_A_PREDICATE, "乙类")
        _admit(store, "乙类", IS_A_PREDICATE, "丙类")
        assert len(_facts(store, IS_A_PREDICATE)) == 3, "结论集与旧手工种子逐条一致"

    def test_otherSeedRelationsDefaultAllOff(self, store):
        """⑩ 其余种子关系特征默认全关：领域假设不写进默认数据。"""
        registry = OntologyTermRegistry(store)
        for term in registry.terms("relation"):
            if term["term_id"] == IS_A_PREDICATE:
                continue
            assert not term["inverse_of"] and not term["symmetric"] \
                and not term["transitive"], \
                "%s 的特征默认全关" % term["term_id"]
