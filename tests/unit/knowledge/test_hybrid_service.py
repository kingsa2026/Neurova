"""P0#4 知识混合检索服务测试。

契约：
- hybrid_search_knowledge 四路 RRF：tfidf 分片 + bm25 + fts + vector（持久化
  ONNX 索引），融合权重缺省 tfidf/bm25/vector/fts = .30/.30/.25/.15。
- tfidf 路复用 repo.search_visible_items（主路，异常不吞——全链故障要暴露）；
  bm25/fts/vector 三路独立降级（单路异常只少一个视角，不阻断检索）。
- 结果 = 可见条目 dict + score（RRF）+ confidence_breakdown（四路 + rrf）。
- semantic_search_api 的 _bm25_search/_rrf_fusion 委托本模块（单源，防分叉；
  模块全局名保持可 monkeypatch）。
- KnowledgeRetrieverAdapter（chat 路）经 hybrid 检索：真实仓库命中含向量路，
  Mock 仓库自动降级 tfidf 路（旧测试契约不破）。
"""

import types

import pytest

from neurova.knowledge import hybrid
from neurova.knowledge.repository import KnowledgeRepository


# ── 融合与词法单源 ──────────────────────────────────────────────


class TestRRFFusion:
    def test_weighted_rank_fusion(self):
        routes = {
            "a": [("d1", 9.0), ("d2", 5.0)],
            "b": [("d2", 8.0), ("d1", 1.0)],
        }
        fused = hybrid.rrf_fusion(routes, {"a": 0.6, "b": 0.4}, k=60)
        ids = [i for i, _ in fused]
        assert set(ids) == {"d1", "d2"}
        # d1: 0.6/61 + 0.4/62 ; d2: 0.6/62 + 0.4/61 → d1 > d2
        assert ids[0] == "d1"

    def test_missing_route_zero(self):
        routes = {"a": [("d1", 1.0)], "b": []}
        fused = hybrid.rrf_fusion(routes, {"a": 0.5, "b": 0.5})
        assert [i for i, _ in fused] == ["d1"]
        assert fused[0][1] == pytest.approx(0.5 / 61)

    def test_api_delegate_single_source(self):
        """API 层融合/分词必须委托本模块（防 preview/生产分叉教训重演）。"""
        from neurova.api.endpoints import semantic_search_api as api

        assert api._rrf_fusion(
            [("x", 1.0)], [("y", 2.0)], [], bm25_weight=0.5, vector_weight=0.5, fts_weight=0.0
        ) == hybrid.rrf_fusion(
            {"bm25": [("x", 1.0)], "vector": [("y", 2.0)], "fts": []},
            {"bm25": 0.5, "vector": 0.5, "fts": 0.0},
        )


class TestBM25Parity:
    corpus = [
        {"id": "a", "content": "NeurFlow 工作流引擎 触发器"},
        {"id": "b", "content": "今天天气不错"},
        {"id": "c", "content": "工作流 编排 系统"},
    ]

    def test_parity_with_api_history(self):
        from neurova.api.endpoints import semantic_search_api as api

        got = api._bm25_search("工作流", self.corpus, top_k=3)
        ref = [(doc["id"], sum(1 for _ in [])) for doc in []]  # noqa  # 语义在下方断言
        ids = [i for i, _ in got]
        assert ids[0] in ("a", "c")
        assert "b" not in ids[:2]

    def test_hybrid_module_bm25_parity(self):
        """API 层 _bm25_search 必须与 hybrid.bm25_rank 同输出（委托单源）。"""
        from neurova.api.endpoints import semantic_search_api as api

        assert api._bm25_search("工作流", self.corpus, top_k=3) == hybrid.bm25_rank(
            "工作流", self.corpus, top_k=3
        )


# ── 知识混合检索主函数 ──────────────────────────────────────────


@pytest.fixture
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path))
    r.create_knowledge(
        "default", "工作流引擎", "NeurFlow 支持触发器与工作流编排", owner_user_id="1",
        confidence=0.9,
    )
    r.create_knowledge("default", "天气笔记", "今天天气不错适合散步", owner_user_id="1")
    r.create_knowledge(
        "default", "向量文档", "向量检索语义相似工作流", owner_user_id="1",
    )
    return r


def _stub_vector_index(hits):
    return types.SimpleNamespace(search=lambda q, user, top_k=10, repo=None: list(hits))


