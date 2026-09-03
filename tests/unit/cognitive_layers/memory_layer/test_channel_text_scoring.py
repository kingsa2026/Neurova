"""
Tier 3D.1 RED 测试 — _channel_text 硬编码 score 修复验证

验证 Bug 13：neurova_recall.py:965 _channel_text 中 score=0.8 硬编码
不同 query/content 组合应产生不同 score，而非全部 0.8。
"""
from __future__ import annotations

from unittest.mock import MagicMock
from typing import Any, Dict, List


class TestChannelTextScoring:
    """_channel_text 返回的 score 应反映真实相似度，非硬编码 0.8"""

    def test_channel_text_score_not_all_equal(self, tmp_path):
        """RED: 不同内容的记忆应有不同 score（非全部 0.8）"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine
        from neurova.cognitive_layers.memory_layer import semantic_search as ss_module

        # 重置 SemanticSearch 单例，用关键词模式（不依赖 ONNX）
        ss_module._reset_semantic_search()

        # 构造 mock memory_manager
        mock_mgr = MagicMock()
        # 提供两条不同内容的记忆
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_a", "content": "机器学习算法原理", "memory_type": "semantic"},
            {"id": "mem_b", "content": "今天天气真好适合出门", "memory_type": "semantic"},
        ]

        engine = NeurovaRecallEngine(memory_manager=mock_mgr, use_plugins=False)

        # 调用 _channel_text（query 含"机器学习"，应匹配 mem_a）
        results = engine._channel_text("机器学习", limit=10)

        # 如果有结果，score 不应全是 0.8
        if results:
            scores = {r.score for r in results}
            # Bug 13 RED: 硬编码时所有 score 都是 0.8，集合长度为 1
            # 修复后：不同内容应有不同 score
            # 注：若只返回 1 条结果，集合长度必然为 1，需检查 score != 0.8
            assert 0.8 not in scores or len(scores) > 1, (
                f"RED: score 全是 0.8 硬编码（Bug 13）, scores={scores}"
            )

    def test_channel_text_score_reflects_similarity(self, tmp_path):
        """RED: 相似内容的 score 应高于不相似内容"""
        from neurova.cognitive_layers.memory_layer.neurova_recall import NeurovaRecallEngine
        from neurova.cognitive_layers.memory_layer import semantic_search as ss_module

        ss_module._reset_semantic_search()

        mock_mgr = MagicMock()
        mock_mgr.get_all_memories.return_value = [
            {"id": "mem_similar", "content": "机器学习算法", "memory_type": "semantic"},
            {"id": "mem_different", "content": "完全无关的内容 xyz", "memory_type": "semantic"},
        ]

        engine = NeurovaRecallEngine(memory_manager=mock_mgr, use_plugins=False)
        results = engine._channel_text("机器学习", limit=10)

        if len(results) >= 2:
            score_map = {r.memory_id: r.score for r in results}
            # 相似内容的 score 应 >= 不相似内容
            assert score_map.get("mem_similar", 0) >= score_map.get("mem_different", 0), (
                f"RED: 相似内容 score 应更高, score_map={score_map}"
            )
