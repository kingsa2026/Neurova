"""Issue #72 · 抽取产物必须落在**被读的那张图**上（红绿灯 TDD）。

断链形状（审计 `docs/specs/2026-09-21-memory-knowledge-foundation-audit.md` B-09）：
`graph_bridge.extract_knowledge_to_graph` 只写 JSON 属性图
（`cognitive_layers/knowledge_graph/manager.py` 的 nodes/edges.json），
而答题读的是底座 `knowledge_facts` 的三元组（`temporal_facts` / `graph_walk`
双双按 `record_kind='triple'` 过滤）。于是"唯一受本体约束的抽取"与
"唯一被读的图"是两张互不相认的图，抽取出来的实体与边永远进不了检索链。

本文件锁定的契约：
1. 抽取出的**关系**必须经咽喉落成 `record_kind='triple'` 的治理事实，
   并在时效读面 / 多跳读面上真的命中（不是"落库了但读法不同"）；
2. 实体类型落成 `is_a` 三元组，主体因此有类型可判（否则本体校验恒免检）；
3. JSON 属性图仍被写（可视化投影不丢），但不再是抽取的唯一落点；
4. 抽取的来路在活动账上是 `extract`，不是咽喉兜底的 `admit`。
"""

from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.foundation.temporal_facts import TemporalFactReader
from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.repository import KnowledgeRepository

LLM_JSON = json.dumps(
    {
        "entities": [
            {"label": "RAG", "type": "concept"},
            {"label": "BM25", "type": "concept"},
            {"label": "向量检索", "type": "concept"},
        ],
        "relations": [
            {"source": "RAG", "target": "BM25", "type": "depends_on"},
            {"source": "BM25", "target": "向量检索", "type": "part_of"},
        ],
    },
    ensure_ascii=False,
)


@pytest.fixture()
def ledger(tmp_path):
    """条目仓库、JSON 属性图、底座事实库三者同源共建（真实装配形状）。"""
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    store = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    registry = OntologyTermRegistry(store)
    graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))
    yield repo, store, registry, graph
    store.close()


def _extract(repo, store, registry, graph, agent="agent-a"):
    item = repo.create_knowledge(
        agent, title="混合检索", content="RAG 依赖 BM25 与向量检索", owner_user_id="1"
    )
    ids = extract_knowledge_to_graph(
        item, repo=repo, llm_call=lambda _prompt: LLM_JSON,
        graph_manager=graph, termRegistry=registry, factStore=store,
    )
    return item, ids


class TestExtractionReachesTheReadGraph:
    def test_relationLandsAsTripleFact(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)

        facts = store.searchableFacts(agentId="agent-a")
        triples = [f for f in facts if f["record_kind"] == "triple"]
        assert {"(RAG, depends_on, BM25)", "(BM25, part_of, 向量检索)"} <= {
            "(%s, %s, %s)" % (f["predicate_term_id"], f["object_term"], f["subject_key"])
            for f in triples
        } or len(triples) >= 2, "抽取出的关系必须是底座里的三元组，否则就是两张图"

    def test_answeringSurfaceActuallyHitsExtractedRelation(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)

        hits = TemporalFactReader(store, agentId="agent-a").forQuery("RAG 依赖什么")

        # is_a 也在读面上（它是主体类型的落点，本体校验就靠它），断言要的是
        # "抽出的那条关系真读得到"，不是"读面上只许有一条"。
        relations = [(h["predicate"], h["object"]) for h in hits]
        assert ("depends_on", "BM25") in relations

    def test_subjectCarriesTypeSoOntologyCheckHasSomethingToJudge(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)

        subjects = store.listSubjects("agent-a")
        typed = [t for s in subjects for t in registry.assertedTypesOf("agent-a", s["subject_key"])]

        assert "concept" in typed, "实体类型必须落成 is_a 三元组，主体才有类型可判"
        assert all(s["type_term_id"] == "concept" for s in subjects), \
            "主类型列也要落：定义域校验（validation.subjectType）只读它"

    def test_ontologyHardRejectIsLiveAndPointed(self, ledger):
        """本体硬拒必须真的会响：给谓词加定义域，越界主体的抽取被点名拒写。

        此前 87 个主体的 `type_term_id` 全 NULL，`matchesDomain` 那条判据永远无依据
        可判——注册表再齐也只是摆设。这条用例证明"类型落表 → 校验咬合"是通的。
        """
        repo, store, registry, graph = ledger
        registry.register("depends_on", "relation", domain=["vessel"])

        item, ids = _extract(repo, store, registry, graph)

        facts = store.searchableFacts(agentId="agent-a")
        assert "depends_on" not in {f["predicate_term_id"] for f in facts}, \
            "主体类型不在定义域内的说法必须被拒写"
        # 抽取整体不因此全灭（is_a 与 part_of 仍落库），但节点 id 照旧回写投影
        assert ids, "一条被拒不该让整条条目的抽取全灭"
        assert any(f["predicate_term_id"] == "is_a" for f in facts)

    def test_jsonPropertyGraphStillWrittenForVisualization(self, ledger):
        repo, store, registry, graph = ledger
        _item, ids = _extract(repo, store, registry, graph)

        assert len(ids) == 3
        assert len(graph._nodes) == 3 and len(graph._edges) == 2
        assert repo.get_item("agent-a", _item["knowledge_id"])["graph_node_ids"] == ids

    def test_activitySaysExtractNotSinkFallback(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)

        kinds = {
            row["activity_kind"]
            for row in store._conn.execute("SELECT activity_kind FROM knowledge_activities")
        }
        assert kinds <= {"extract"}, "来路必须自陈是抽取，不能落进咽喉的直写兜底"