class TestHybridSearchKnowledge:
    def test_four_routes_breakdown(self, repo):
        # 向量路命中"工作流引擎"：词法两路它屈居"向量文档"之后，        # vector 第一秩 + 0.25 权重把综合分抬到第一 → 证明向量路真实参与排序
        kid_wflow = repo._items["default"][0]["knowledge_id"]
        vec = _stub_vector_index([{"id": kid_wflow, "score": 0.8}])
        results = hybrid.hybrid_search_knowledge(
            repo, {"user_id": "1"}, "工作流 向量检索", limit=5, vector_index=vec
        )
        assert results
        top = results[0]
        assert {"tfidf", "bm25", "vector", "fts", "rrf"} <= set(top["confidence_breakdown"])
        assert top["score"] > 0
        # "工作流引擎" 同时命中 tfidf+bm25(+fts) → 排最前
        assert top["title"] == "工作流引擎"
        # 向量独中的"向量文档"也应进入结果（vector 路贡献）
        titles = [r["title"] for r in results]
        assert "向量文档" in titles

    def test_vector_route_absent_degrades(self, repo):
        vec = _stub_vector_index([])
        results = hybrid.hybrid_search_knowledge(
            repo, {"user_id": "1"}, "触发器", limit=5, vector_index=vec
        )
        assert [r["title"] for r in results] == ["工作流引擎"]
        assert results[0]["confidence_breakdown"]["vector"] == 0.0

    def test_vector_route_exception_degrades(self, repo):
        boom = types.SimpleNamespace(
            search=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("embedding down"))
        )
        results = hybrid.hybrid_search_knowledge(
            repo, {"user_id": "1"}, "触发器", limit=5, vector_index=boom
        )
        assert results and results[0]["title"] == "工作流引擎"

    def test_tfdf_route_exception_propagates(self, repo):
        """tfidf 主路异常必须上抛（全链故障不许被降级吞掉——修复教义）。"""
        broken = types.SimpleNamespace(
            search_visible_items=lambda **k: (_ for _ in ()).throw(RuntimeError("db down")),
            visible_items=lambda *a, **k: [],
        )
        with pytest.raises(RuntimeError):
            hybrid.hybrid_search_knowledge(
                broken, {"user_id": "1"}, "q", limit=5, vector_index=_stub_vector_index([])
            )

    def test_empty_corpus_empty(self, repo):
        results = hybrid.hybrid_search_knowledge(
            repo, {"user_id": "nobody"}, "工作流", limit=5,
            vector_index=_stub_vector_index([]),
        )
        assert results == []

    def test_isolation_preserved(self, repo):
        """他人 private 条目不得从任何路进入结果（vector 路按用户文件天然隔离，
        bm25/fts 语料来自 visible_items）。"""
        vec = _stub_vector_index([{"id": repo._items["default"][0]["knowledge_id"], "score": 0.9}])
        results = hybrid.hybrid_search_knowledge(
            repo, {"user_id": "999"}, "工作流", limit=5, vector_index=vec
        )
        assert results == []  # user999 无可见条目 → visible 先行

    def test_chunk_hits_passthrough(self, repo):
        results = hybrid.hybrid_search_knowledge(
            repo, {"user_id": "1"}, "NeurFlow 触发器", limit=5,
            vector_index=_stub_vector_index([]),
        )
        assert results and "chunk_hits" in results[0]


class TestAdapterUsesHybrid:
    @pytest.mark.asyncio
    async def test_adapter_routes_through_hybrid_vector_enabled(self, repo, monkeypatch):
        """chat 路（P0#4）：adapter 经 hybrid 四路融合，向量路命中参与排序。"""
        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
        from neurova.agent.memory_retrieval_chain import RetrievalContext

        kid_vec_only = repo._items["default"][2]["knowledge_id"]  # "向量文档"

        # 单例向量索引 → 桩（不触发真 ONNX）；query 词面上不命中"向量文档"的        # bm25/fts 主词，仅向量路命中
        monkeypatch.setattr(
            "neurova.knowledge.vector_index.get_knowledge_vector_index",
            lambda: _stub_vector_index([{"id": kid_vec_only, "score": 0.8}]),
        )
        adapter = KnowledgeRetrieverAdapter(repo)
        ctx = RetrievalContext(query="语义相似", limit=5, user_id="1")
        result = await adapter.retrieve(ctx)
        titles = {m["title"] for m in result.memories}
        assert "向量文档" in titles, "P0#4 后向量路命中必须进 chat 检索结果"

    @pytest.mark.asyncio
    async def test_adapter_mock_repo_degrades(self):
        """Mock 仓库（旧测试惯用法）：hybrid 自动降级 tfidf 主路，不炸。"""
        from unittest.mock import MagicMock, Mock

        from neurova.agent.knowledge_retriever_adapter import KnowledgeRetrieverAdapter
        from neurova.agent.memory_retrieval_chain import RetrievalContext

        mrepo = Mock()
        mrepo.search_visible_items = MagicMock(return_value=[
            {"knowledge_id": "k1", "title": "T", "content": "C", "category": "x",
             "tags": [], "source": "s", "confidence": 0.5, "visibility": "private"},
        ])
        adapter = KnowledgeRetrieverAdapter(mrepo)
        result = await adapter.retrieve(RetrievalContext(query="q", user_id="u1"))
        assert len(result.memories) == 1
        assert result.memories[0]["title"] == "T"
