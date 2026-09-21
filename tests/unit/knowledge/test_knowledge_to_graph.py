"""
知识条目 → 图谱节点自动抽取（批次 3 / B2）

契约（extract_knowledge_to_graph）：
- LLM 抽实体/关系（JSON），合法类型来自 `ontology_terms`（工单 018），越界落 custom
- 节点复用走 006 身份消解段（重复抽取复用既有节点，类型不参与身份判定）
- node_ids 回写 KnowledgeItem.graph_node_ids（经 repository 白名单字段）
- **抽取产物同时经咽喉落到底座三元组**（Issue #72 / B-09）：JSON 属性图只是投影，
  被检索链读的是底座；本文件因此一律注入隔离底座库，且断言权威侧真有行
- LLM 异常/畸形输出/未配置 → 返回 []，不抛出、不写回
"""
import json

import pytest

from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.repository import KnowledgeRepository
from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager

LLM_JSON = json.dumps(
    {
        "entities": [
            {"label": "RAG", "type": "concept"},
            {"label": "BM25", "type": "concept"},
            {"label": "向量检索", "type": "technique"},
        ],
        "relations": [
            {"source": "RAG", "target": "BM25", "type": "depends_on"},
            {"source": "RAG", "target": "向量检索", "type": "uses_x"},
        ],
    },
    ensure_ascii=False,
)


def fake_llm(prompt):
    return LLM_JSON


@pytest.fixture()
def repo(tmp_path):
    return KnowledgeRepository(str(tmp_path / "kb"))


@pytest.fixture()
def graph(tmp_path):
    return KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))


@pytest.fixture()
def store(tmp_path):
    """权威落点自带隔离库——围栏不让碰生产底座，注入就是本文件的纪律。"""
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    yield s
    s.close()


@pytest.fixture()
def registry(store):
    """合法类型的权威在注册表里。"""
    return OntologyTermRegistry(store)


def _extract(item, repo, graph, registry, store, llm=None):
    return extract_knowledge_to_graph(
        item, repo=repo, llm_call=llm if llm is not None else fake_llm,
        graph_manager=graph, termRegistry=registry, factStore=store,
        agentId="agent-a")


def _item(repo):
    return repo.create_knowledge(
        "agent-a", title="混合检索", content="RAG 依赖 BM25 与向量检索", owner_user_id="1"
    )


class TestExtractToGraph:
    def test_creates_nodes_edges_and_writes_back(self, repo, graph, registry, store):
        item = _item(repo)
        ids = _extract(item, repo, graph, registry, store)

        assert len(ids) == 3
        labels = {n.label for n in graph._nodes.values()}
        assert {"RAG", "BM25", "向量检索"} <= labels
        assert all(nid in graph._nodes for nid in ids)

        updated = repo.get_item("agent-a", item["knowledge_id"])
        assert updated["graph_node_ids"] == ids

        rels = {e.relationTypeValue for e in graph._edges.values()}
        assert "depends_on" in rels

        # 抽取的产物必须同时是底座里的三元组（被检索链读的那张图），
        # 否则"可视化有、答题没有"就是 Issue #72 的原始病灶。
        # 谓词用"注册表判过之后"的类型：depends_on 登记过就用它；uses_x 未登记落
        # custom——`custom` 是兜底标记不是一种类型（术语表里没有它），所以投影侧
        # 保留它（可视化要看得出"这个词没登记"），底座侧**不写**它：拿它当谓词只会
        # 造出一批读不出来源的无义事实。
        predicates = {f["predicate_term_id"] for f in store.searchableFacts(agentId="agent-a")}
        assert {"depends_on", "is_a"} <= predicates
        assert "custom" not in predicates, "custom 是兜底标记，不许当谓词入库"

    def test_invalid_types_fall_back_to_custom(self, repo, graph, registry, store):
        item = _item(repo)
        _extract(item, repo, graph, registry, store)

        types = {n.nodeTypeValue for n in graph._nodes.values()}
        assert "custom" in types  # "technique" 没在注册表里登记
        rels = {e.relationTypeValue for e in graph._edges.values()}
        assert "custom" in rels  # "uses_x" 同上

    def test_repeated_extraction_reuses_nodes_by_identity(self, repo, graph, registry, store):
        """复用以身份消解段为准：同一实体不因类型词不同就开第二个节点。"""
        item = _item(repo)
        ids1 = _extract(item, repo, graph, registry, store)
        ids2 = _extract(item, repo, graph, registry, store)

        assert ids1 == ids2
        assert len(graph._nodes) == 3

    def test_llm_failure_returns_empty(self, repo, graph, store):
        def boom(prompt):
            raise RuntimeError("llm down")

        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=boom,
                                         graph_manager=graph, factStore=store)

        assert ids == []
        assert graph._nodes == {}
        assert repo.get_item("agent-a", item["knowledge_id"])["graph_node_ids"] == []

    def test_no_llm_call_skips_extraction(self, repo, graph, store):
        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=None,
                                         graph_manager=graph, factStore=store)
        assert ids == []
        assert graph._nodes == {}

    def test_malformed_llm_json_tolerated(self, repo, graph, store):
        def bad_llm(prompt):
            return "not json {"

        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=bad_llm,
                                         graph_manager=graph, factStore=store)
        assert ids == []
        assert graph._nodes == {}
