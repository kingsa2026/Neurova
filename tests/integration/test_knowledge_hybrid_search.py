"""
混合检索接入知识条目语料（批次 2 / B1）

契约：
- POST /api/v1/semantic-search/hybrid 的 body.source 支持 "memory"（默认，行为不变）
  与 "knowledge"（语料 = 当前用户可见知识条目，标题+正文）
- source=knowledge 时受知识库可见性过滤：他人私有条目不可见
- 默认 memory 路径不串入知识条目

零网络：monkeypatch 知识仓库单例工厂与 SemanticSearch（关键词重叠桩）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as semantic_auth
from neurova.api.endpoints import semantic_search_api as ssa

PREFIX = "/v1/semantic-search"

ALICE = {"user_id": "1", "username": "alice", "role": "user", "neuser_id": "1"}
BOB = {"user_id": "2", "username": "bob", "role": "user", "neuser_id": "2"}


class StubEngine:
    """确定性 embedding 桩：固定词表 one-hot"""

    VOCAB = ["quantum", "rust", "async", "cookie", "recipe", "travel", "sales", "plan"]

    def encode(self, text):
        t = (text or "").lower()
        return [1.0 if w in t else 0.0 for w in self.VOCAB]

    def encode_batch(self, texts):
        return [self.encode(t) for t in texts]


class StubSemanticSearch:
    """确定性相似度桩：基于字符重叠，避免真实 ONNX 加载"""

    def compute_similarity(self, query: str, content: str) -> float:
        q = set(query)
        c = set(content or "")
        if not q or not c:
            return 0.0
        return len(q & c) / len(q | c)

    def build_keyword_index(self, corpus):
        self._corpus = corpus

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
    # 向量路走持久化索引桩（避免真实 ONNX）
    monkeypatch.setattr(
        vi, "get_knowledge_vector_index",
        lambda: KnowledgeVectorIndex(str(tmp_path / "vec"), engine=StubEngine()),
    )

    holder = {"user": dict(ALICE)}
    app = FastAPI()
    app.include_router(ssa.router, prefix=PREFIX)
    app.dependency_overrides[semantic_auth.get_current_user_or_service] = lambda: holder["user"]
    # 断开真实记忆源：默认 memory 路径不串入测试知识条目
    monkeypatch.setattr(
        ssa, "_get_runtime_memory_manager", lambda request: type("M", (), {"get_all_memories": lambda self: []})()
    )
    client = TestClient(app)
    return client, holder, r, app


def _seed_knowledge(r, owner, visibility, title, content):
    r.create_knowledge(
        "agent-a", title=title, content=content,
        visibility=visibility, owner_user_id=owner,
    )


def test_knowledge_source_hits_visible_entries_only(client):
    c, holder, r, _app = client
    _seed_knowledge(r, "1", "private", "Quantum Guide", "quantum computing explained deeply")
    _seed_knowledge(r, "1", "private", "Secret Recipe", "grandma cookie recipe")

    resp = c.post(PREFIX + "/hybrid", json={"query": "quantum computing", "source": "knowledge", "top_k": 5})
    assert resp.status_code == 200, resp.text
    results = resp.json()["data"]["results"]
    # 最相关命中排第一（桩相似度粗粒度，低分噪声允许出现在尾部）
    assert results[0]["title"] == "Quantum Guide"

    # bob 搜索不到 alice 的私有条目
    holder["user"] = dict(BOB)
    resp = c.post(PREFIX + "/hybrid", json={"query": "quantum computing", "source": "knowledge", "top_k": 5})
    assert resp.json()["data"]["results"] == []


def test_public_knowledge_hit_and_title_in_result(client):
    c, _holder, r, _app = client
    _seed_knowledge(r, "2", "public", "Rust Async Handbook", "async runtimes in rust")

    resp = c.post(PREFIX + "/hybrid", json={"query": "async rust runtimes", "source": "knowledge", "top_k": 5})
    results = resp.json()["data"]["results"]
    assert len(results) == 1
    assert results[0]["title"] == "Rust Async Handbook"


def test_default_memory_source_stays_memory(client):
    c, _holder, _r, _app = client
    resp = c.post(PREFIX + "/hybrid", json={"query": "anything"})
    data = resp.json()["data"]
    assert resp.status_code == 200
    assert data["results"] == []  # 记忆语料为空桩 → 无知识条目串入


def test_anonymous_gets_401(client):
    c, _holder, _r, app = client
    app.dependency_overrides.clear()
    resp = c.post(PREFIX + "/hybrid", json={"query": "q", "source": "knowledge"})
    assert resp.status_code == 401
