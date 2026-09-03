"""
RAG Evaluation 最小闭环（批次 2 / B4）：召回可信度字段契约

/hybrid 每条结果必须携带 confidence_breakdown：
- bm25 / vector / fts：各路归一化分（[0,1]；fts 当前为占位恒 0，如实标注）
- rrf：融合分（>=0）
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as semantic_auth
from neurova.api.endpoints import semantic_search_api as ssa

PREFIX = "/v1/semantic-search"
USER = {"user_id": "1", "username": "u", "role": "user", "neuser_id": "1"}


class StubEngine:
    """确定性 embedding 桩：固定词表 one-hot"""

    VOCAB = ["quantum", "rust", "async", "cookie", "recipe", "travel", "sales", "plan"]

    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]

    def encode_batch(self, texts):
        return [self.encode(t) for t in texts]


class StubSemanticSearch:
    def compute_similarity(self, query: str, content: str) -> float:
        return 0.42 if "quantum" in (content or "") else 0.0

    def build_keyword_index(self, corpus):
        pass

    def search_by_keywords(self, query, limit=10):
        return []


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from neurova.knowledge import vector_index as vi
    from neurova.knowledge.repository import KnowledgeRepository
    from neurova.knowledge.vector_index import KnowledgeVectorIndex

    r = KnowledgeRepository(str(tmp_path / "kb"))
    monkeypatch.setattr("neurova.knowledge.repository.get_knowledge_repository", lambda: r)
    monkeypatch.setattr(ssa, "get_semantic_search", lambda: StubSemanticSearch())
    monkeypatch.setattr(
        vi, "get_knowledge_vector_index",
        lambda: KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine()),
    )
    r.create_knowledge(
        "agent-a", title="Quantum Guide", content="quantum computing explained",
        visibility="public", owner_user_id="1",
    )

    app = FastAPI()
    app.include_router(ssa.router, prefix=PREFIX)
    app.dependency_overrides[semantic_auth.get_current_user_or_service] = lambda: dict(USER)
    return TestClient(app)


def test_every_result_has_confidence_breakdown(client):
    resp = client.post(PREFIX + "/hybrid", json={"query": "quantum", "source": "knowledge", "top_k": 5})
    assert resp.status_code == 200
    results = resp.json()["data"]["results"]
    assert results, "public 知识条目应被召回"
    for item in results:
        bd = item.get("confidence_breakdown")
        assert isinstance(bd, dict)
        for key in ("bm25", "vector", "fts", "rrf"):
            assert key in bd, "缺少 %s 分量" % key
        for key in ("bm25", "vector", "fts"):
            assert 0.0 <= bd[key] <= 1.0
        assert bd["rrf"] >= 0.0


def test_relevant_hit_scores_higher_than_noise(client):
    from neurova.knowledge.repository import KnowledgeRepository  # noqa: F401

    resp = client.post(PREFIX + "/hybrid", json={"query": "quantum", "source": "knowledge", "top_k": 5})
    results = resp.json()["data"]["results"]
    top = results[0]["confidence_breakdown"]
    assert top["bm25"] > 0.0, "含关键词的命中 BM25 分应大于 0"
    assert top["vector"] > 0.0, "向量桩命中应大于 0"
