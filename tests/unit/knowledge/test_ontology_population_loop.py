"""本体层人口闭环（Issue #73）：写侧产出三元组 / 类型断言 / 规则，两条检索分支才有数据。

要灭的病（审计 2026-09-21 §5.2，B-04 / B-09 / B-10）：

- 底座 92 条事实全 `narrative`、0 `triple` ⇒ priority 26（`temporal_facts.py`）与
  priority 27（`graph_walk.py`）按 `record_kind='triple'` 过滤，每轮恒定返回 0。
  形状与 B01「接了但不工作」相同，只是换了成因。
- `graph_bridge` 抽出的实体与边只落 JSON 属性图；被读的那张图
  （`knowledge_subjects` + `knowledge_facts`）永远收不到它们。
- `term_registry.register` 与 `rule_engine.registerRule` 的生产调用方为零，
  候选类型清单硬编在 prompt 里 ⇒ 新登记的术语对抽取不可见。

根因全在写侧，所以判据落在"抽取跑完以后底座里有什么、两条读面命中什么"，
而不是在读侧放宽过滤（那只是把症状挪走）。
"""

from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
from neurova.knowledge import graph_bridge
from neurova.knowledge.foundation.admission import AdmissionRequest, productionAdmissionGate
from neurova.knowledge.foundation.graph_walk import GraphFactWalker
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader
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
def graph(tmp_path):
    return KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))


_LLM_PAYLOAD = {
    "entities": [
        {"label": "检索链", "type": "concept"},
        {"label": "重排器", "type": "tool"},
    ],
    "relations": [
        {"source": "检索链", "target": "重排器", "type": "depends_on"},
    ],
}

_CHAIN_PAYLOAD = {
    "entities": [
        {"label": "检索链", "type": "concept"},
        {"label": "重排器", "type": "tool"},
        {"label": "ONNX 运行时", "type": "tool"},
    ],
    "relations": [
        {"source": "检索链", "target": "重排器", "type": "depends_on"},
        {"source": "重排器", "target": "ONNX 运行时", "type": "depends_on"},
    ],
}


def _llm(payload):
    text = json.dumps(payload, ensure_ascii=False)

    def _call(_prompt):
        return text

    return _call


def _extract(graph, registry, payload, *, item=None, factStore=None, agentId="default"):
    return graph_bridge.extract_knowledge_to_graph(
        item or {"knowledge_id": "k1", "title": "检索链", "content": "检索链依赖重排器。"},
        repo=None, llm_call=_llm(payload), graph_manager=graph,
        termRegistry=registry, factStore=factStore, agentId=agentId,
    )


def _triples(store):
    return {(f["canonical_label"] if "canonical_label" in f else "",
             f["predicate_term_id"], f["object_term"])
            for f in store.searchableFacts(agentId="default")}


class TestExtractionFeedsTheReadSurface:
    def test_extractedRelationBecomesATripleInTheFoundation(self, graph, registry, store):
        """抽取出的边必须进被读的那张图，而不只进 JSON 属性图。"""
        _extract(graph, registry, _LLM_PAYLOAD, factStore=store)

        facts = store.searchableFacts(agentId="default")

        assert facts, "抽取跑完底座仍是空的——写面与读面还是两张图"
        triples = {(f["canonical_label"], f["predicate_term_id"], f["object_term"])
                   for f in facts}
        assert ("检索链", "depends_on", "重排器") in triples
        assert {f["record_kind"] for f in facts} == {"triple"}, "这两条读面只收三元组"

    def test_extractedEntityTypeLandsAsAnIsAFactAndOnTheSubject(self, graph, registry, store):
        """主体类型不能只躺在 JSON 图里：`type_term_id` 与 `is_a` 事实都要有人写。"""
        _extract(graph, registry, _LLM_PAYLOAD, factStore=store)

        triples = {(f["canonical_label"], f["predicate_term_id"], f["object_term"])
                   for f in store.searchableFacts(agentId="default")}
        assert ("重排器", "is_a", "tool") in triples

        key = store.resolveSubjectKey("default", "重排器")
        assert registry.subjectType(key) == "tool", "抽出的类型要挂到主体上"

    def test_priority26BranchHitsWhatExtractionWrote(self, graph, registry, store):
        _extract(graph, registry, _LLM_PAYLOAD, factStore=store)

        hits = TemporalFactReader(store, agentId="default").forQuery("检索链依赖什么")

        assert ("depends_on", "重排器") in [(h["predicate"], h["object"]) for h in hits]

    def test_priority27BranchWalksWhatExtractionWrote(self, graph, registry, store):
        _extract(graph, registry, _CHAIN_PAYLOAD, factStore=store, item={
            "knowledge_id": "k2", "title": "检索链", "content": "检索链依赖重排器，重排器自己又依赖 ONNX 运行时。"})

        hops = GraphFactWalker(store, agentId="default").walkFromQuery(
            "检索链最终跑在什么上", maxHops=2)

        assert ("depends_on", "ONNX 运行时", 2) in [
            (h["predicate"], h["object"], h["hop"]) for h in hops]

    def test_activityIsAttributedToTheExtractionPipeline(self, graph, registry, store):
        """来路要自陈：新增事实的活动不能再一律记成咽喉兜底的 `admit`。"""
        _extract(graph, registry, _LLM_PAYLOAD, factStore=store)

        kinds = {row["activity_kind"] for row in store._conn.execute(
            "SELECT activity_kind FROM knowledge_activities").fetchall()}

        assert kinds == {"extract"}, "抽取是一条独立来路，不许混进直写兜底"

    def test_unregisteredRelationTypeStaysOutOfTheFoundation(self, graph, registry, store):
        """`custom` 是兜底标记、不是一种类型：拿它当谓词入库只会造出一批无义事实。"""
        _extract(graph, registry, {
            "entities": [{"label": "甲部", "type": "concept"}, {"label": "乙部", "type": "concept"}],
            "relations": [{"source": "甲部", "target": "乙部", "type": "definitely_not_a_relation"}],
        }, factStore=store)

        assert {f["predicate_term_id"] for f in store.searchableFacts(agentId="default")} == {"is_a"}


