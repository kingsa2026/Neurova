"""Issue #72 未处置项 · 存量条目必须能被补抽**认得出来**（红绿灯 TDD）。

断链形状：`/knowledge-graph/backfill` 的待办判据是"条目没有 JSON 图节点 id"
（`graph_node_ids` 为空）。但抽取收口**之前**抽过的条目，`graph_node_ids` 早就有值
（旧实现只落投影、也照样回写），而权威侧（底座三元组）一条都没有。

于是最需要补抽的那批存量条目——"投影有、权威无"——恰好被待办判据全部跳过：
端点报表写着 `entries=0`（"没有待补的"），实际上是"待补的认不出来"。
这正是 Issue #72 §5 登记的那条"存量未回填"：它不是纯运维动作，先有一处判据要修。

修法在**产生非法状态的上游**：待办判据必须是"这条条目在权威侧没有事实"，
与有没有投影无关。投影是派生品（`projectionDrift` 已能给同一结论），不是补抽的依据。
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth
from neurova.api.endpoints import knowledge_graph_api as kg
from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.term_registry import OntologyTermRegistry
from neurova.knowledge.repository import KnowledgeRepository

_LLM = json.dumps(
    {
        "entities": [
            {"label": "RAG", "type": "concept"},
            {"label": "BM25", "type": "concept"},
        ],
        "relations": [{"source": "RAG", "target": "BM25", "type": "depends_on"}],
    },
    ensure_ascii=False,
)


class TestPendingPredicateAsksTheAuthority:
    def test_entry_withProjectionButNoAuthorityIsPending(self, tmp_path):
        from neurova.knowledge.graph_bridge import extractionPending

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        store = KnowledgeFactStore(str(tmp_path / "facts.db"))
        item = repo.create_knowledge("a1", title="T", content="RAG 依赖 BM25",
                                     owner_user_id="1")
        # 旧实现留下的形状：投影 id 有值，权威侧 0 条
        repo.update_knowledge("a1", item["knowledge_id"], {"graph_node_ids": ["n1", "n2"]})

        assert extractionPending(item, store, "a1") is True, \
            "投影有 id 不等于权威有事实——旧存量正是这个形状"
        store.close()

    def test_entry_withAuthorityIsNotPending(self, tmp_path):
        from neurova.knowledge.graph_bridge import extractionPending

        repo, store, registry, graph = _ledger(tmp_path)
        item = repo.create_knowledge("a1", title="T", content="RAG 依赖 BM25",
                                     owner_user_id="1")
        from neurova.knowledge.graph_bridge import extract_knowledge_to_graph

        extract_knowledge_to_graph(item, repo=repo, llm_call=lambda _p: _LLM,
                                   graph_manager=graph, termRegistry=registry,
                                   factStore=store, agentId="a1")

        assert extractionPending(item, store, "a1") is False, "补过了就不该再补一次"


class TestBackfillEndpointPicksThemUp:
    def test_endpointReportsAndHealsTheAuthorityLessEntry(self, tmp_path, monkeypatch):
        repo, store, registry, graph = _ledger(tmp_path)
        item = repo.create_knowledge("a1", title="T", content="RAG 依赖 BM25",
                                     owner_user_id="1")
        # 旧存量形状：投影有、权威无
        repo.update_knowledge("a1", item["knowledge_id"], {"graph_node_ids": ["n1", "n2"]})

        monkeypatch.setattr(kg, "_get_kg_manager", lambda _agent: graph)
        monkeypatch.setattr(
            "neurova.knowledge.repository.get_knowledge_repository", lambda: repo)
        monkeypatch.setattr(
            "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
            lambda *_a, **_k: store)
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge._default_llm_call",
            lambda *_a, **_k: (lambda _p: _LLM))

        app = FastAPI()
        app.dependency_overrides[auth.get_current_user_or_service] = lambda: {"user_id": "u1"}
        app.include_router(kg.router, prefix="/api/v1/knowledge-graph")
        client = TestClient(app)

        data = client.post("/api/v1/knowledge-graph/a1/knowledge-graph/backfill").json()["data"]

        assert data["entries"] == 1, "投影有 id、权威空白的存量条目必须进待补清单"
        assert data["extracted_nodes"] == 2
        assert store.searchableFacts(agentId="a1"), "补抽要真的落权威"
        assert [f["predicate_term_id"] for f in store.searchableFacts(agentId="a1")] \
            .count("depends_on") == 1


# ── 夹具 ──────────────────────────────────────────────────────────


def _ledger(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    registry = OntologyTermRegistry(store)
    graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))
    return repo, store, registry, graph
