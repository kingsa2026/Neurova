"""
Tier 3E.3 RED 测试 — /vector 端点 SemanticSearch 实现

验证 Bug 11：semantic_search_api.py:111-118 /vector 端点返回空 results
修复后应返回基于 SemanticSearch.compute_similarity 的语义相关结果。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

_USER = {"user_id": "1", "username": "u", "role": "user", "neuser_id": "1"}


def _fake_request():
    """空 agents 表的请求桩：走 get_memory_manager 单例降级路径"""
    req = MagicMock()
    req.app.state.agents = {}
    return req


class TestVectorSearchEndpoint:
    """/vector 端点应返回语义相似度结果"""

    def test_vector_returns_semantic_matches(self):
        """RED: 应返回语义匹配结果（非空）"""
        from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, vector_search

        mock_mgr = MagicMock()
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_a", "content": "机器学习算法", "memory_type": "semantic"},
        ]

        with patch(
            "neurova.api.endpoints.semantic_search_api.get_memory_manager",
            return_value=mock_mgr,
        ), patch(
            "neurova.api.endpoints.semantic_search_api.get_semantic_search"
        ) as mock_get_ss:
            mock_ss = MagicMock()
            mock_ss.compute_similarity.return_value = 0.75
            mock_get_ss.return_value = mock_ss

            req = HybridSearchRequest(query="机器学习", top_k=5)
            import asyncio

            result = asyncio.run(vector_search(req, _fake_request(), _USER))

        assert result["code"] == 0
        assert result["data"]["total"] > 0, f"RED: /vector 返回空结果"
        assert len(result["data"]["results"]) > 0

    def test_vector_score_in_range_0_1(self):
        """RED: 分数应在 [0, 1] 范围内"""
        from neurova.api.endpoints.semantic_search_api import HybridSearchRequest, vector_search

        mock_mgr = MagicMock()
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_a", "content": "test", "memory_type": "semantic"},
        ]

        with patch(
            "neurova.api.endpoints.semantic_search_api.get_memory_manager",
            return_value=mock_mgr,
        ), patch(
            "neurova.api.endpoints.semantic_search_api.get_semantic_search"
        ) as mock_get_ss:
            mock_ss = MagicMock()
            mock_ss.compute_similarity.return_value = 0.5
            mock_get_ss.return_value = mock_ss

            req = HybridSearchRequest(query="test", top_k=5)
            import asyncio
            result = asyncio.run(vector_search(req, _fake_request(), _USER))

        for r in result["data"]["results"]:
            assert 0.0 <= r["score"] <= 1.0, f"RED: 分数超出 [0,1], score={r['score']}"
