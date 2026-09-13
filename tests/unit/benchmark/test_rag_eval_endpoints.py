# -*- coding: utf-8 -*-
"""RAG 评估端点冒烟（P1 #5）：CRUD/evaluate 真跑、generate 无 LLM 503 诚实。"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as auth_mod
from neurova.api.endpoints import benchmark as bm
from neurova.benchmark import rag_eval


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_RAG_EVAL_DATASETS", str(tmp_path / "ds.json"))
    rag_eval._datasets_path.cache_clear() if hasattr(rag_eval._datasets_path, "cache_clear") else None
    app = FastAPI()
    app.include_router(bm.router, prefix="/api/v1/benchmark")
    app.dependency_overrides[auth_mod.get_current_user] = lambda: {"user_id": "u1", "role": "user"}
    return TestClient(app)


def _mk_dataset(client):
    return client.post(
        "/api/v1/benchmark/rag-datasets",
        json={
            "name": "smoke", "description": "",
            "items": [
                {"query": "q1", "gold_chunk_ids": ["kA#0"], "gold_answer": None},
                {"query": "q2", "gold_chunk_ids": ["kZ#0"], "gold_answer": None},
            ],
        },
    ).json()["data"]


def test_dataset_crud_endpoints(client):
    ds = _mk_dataset(client)
    assert client.get("/api/v1/benchmark/rag-datasets").json()["data"]["datasets"][0]["id"] == ds["id"]
    upd = client.put(
        f"/api/v1/benchmark/rag-datasets/{ds['id']}",
        json={"name": "renamed", "description": "", "items": []},
    )
    assert upd.json()["data"]["name"] == "renamed"
    assert client.delete(f"/api/v1/benchmark/rag-datasets/{ds['id']}").status_code == 200
    assert client.delete(f"/api/v1/benchmark/rag-datasets/{ds['id']}").status_code == 404


def test_evaluate_endpoint_real_metrics(client, monkeypatch):
    ds = _mk_dataset(client)

    class _Repo:
        def search_visible_items(self, user, query, agent_id=None, limit=20, **kw):
            table = {"q1": [("kA", [0, 1])], "q2": [("kX", [0])]}
            out = []
            for kid, idxs in table.get(query, []):
                out.append({
                    "knowledge_id": kid, "score": 1.0,
                    "chunk_hits": [{"chunk_index": i, "score": 1.0 - j * 0.1} for j, i in enumerate(idxs)],
                })
            return out

    import neurova.knowledge.repository as repo_mod

    monkeypatch.setattr(repo_mod, "get_knowledge_repository", lambda: _Repo())
    r = client.post("/api/v1/benchmark/rag-evaluate", json={"dataset_id": ds["id"], "top_k": 3})
    data = r.json()["data"]
    assert data["n_items"] == 2
    # q1 recall@1=1（kA#0 首位）、q2 全错 → 均值 0.5
    assert data["mean"]["recall@1"] == pytest.approx(0.5)


def test_generate_without_llm_is_503_honest(client, monkeypatch):
    monkeypatch.setattr(bm, "_rag_llm_fn", lambda agent_id: None)
    r = client.post("/api/v1/benchmark/rag-datasets/generate", json={"sample_n": 3})
    assert r.status_code == 503
    assert "拒绝伪造" in r.json()["detail"]


def test_generate_endpoint_with_fake_llm(client, monkeypatch):
    monkeypatch.setattr(bm, "_rag_llm_fn", lambda agent_id: (lambda prompt: '{"question": "这讲什么？", "answer": "讲块内容"}'))

    class _Repo:
        def visible_items(self, user, scope="all", agent_id=None, **kw):
            return [{
                "knowledge_id": "kA", "title": "T", "content": "甲乙丙",
                "chunks": [{"char_start": i, "char_end": i + 1} for i in range(3)],
            }]

    import neurova.knowledge.repository as repo_mod

    monkeypatch.setattr(repo_mod, "get_knowledge_repository", lambda: _Repo())
    r = client.post("/api/v1/benchmark/rag-datasets/generate", json={"sample_n": 2})
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["generated"] == 2
    assert all("#" in c for row in data["dataset"]["items"] for c in row["gold_chunk_ids"])
