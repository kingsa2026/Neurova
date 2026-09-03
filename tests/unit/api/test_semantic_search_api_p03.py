"""P0-3 混合检索复活 + rerank — API 层契约测试（TDD）。

契约（docs/Neurova_Dify代码级对比_2026-09-03.md §4 P0-3）：
1. POST /semantic-search/hybrid：data.retrieval_method 回显四态解析结果
   （RetrievalMethod 枚举 value：hybrid_search/semantic_search/
   full_text_search/keyword_search；非法值回退 hybrid_search）
2. fts 路真分数：full_text_search（IDF 加权词覆盖）给出归一化 [0,1] 分数，
   confidence_breakdown.fts 不再恒 0 占位
3. 检索方法分路：keyword/full_text 态不碰向量路；semantic 态不碰词法路
4. hybrid 出口接 rerank：body.rerank={"method":"weight","weights":{...}} 时
   结果按 rerank 分重排，每条带 rerank_score/rerank_method；异常降级 rrf 原序
"""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from neurova.api.endpoints.semantic_search_api import HybridSearchRequest

_USER = {"user_id": "1", "username": "u", "role": "user", "neuser_id": "1"}

# mem_a / mem_b 含查询词"机器学习"（分词命中）；mem_c 完全无关
_CORPUS = [
    {"id": "mem_a", "content": "机器学习算法原理与神经网络", "memory_type": "semantic"},
    {"id": "mem_b", "content": "深度学习与机器学习实践", "memory_type": "semantic"},
    {"id": "mem_c", "content": "今天的天气很好", "memory_type": "semantic"},
]


def _fake_request():
    req = MagicMock()
    req.app.state.agents = {}
    return req


def _mock_ss(similarity=0.5):
    """SemanticSearch 桩：仅向量路被 mock；词法路真算（语料确定性）"""
    ss = MagicMock()
    ss.compute_similarity.return_value = similarity
    return ss


def _run(body, mock_ss, **extra_patches):
    from contextlib import ExitStack

    from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, hybrid_search

    mock_mgr = MagicMock()
    mock_mgr.get_all_memories.return_value = _CORPUS
    with ExitStack() as stack:
        stack.enter_context(
            patch("neurova.api.endpoints.semantic_search_api.get_memory_manager", return_value=mock_mgr)
        )
        stack.enter_context(
            patch("neurova.api.endpoints.semantic_search_api.get_semantic_search", return_value=mock_ss)
        )
        for target, value in extra_patches.items():
            stack.enter_context(patch(target, value))
        return asyncio.run(hybrid_search(body, _fake_request(), _USER))


class TestFtsRevival:
    def test_fts_scores_not_all_zero(self):
        """fts 复活：词法命中的文档应有非 0 归一化分数（不再恒 0 占位）"""
        body = HybridSearchRequest(query="机器学习", top_k=5)
        result = _run(body, _mock_ss())

        by_id = {r["id"]: r for r in result["data"]["results"]}
        assert "mem_a" in by_id, f"mem_a 应被 fts/bm25 命中: {by_id}"
        fts_score = by_id["mem_a"]["confidence_breakdown"]["fts"]
        assert fts_score > 0.0, f"fts 分数不应恒 0: {by_id['mem_a']['confidence_breakdown']}"
        assert fts_score == pytest.approx(1.0, abs=0.01), "唯一查询词全命中 → 覆盖率 1.0"

    def test_fts_zero_hit_doc_has_zero_fts_score(self):
        body = HybridSearchRequest(query="机器学习", top_k=5)
        result = _run(body, _mock_ss())
        by_id = {r["id"]: r for r in result["data"]["results"]}
        if "mem_c" in by_id:  # mem_c 仅经向量路进入（相似度桩 0.5）
            assert by_id["mem_c"]["confidence_breakdown"]["fts"] == 0.0


