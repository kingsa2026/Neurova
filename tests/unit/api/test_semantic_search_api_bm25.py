"""
Tier 3E.2 RED 测试 — /bm25 端点 Okapi BM25 实现

验证 Bug 11：semantic_search_api.py:101-108 /bm25 端点返回空 results
修复后应返回按 BM25 分数降序的结果。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
_USER = {"user_id": "1", "username": "u", "role": "user", "neuser_id": "1"}


def _fake_request():
    """空 agents 表的请求桩：走 get_memory_manager 单例降级路径"""
    req = MagicMock()
    req.app.state.agents = {}
    return req



class TestBM25SearchEndpoint:
    """/bm25 端点应返回 Okapi BM25 排序结果"""

    def test_bm25_returns_ranked_results(self):
        """RED: 应返回按 BM25 分数降序的结果"""
        from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, bm25_search

        mock_mgr = MagicMock()
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_a", "content": "机器学习算法", "memory_type": "semantic"},
            {"id": "mem_b", "content": "完全无关内容", "memory_type": "semantic"},
        ]

        with patch(
            "neurova.api.endpoints.semantic_search_api.get_memory_manager",
            return_value=mock_mgr,
        ):
            req = HybridSearchRequest(query="机器学习", top_k=5)
            import asyncio
            result = asyncio.run(bm25_search(req, _fake_request(), _USER))

        assert result["code"] == 0
        assert result["data"]["total"] > 0, f"RED: /bm25 返回空结果"
        results = result["data"]["results"]
        # 分数应降序
        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True), f"RED: 分数未降序, scores={scores}"

    def test_bm25_score_in_range_0_1(self):
        """RED: 分数应归一化到 [0, 1]"""
        from neurova.api.endpoints.semantic_search_api import _bm25_search

        corpus = [
            {"id": "d1", "content": "machine learning algorithm"},
            {"id": "d2", "content": "deep learning neural network"},
            {"id": "d3", "content": "unrelated content xyz"},
        ]

        results = _bm25_search("learning", corpus, top_k=3)

        for _, score in results:
            assert 0.0 <= score <= 1.0, f"RED: 分数超出 [0,1], score={score}"

    def test_bm25_handles_empty_corpus(self):
        """RED: 空语料应返回空"""
        from neurova.api.endpoints.semantic_search_api import _bm25_search

        results = _bm25_search("query", [], top_k=5)
        assert results == [], f"RED: 空语料应返回空, got {results}"

    def test_bm25_ranks_relevant_higher(self):
        """RED: 相关文档应排名更高"""
        from neurova.api.endpoints.semantic_search_api import _bm25_search

        corpus = [
            {"id": "relevant", "content": "机器学习 机器学习 机器学习"},
            {"id": "irrelevant", "content": "完全无关内容 abc xyz"},
        ]

        results = _bm25_search("机器学习", corpus, top_k=2)
        score_map = dict(results)
        assert score_map["relevant"] > score_map["irrelevant"], (
            f"RED: 相关文档应排名更高, scores={score_map}"
        )
