"""Issue #72 未处置项收口 · JSON 属性图必须能由底座权威**派生重建**（红绿灯 TDD）。

断链形状：抽取收口后权威侧（`knowledge_subjects` + `knowledge_facts` 的 triple）
与 JSON 属性图（`agent_workspaces/<agent>/knowledge_graph/*.json`）仍是两套数据。
抽取那一刻两边同源，但只要权威侧再变（补抽、裁决取代、推导结论落库、存量回填），
投影不会跟着动，也没有任何一条路径能把投影拉回与权威一致——那就是"投影"名下的
第二份真相：可视化读它，检索读权威，两边各说各话且无人报出分叉。

本文件锁定三条契约：

1. 分叉**可读**：给定权威与投影，能算出"权威里有、投影里没有"的缺口并点名。
2. 分叉**可修**：重建走权威派生，重建后投影与权威逐条对齐（投影不再是独立写入面）。
3. 重建**不越域**：只重建这一个 agent 的投影，别的域一个节点都不动。
"""

from __future__ import annotations

import json

import pytest

from neurova.cognitive_layers.knowledge_graph.manager import KnowledgeGraphManager
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.graph_bridge import (
    extract_knowledge_to_graph,
    projectionDrift,
    rebuildProjectionFromAuthority,
)
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


@pytest.fixture()
def ledger(tmp_path):
    repo = KnowledgeRepository(str(tmp_path / "kb"))
    store = KnowledgeFactStore(str(tmp_path / "facts.db"))
    registry = OntologyTermRegistry(store)
    graph = KnowledgeGraphManager(storage_dir=str(tmp_path / "kg"))
    yield repo, store, registry, graph
    store.close()


def _extract(repo, store, registry, graph, agent="agent-a"):
    item = repo.create_knowledge(agent, title="混合检索", content="RAG 依赖 BM25",
                                 owner_user_id="1")
    extract_knowledge_to_graph(item, repo=repo, llm_call=lambda _p: _LLM,
                               graph_manager=graph, termRegistry=registry,
                               factStore=store, agentId=agent)
    return item


class TestDriftIsReadable:
    def test_freshlyExtractedProjectionHasNoDrift(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)

        drift = projectionDrift("agent-a", graph, store)

        assert drift["authority_relations"] == 1, "权威侧一条关系"
        assert drift["missing_relations"] == [], "刚抽完两边同源，不该有缺口"

    def test_authorityGainedARelationTheProjectionNeverSaw(self, ledger):
        """权威侧补了一条投影没见过的关系 ⇒ 必须点名，不许静默。"""
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)
        # 模拟"权威侧再变"：直接经咽喉补一条，不走抽取（补抽/推导结论落到这里）
        from neurova.knowledge.foundation.admission import (
            AdmissionRequest, productionAdmissionGate,
        )

        productionAdmissionGate(store, toolVersion="unit").admit(AdmissionRequest(
            agentId="agent-a", subjectLabel="BM25", predicateTermId="depends_on",
            objectTerm="RAG", content="BM25 depends_on RAG",
            assertions=[{"actorType": "pipeline", "actorId": "unit",
                         "mediumRef": "unit:test",
                         "statementText": "BM25 depends_on RAG"}],
            activityKind="extract",
        ))

        drift = projectionDrift("agent-a", graph, store)

        assert drift["authority_relations"] == 2
        assert drift["missing_relations"] == [{"source": "BM25", "relation": "depends_on",
                                               "target": "RAG"}]

    def test_projectionOnlyNodesAreAlsoReported(self, ledger):
        """反向缺口同样要点名：投影里有、权威里没有的，是可视化在展示无据可依的边。"""
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)
        graph.clear()
        node_a = graph.add_node(label="孤岛甲", node_type="concept")
        node_b = graph.add_node(label="孤岛乙", node_type="concept")
        graph.add_edge(source_id=node_a.node_id, target_id=node_b.node_id,
                       relation_type="related_to")

        drift = projectionDrift("agent-a", graph, store)

        assert drift["orphan_relations"] == [{"source": "孤岛甲", "relation": "related_to",
                                              "target": "孤岛乙"}]


