"""P1 remaining① knowledge_integration 桩收口回归。

契约（§10 待拍板①）：
原 sync/* 把关联写进进程内 `_sync_links`（重启即丢、无消费方、假成功）；
/rag/retrieve 恒返回 items:[]（假空成功）。收口为：
- sync/knowledge-to-memory、sync/memory-to-kb → 落 KnowledgeStorage.memory_links
  （持久、可重启后 GET /sync/links 读到）；
- GET /sync/links → 读真存储（按 user_id 过滤）；
- POST /rag/retrieve → 真实检索（记忆 recall + 知识 search_visible_items），
  include_* 开关生效，命中如实带 items/score，无命中返回空但 total 真实；
- POST /rag/batch → 逐 query 真实检索；
- /gaps/analyze、/learn 保持诚实 501（无后端能力，不伪造）。
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from neurova.api.endpoints import knowledge_integration as ki


def _req(user_id="u1"):
    r = MagicMock()
    r.state = SimpleNamespace(user_id=user_id)
    r.app.state.agents = {}
    return r


class TestSyncPersistence:
    def test_knowledge_to_memory_persists_link(self, monkeypatch):
        storage = MagicMock()
        storage.create_memory_knowledge_link.return_value = "kbl_1"
        monkeypatch.setattr(ki, "_storage", lambda: storage)
        resp = asyncio.run(
            ki.sync_knowledge_to_memory(
                {"knowledge_id": "k1", "memory_id": "m1"}, _req()
            )
        )
        assert resp["code"] == 0
        storage.create_memory_knowledge_link.assert_called_once_with(
            "m1", "k1", relation="knowledge_to_memory"
        )

    def test_links_read_from_storage(self, monkeypatch):
        storage = MagicMock()
        storage.get_memory_links.return_value = [{"id": "kbl_1", "memory_id": "m1", "knowledge_id": "k1"}]
        monkeypatch.setattr(ki, "_storage", lambda: storage)
        resp = asyncio.run(ki.get_memory_knowledge_links(_req()))
        assert resp["data"]["total"] == 1
        assert resp["data"]["items"][0]["knowledge_id"] == "k1"

    def test_missing_ids_rejected(self, monkeypatch):
        monkeypatch.setattr(ki, "_storage", lambda: MagicMock())
        resp = asyncio.run(ki.sync_knowledge_to_memory({"knowledge_id": "k1"}, _req()))
        assert resp["code"] == 1  # 缺 memory_id，如实失败不假成功


class TestRagRetrieveReal:
    def test_knowledge_path_uses_hybrid(self, monkeypatch):
        """知识路必须与 chat 主路同源：走 hybrid，而不是第二条 TF-IDF 质量线。"""
        calls = {}

        def fake_hybrid(repo, user, query, limit=10, scope="all", **kwargs):
            calls["called"] = True
            return [{"knowledge_id": "k1", "title": "T", "content": "正文", "score": 0.7}]

        monkeypatch.setattr(
            "neurova.knowledge.hybrid.hybrid_search_knowledge", fake_hybrid
        )
        dummy = MagicMock()
        dummy.search_visible_items.return_value = []
        monkeypatch.setattr(
            "neurova.knowledge.repository.get_knowledge_repository", lambda *a, **k: dummy
        )

        resp = ki._retrieve_once("q", 3, False, True, _req())

        assert calls.get("called") is True, "知识路仍在走 search_visible_items 旧路"
        knowledge = [r for r in resp["results"] if r["source"] == "knowledge"][0]
        assert knowledge["retrieval_method"] == "hybrid"
        assert knowledge["items"][0]["id"] == "k1"

    def test_knowledge_path_uses_authenticated_identity_not_request_state(self, monkeypatch):
        """真实 JWT 装配下 request.state.user_id 可能为空；必须用端点注入的身份。"""
        seen = {}

        def fake_hits(query, user, top_k):
            seen["user"] = user
            return [{"knowledge_id": "k1", "title": "T", "content": "c"}]

        monkeypatch.setattr(ki, "_knowledge_hits", fake_hits)
        body = ki.RAGRetrieveRequest(query="q", include_memory=False, include_knowledge=True)

        asyncio.run(ki.rag_retrieve(
            body, _req(user_id=""), current_user={"user_id": "auth-user", "role": "admin"},
        ))

        assert seen["user"]["user_id"] == "auth-user"

    def test_returns_real_hits_not_empty_stub(self, monkeypatch):
        monkeypatch.setattr(
            ki, "_knowledge_hits",
            lambda query, user, top_k: [
                {"knowledge_id": "k1", "title": "T", "content": "正文", "score": 0.42},
            ],
        )
        mgr = MagicMock()
        mgr.recall.return_value = [{"id": "m1", "content": "记忆体", "temperature": 0.5}]
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_integration._memory_manager_for",
            lambda req: mgr,
        )
        body = ki.RAGRetrieveRequest(query="q", top_k=3, include_memory=True, include_knowledge=True)
        resp = asyncio.run(ki.rag_retrieve(
            body, _req(), current_user={"user_id": "u1", "role": "admin"}
        ))
        data = resp["data"]
        assert data["total"] == 2
        by_src = {r["source"]: r for r in data["results"]}
        assert by_src["knowledge"]["items"][0]["id"] == "k1"
        assert by_src["memory"]["items"][0]["id"] == "m1"

    def test_include_flags_respected(self, monkeypatch):
        monkeypatch.setattr(
            ki, "_knowledge_hits",
            lambda query, user, top_k: [
                {"knowledge_id": "k1", "title": "", "content": "c"},
            ],
        )
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_integration._memory_manager_for",
            lambda req: MagicMock(recall=lambda *a, **k: []),
        )
        body = ki.RAGRetrieveRequest(query="q", include_memory=False, include_knowledge=True)
        resp = asyncio.run(ki.rag_retrieve(
            body, _req(), current_user={"user_id": "u1", "role": "admin"}
        ))
        assert [r["source"] for r in resp["data"]["results"]] == ["knowledge"]

    def test_batch_real_retrieval(self, monkeypatch):
        monkeypatch.setattr(
            ki, "_knowledge_hits",
            lambda query, user, top_k: [
                {"knowledge_id": "kx", "title": "", "content": "c"},
            ],
        )
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_integration._memory_manager_for",
            lambda req: MagicMock(recall=lambda *a, **k: []),
        )
        resp = asyncio.run(ki.batch_rag_retrieve(
            {"queries": ["a", "b"]}, _req(),
            current_user={"user_id": "u1", "role": "admin"},
        ))
        assert len(resp["data"]["results"]) == 2
        assert resp["data"]["results"][0]["total"] >= 1
