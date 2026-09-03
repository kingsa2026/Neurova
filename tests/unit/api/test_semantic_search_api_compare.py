"""
Tier 3E.4 RED 测试 — /compare 端点聚合三路

验证 Bug 11：semantic_search_api.py:121-136 /compare 端点返回空三组
修复后应返回 bm25/vector/hybrid 三组对比结果。
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch
_USER = {"user_id": "1", "username": "u", "role": "user", "neuser_id": "1"}


def _fake_request():
    """空 agents 表的请求桩：走 get_memory_manager 单例降级路径"""
    req = MagicMock()
    req.app.state.agents = {}
    return req



class TestCompareSearchEndpoint:
    """/compare 端点应返回三路对比结果"""

    def test_compare_returns_three_channels(self):
        """RED: 应返回 bm25/vector/hybrid 三组结果"""
        from neurova.api.endpoints.semantic_search_api import CompareRequest, compare_search

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

            req = CompareRequest(query="机器学习", top_k=5)
            import asyncio
            result = asyncio.run(compare_search(req, _fake_request(), _USER))

        assert result["code"] == 0
        data = result["data"]
        assert "bm25_results" in data
        assert "vector_results" in data
        assert "hybrid_results" in data

    def test_compare_totals_consistent(self):
        """RED: total 字段应与 results 长度一致"""
        from neurova.api.endpoints.semantic_search_api import CompareRequest, compare_search

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
            mock_ss.search_by_keywords.return_value = ["mem_a"]
            mock_get_ss.return_value = mock_ss

            req = CompareRequest(query="test", top_k=5)
            import asyncio
            result = asyncio.run(compare_search(req, _fake_request(), _USER))

        data = result["data"]
        assert data["bm25_total"] == len(data["bm25_results"])
        assert data["vector_total"] == len(data["vector_results"])
        assert data["hybrid_total"] == len(data["hybrid_results"])