class TestRetrievalMethodParam:
    def test_response_has_retrieval_method_default_hybrid(self):
        result = _run(HybridSearchRequest(query="机器学习", top_k=5), _mock_ss())
        assert result["data"]["retrieval_method"] == "hybrid_search"

    def test_keyword_method_skips_vector_path(self):
        """keyword 态：纯词法，不走向量路"""
        vec = MagicMock()
        result = _run(
            HybridSearchRequest(query="机器学习", top_k=5, retrieval_method="keyword"),
            _mock_ss(),
            **{"neurova.api.endpoints.semantic_search_api._vector_search_impl": vec},
        )
        assert result["data"]["retrieval_method"] == "keyword_search"
        vec.assert_not_called()
        ids = [r["id"] for r in result["data"]["results"]]
        assert "mem_a" in ids, f"关键词子串应命中 mem_a: {ids}"

    def test_semantic_method_skips_lexical_path(self):
        """semantic 态：纯向量，不走 fts/bm25 词法路"""
        fts = MagicMock()
        result = _run(
            HybridSearchRequest(query="机器学习", top_k=5, retrieval_method="semantic"),
            _mock_ss(),
            **{"neurova.api.endpoints.semantic_search_api._fts_search_impl": fts},
        )
        assert result["data"]["retrieval_method"] == "semantic_search"
        fts.assert_not_called()
        assert len(result["data"]["results"]) > 0

    def test_full_text_method_only_lexical(self):
        vec = MagicMock()
        result = _run(
            HybridSearchRequest(query="机器学习", top_k=5, retrieval_method="full_text"),
            _mock_ss(),
            **{"neurova.api.endpoints.semantic_search_api._vector_search_impl": vec},
        )
        assert result["data"]["retrieval_method"] == "full_text_search"
        vec.assert_not_called()
        assert len(result["data"]["results"]) > 0

    def test_invalid_method_falls_back_to_hybrid(self):
        result = _run(
            HybridSearchRequest(query="机器学习", top_k=5, retrieval_method="bogus"),
            _mock_ss(),
        )
        assert result["data"]["retrieval_method"] == "hybrid_search"


class TestRerankIntegration:
    def test_rerank_weight_resorts_results(self):
        """hybrid 出口接 rerank：rerank_score 覆盖 rrf 次序"""
        body = HybridSearchRequest(
            query="机器学习",
            top_k=3,
            rerank={"method": "weight", "weights": {"fts": 1.0, "bm25": 0.0, "vector": 0.0}},
        )
        result = _run(body, _mock_ss())
        results = result["data"]["results"]
        assert len(results) == 3
        # fts 命中：mem_a(1.0) > mem_b/mem_c(0) → rerank 后 mem_a 第一
        assert results[0]["id"] == "mem_a"
        assert results[0]["rerank_method"] == "weight"
        scores = [r["rerank_score"] for r in results]
        assert scores == sorted(scores, reverse=True), "rerank 后按 rerank_score 降序"

    def test_rerank_absent_keeps_rrf_order(self):
        """不带 rerank 参数 → 与旧契约一致（rrf 次序，无 rerank 字段）"""
        result = _run(HybridSearchRequest(query="机器学习", top_k=3), _mock_ss())
        assert all("rerank_score" not in r for r in result["data"]["results"])

    def test_rerank_failure_degrades_gracefully(self):
        """rerank 内部异常 → 降级 rrf 原序，不 500"""

        class BrokenRunner:
            def rerank(self, q, docs):
                raise RuntimeError("boom")

        body = HybridSearchRequest(
            query="机器学习", top_k=3,
            rerank={"method": "weight", "weights": {"fts": 1.0}},
        )
        result = _run(
            body, _mock_ss(),
            **{"neurova.api.endpoints.semantic_search_api._build_rerank_runner": BrokenRunner()},
        )
        assert result["code"] == 0
        assert len(result["data"]["results"]) > 0

    def test_rerank_model_without_provider_falls_back_to_weight(self):
        """model 态但 provider 未装配 → 退化加权融合（不报错）"""
        body = HybridSearchRequest(
            query="机器学习", top_k=3,
            rerank={"method": "model", "rerank_provider": "nonexistent"},
        )
        result = _run(body, _mock_ss())
        results = result["data"]["results"]
        assert len(results) > 0
        assert results[0]["rerank_method"] == "weight", "无 provider 应回退加权模式"