class TestOntologyIsPopulatedByDeclaration:
    def test_promptCandidatesComeFromTheRegistry(self, registry):
        registry.register("vessel", "concept", label="舰船")
        registry.register("docks_at", "relation", label="停靠于")

        prompt = graph_bridge.extractionPrompt(registry, title="T", content="C")

        assert "vessel" in prompt and "docks_at" in prompt, \
            "新登记的术语必须出现在抽取候选里——否则『加类型不改 .py』只对校验侧成立"

    def test_extractionStillHonoursANewTypeFromDataAlone(self, graph, registry, store):
        registry.register("vessel", "concept", label="舰船")

        _extract(graph, registry, {"entities": [{"label": "东风号", "type": "vessel"}],
                                   "relations": []}, factStore=store)

        assert ("东风号", "is_a", "vessel") in {
            (f["canonical_label"], f["predicate_term_id"], f["object_term"])
            for f in store.searchableFacts(agentId="default")}

    def test_isARangeIsJudgeableAndNamesTheKind(self, registry):
        """`is_a` 的客体是类型；把关系术语挂上去必须被拒——这是硬拒的第一条真实判据。"""
        report = OntologyValidationReport(registry)
        key = registry._store.upsertSubject("default", "甲")

        violations = report.violations(
            AdmissionRequest(agentId="default", subjectLabel="甲", predicateTermId="is_a",
                             objectTerm="part_of", content="甲 is_a part_of"), key)

        assert [v["rule"] for v in violations] == ["range"]
        assert "concept" in violations[0]["message"], "报错要点名值域是什么"

    def test_registeredConceptPassesTheKindSelector(self, registry):
        report = OntologyValidationReport(registry)
        key = registry._store.upsertSubject("default", "青海湖")

        assert report.violations(
            AdmissionRequest(agentId="default", subjectLabel="青海湖", predicateTermId="is_a",
                             objectTerm="location", content="青海湖 is_a location"), key) == []


class TestRulesHaveAProductionCaller:
    def test_gateAssemblySeedsRulesSoTheEngineIsNotIdle(self, store):
        gate = productionAdmissionGate(store, toolVersion="unit")

        assert gate is not None
        assert store._conn.execute("SELECT COUNT(*) FROM ontology_rules").fetchone()[0] > 0, \
            "规则表 0 行 ⇒ 前向链每轮空转（工单 021 的成品没有生产调用方）"

    def test_seededRuleActuallyFiresOnAdmittedChain(self, store):
        """种子规则不是摆设：写出一条 `is_a` 链，传递结论必须自己落库。"""
        gate = productionAdmissionGate(store, toolVersion="unit")
        for subject, obj in (("路由器", "设备"), ("设备", "硬件")):
            gate.admit(AdmissionRequest(
                agentId="default", subjectLabel=subject, predicateTermId="is_a",
                objectTerm=obj, content="%s is_a %s" % (subject, obj),
                recordKind="triple",
                assertions=[{"actorType": "pipeline", "actorId": "unit",
                             "mediumRef": "unit:test", "statementText": "%s is_a %s" % (subject, obj)}],
            ))

        derived = store._conn.execute(
            "SELECT 1 FROM knowledge_facts WHERE predicate_term_id = 'is_a'"
            " AND object_term = '硬件' AND qualifier_json LIKE '%derived_by%'").fetchone()

        assert derived is not None, "两条 is_a 事实该推出 路由器 is_a 硬件"

    def test_bareEngineStaysEmptySoTheSeedHasOneOwner(self, store):
        """种子只准在生产装配点落一次：裸造引擎仍应是空规则表。"""
        from neurova.knowledge.ontology.rule_engine import ForwardChainingEngine

        assert ForwardChainingEngine(store).rules() == []