class TestRebuildDerivesFromAuthority:
    def test_rebuildClosesTheGap(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)
        graph.clear()

        outcome = rebuildProjectionFromAuthority("agent-a", graph, store, registry)

        assert outcome["nodes"] == 2 and outcome["edges"] == 1
        assert projectionDrift("agent-a", graph, store)["missing_relations"] == []
        assert projectionDrift("agent-a", graph, store)["orphan_relations"] == []

    def test_rebuiltNodeCarriesTheAuthorityType(self, ledger):
        """节点类型取自权威主体的类型列——投影的类型不是自己猜的。"""
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)
        graph.clear()

        rebuildProjectionFromAuthority("agent-a", graph, store, registry)

        node = [n for n in graph._nodes.values() if n.label == "RAG"][0]
        assert node.nodeTypeValue == "concept"

    def test_rebuildIsIdempotent(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)

        rebuildProjectionFromAuthority("agent-a", graph, store, registry)
        outcome = rebuildProjectionFromAuthority("agent-a", graph, store, registry)

        assert len(graph._nodes) == 2, "重建是幂等的：不许每跑一次就多一批节点"
        assert outcome["nodes"] == 2

    def test_rebuildDoesNotTouchOtherAgents(self, ledger):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph, agent="agent-a")
        _extract(repo, store, registry, graph, agent="agent-b")

        before = sum(1 for n in graph._nodes.values() if n.label in ("RAG", "BM25"))
        rebuildProjectionFromAuthority("agent-a", graph, store, registry)
        after = sum(1 for n in graph._nodes.values() if n.label in ("RAG", "BM25"))

        assert before == after == 2, "同标签跨域同名，重建只准动本域的节点/边"
        assert projectionDrift("agent-b", graph, store)["missing_relations"] == [], \
            "别的域的投影本来就与它的权威一致，重建不该把它拆了"


class TestEndpointsAreWired:
    """两条端点是投影一致性的**生产消费点**：只加函数不接线就是断点。"""

    def _client(self, monkeypatch, tmp_path, repo, store, registry, graph):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api import auth
        from neurova.api.endpoints import knowledge_graph_api as kg

        monkeypatch.setattr(kg, "_get_kg_manager", lambda _agent: graph)
        monkeypatch.setattr(
            "neurova.knowledge.foundation.knowledge_facts.get_knowledge_fact_store",
            lambda *_a, **_k: store,
        )
        app = FastAPI()
        app.dependency_overrides[auth.get_current_user_or_service] = lambda: {"user_id": "u1"}
        app.include_router(kg.router, prefix="/api/v1/knowledge-graph")
        return TestClient(app)

    def test_driftEndpointReportsAndDoesNotFix(self, ledger, monkeypatch, tmp_path):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)
        graph.clear()
        client = self._client(monkeypatch, tmp_path, repo, store, registry, graph)

        first = client.get("/api/v1/knowledge-graph/agent-a/knowledge-graph/authority-drift").json()
        second = client.get("/api/v1/knowledge-graph/agent-a/knowledge-graph/authority-drift").json()

        assert first["data"]["missing_relations"], "清了投影就该报出缺口"
        assert first["data"] == second["data"], "读数端点不许顺手把分叉修掉（两次读数必须一样）"
        assert len(graph._nodes) == 0

    def test_rebuildEndpointClosesTheGap(self, ledger, monkeypatch, tmp_path):
        repo, store, registry, graph = ledger
        _extract(repo, store, registry, graph)
        graph.clear()
        client = self._client(monkeypatch, tmp_path, repo, store, registry, graph)

        rebuilt = client.post(
            "/api/v1/knowledge-graph/agent-a/knowledge-graph/projection/rebuild").json()
        after = client.get(
            "/api/v1/knowledge-graph/agent-a/knowledge-graph/authority-drift").json()

        assert rebuilt["data"]["nodes"] == 2 and rebuilt["data"]["edges"] == 1
        assert after["data"]["missing_relations"] == []
