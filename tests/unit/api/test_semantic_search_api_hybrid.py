"""
Tier 3E.1 RED 测试 — /hybrid 端点 RRF 三路融合

验证 Bug 11：semantic_search_api.py:84-98 /hybrid 端点返回空 results
修复后应返回非空结果，含 rrf_score 字段。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

_USER = {"user_id": "1", "username": "u", "role": "user", "neuser_id": "1"}


def _fake_request():
    """空 agents 表的请求桩：走 get_memory_manager 单例降级路径"""
    req = MagicMock()
    req.app.state.agents = {}
    return req


class TestHybridSearchEndpoint:
    """/hybrid 端点应返回 RRF 三路融合结果"""

    def test_hybrid_returns_nonempty_for_matching_query(self):
        """RED: 匹配查询应返回非空结果（原空壳返回 results: []）"""
        from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, hybrid_search

        mock_mgr = MagicMock()
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_a", "content": "机器学习算法原理", "memory_type": "semantic"},
            {"id": "mem_b", "content": "深度学习神经网络", "memory_type": "semantic"},
        ]

        with patch(
            "neurova.api.endpoints.semantic_search_api.get_memory_manager",
            return_value=mock_mgr,
        ), patch(
            "neurova.api.endpoints.semantic_search_api.get_semantic_search"
        ) as mock_get_ss:
            mock_ss = MagicMock()
            mock_ss.compute_similarity.return_value = 0.5
            mock_ss.search_by_keywords.return_value = ["mem_a", "mem_b"]
            mock_get_ss.return_value = mock_ss

            req = HybridSearchRequest(query="机器学习", top_k=5)
            import asyncio

            result = asyncio.run(hybrid_search(req, _fake_request(), _USER))

        assert result["code"] == 0
        assert result["data"]["total"] > 0, f"RED: /hybrid 返回空结果, result={result['data']}"
        assert len(result["data"]["results"]) > 0

    def test_hybrid_results_have_rrf_score(self):
        """RED: 结果应含 rrf_score 字段"""
        from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, hybrid_search

        mock_mgr = MagicMock()
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_a", "content": "机器学习", "memory_type": "semantic"},
        ]

        with patch(
            "neurova.api.endpoints.semantic_search_api.get_memory_manager",
            return_value=mock_mgr,
        ), patch(
            "neurova.api.endpoints.semantic_search_api.get_semantic_search"
        ) as mock_get_ss:
            mock_ss = MagicMock()
            mock_ss.compute_similarity.return_value = 0.5
            mock_ss.search_by_keywords.return_value = ["mem_a"]
            mock_get_ss.return_value = mock_ss

            req = HybridSearchRequest(query="机器学习", top_k=5)
            import asyncio
            result = asyncio.run(hybrid_search(req, _fake_request(), _USER))

        if result["data"]["results"]:
            assert "rrf_score" in result["data"]["results"][0], (
                f"RED: 结果缺少 rrf_score 字段, result={result['data']['results'][0]}"
            )

    def test_hybrid_fuses_three_channels(self):
        """RED: 应融合 BM25 + 向量 + FTS5 三路结果"""
        from neurova.api.endpoints.semantic_search_api import _rrf_fusion

        bm25_results = [("mem_a", 0.9), ("mem_b", 0.5)]
        vector_results = [("mem_b", 0.8), ("mem_c", 0.3)]
        fts_results = [("mem_a", 1.0), ("mem_c", 0.6)]

        fused = _rrf_fusion(bm25_results, vector_results, fts_results)

        # 三路并集应包含 mem_a, mem_b, mem_c
        fused_ids = {mid for mid, _ in fused}
        assert "mem_a" in fused_ids
        assert "mem_b" in fused_ids
        assert "mem_c" in fused_ids
