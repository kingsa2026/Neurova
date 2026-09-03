"""
知识条目 → 图谱节点自动抽取（批次 3 / B2）

契约（extract_knowledge_to_graph）：
- LLM 抽实体/关系（JSON），类型对齐 NodeType/RelationType 枚举，越界落 custom
- 按 label+type 去重（重复抽取复用既有节点）
- node_ids 回写 KnowledgeItem.graph_node_ids（经 repository 白名单字段）
- LLM 异常/畸形输出/未配置 → 返回 []，不抛出、不写回
"""
import json

import pytest

from neurova.knowledge.graph_bridge import extract_knowledge_to_graph
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


def _item(repo):
    return repo.create_knowledge(
        "agent-a", title="混合检索", content="RAG 依赖 BM25 与向量检索", owner_user_id="1"
    )


class TestExtractToGraph:
    def test_creates_nodes_edges_and_writes_back(self, repo, graph):
        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=fake_llm, graph_manager=graph)

        assert len(ids) == 3
        labels = {n.label for n in graph._nodes.values()}
        assert {"RAG", "BM25", "向量检索"} <= labels
        assert all(nid in graph._nodes for nid in ids)

        updated = repo.get_item("agent-a", item["knowledge_id"])
        assert updated["graph_node_ids"] == ids

        rels = {e.relation_type.value for e in graph._edges.values()}
        assert "depends_on" in rels

    def test_invalid_types_fall_back_to_custom(self, repo, graph):
        item = _item(repo)
        extract_knowledge_to_graph(item, repo=repo, llm_call=fake_llm, graph_manager=graph)

        types = {n.node_type.value for n in graph._nodes.values()}
        assert "custom" in types  # "technique" 非法
        rels = {e.relation_type.value for e in graph._edges.values()}
        assert "custom" in rels  # "uses_x" 非法

    def test_dedupe_by_label_and_type(self, repo, graph):
        item = _item(repo)
        ids1 = extract_knowledge_to_graph(item, repo=repo, llm_call=fake_llm, graph_manager=graph)
        ids2 = extract_knowledge_to_graph(item, repo=repo, llm_call=fake_llm, graph_manager=graph)

        assert ids1 == ids2
        assert len(graph._nodes) == 3

    def test_llm_failure_returns_empty(self, repo, graph):
        def boom(prompt):
            raise RuntimeError("llm down")

        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=boom, graph_manager=graph)

        assert ids == []
        assert graph._nodes == {}
        assert repo.get_item("agent-a", item["knowledge_id"])["graph_node_ids"] == []

    def test_no_llm_call_skips_extraction(self, repo, graph):
        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=None, graph_manager=graph)
        assert ids == []
        assert graph._nodes == {}

    def test_malformed_llm_json_tolerated(self, repo, graph):
        def bad_llm(prompt):
            return "not json {"

        item = _item(repo)
        ids = extract_knowledge_to_graph(item, repo=repo, llm_call=bad_llm, graph_manager=graph)
        assert ids == []
        assert graph._nodes == {}
