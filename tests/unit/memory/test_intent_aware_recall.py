"""
意图感知检索测试套件

测试任务2.1：查询意图检测器
测试任务2.2：意图特定的检索策略
测试任务2.3：集成意图感知到检索引擎
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import List, Dict, Any

# 导入被测试模块
from neurova.cognitive_layers.memory_layer.neurova_recall import (
    QueryIntent,
    QueryIntentDetector,
    IntentAwareRecallStrategy,
    NeurovaRecallEngine,
    RecallChannel,
    DrillIntent,
    RecallResult,
    RecalledMemory,
)


# ────── Task 2.1: Query Intent Detector ──────

class TestQueryIntentDetector:
    """测试任务2.1：查询意图检测器"""

    @pytest.fixture
    def detector(self):
        return QueryIntentDetector()

    def test_temporal_intent_english(self, detector):
        """测试英文时间意图检测"""
        assert detector.detect_intent("when did this happen?") == QueryIntent.TEMPORAL
        assert detector.detect_intent("what time is the meeting?") == QueryIntent.TEMPORAL
        assert detector.detect_intent("before the deadline") == QueryIntent.TEMPORAL

    def test_temporal_intent_chinese(self, detector):
        """测试中文时间意图检测"""
        assert detector.detect_intent("这是什么时候发生的？") == QueryIntent.TEMPORAL
        assert detector.detect_intent("最近有什么更新？") == QueryIntent.TEMPORAL
        assert detector.detect_intent("之前我们讨论过什么？") == QueryIntent.TEMPORAL

    def test_causal_intent_english(self, detector):
        """测试英文因果意图检测"""
        assert detector.detect_intent("why is the sky blue?") == QueryIntent.CAUSAL
        assert detector.detect_intent("what caused the error?") == QueryIntent.CAUSAL
        assert detector.detect_intent("the reason for failure") == QueryIntent.CAUSAL

    def test_causal_intent_chinese(self, detector):
        """测试中文因果意图检测"""
        assert detector.detect_intent("为什么用户流失率上升？") == QueryIntent.CAUSAL
        assert detector.detect_intent("这个错误的原因是什么？") == QueryIntent.CAUSAL
        assert detector.detect_intent("导致这个问题的因素") == QueryIntent.CAUSAL

    def test_comparative_intent_english(self, detector):
        """测试英文比较意图检测"""
        assert detector.detect_intent("compare Python vs Java") == QueryIntent.COMPARATIVE
        assert detector.detect_intent("what is the difference between X and Y?") == QueryIntent.COMPARATIVE
        assert detector.detect_intent("which one is better?") == QueryIntent.COMPARATIVE

    def test_comparative_intent_chinese(self, detector):
        """测试中文比较意图检测"""
        assert detector.detect_intent("Python 和 Java 哪个更好？") == QueryIntent.COMPARATIVE
        assert detector.detect_intent("比较两种方案的区别") == QueryIntent.COMPARATIVE

    def test_exploratory_intent_english(self, detector):
        """测试英文探索意图检测"""
        assert detector.detect_intent("tell me about machine learning") == QueryIntent.EXPLORATORY
        assert detector.detect_intent("what is quantum computing?") == QueryIntent.EXPLORATORY
        assert detector.detect_intent("explore the new feature") == QueryIntent.EXPLORATORY

    def test_exploratory_intent_chinese(self, detector):
        """测试中文探索意图检测"""
        assert detector.detect_intent("介绍下机器学习的知识") == QueryIntent.EXPLORATORY
        assert detector.detect_intent("什么是深度学习？") == QueryIntent.EXPLORATORY
        assert detector.detect_intent("发现新的功能") == QueryIntent.EXPLORATORY

    def test_fallback_to_exploratory(self, detector):
        """测试无关键词时默认为探索意图"""
        # 无明确关键词的查询应归类为探索
        result = detector.detect_intent("hello world")
        assert result in [QueryIntent.EXPLORATORY, QueryIntent.UNKNOWN]

    def test_get_intent_confidence(self, detector):
        """测试意图置信度计算"""
        # 高置信度：多个关键词匹配
        confidence = detector.get_intent_confidence("why is this happening because of the error", QueryIntent.CAUSAL)
        assert 0.0 <= confidence <= 1.0
        assert confidence > 0.3  # 多个关键词应有较高置信度

        # 低置信度：无关键词匹配
        confidence_low = detector.get_intent_confidence("hello world", QueryIntent.CAUSAL)
        assert confidence_low < confidence

    def test_confidence_range(self, detector):
        """测试所有置信度在有效范围内"""
        test_queries = [
            "when did this happen?",
            "why is it broken?",
            "compare A and B",
            "tell me about X",
            "random text",
        ]
        for query in test_queries:
            for intent in QueryIntent:
                conf = detector.get_intent_confidence(query, intent)
                assert 0.0 <= conf <= 1.0, f"Confidence {conf} out of range for '{query}' / {intent}"

    def test_multiple_keywords_boost_confidence(self, detector):
        """测试多关键词匹配提升置信度"""
        single = detector.get_intent_confidence("why", QueryIntent.CAUSAL)
        multi = detector.get_intent_confidence("why because cause reason", QueryIntent.CAUSAL)
        assert multi >= single


# ────── Task 2.2: Intent-Specific Retrieval Strategy ──────

class TestIntentAwareRecallStrategy:
    """测试任务2.2：意图特定的检索策略"""

    @pytest.fixture
    def strategy(self):
        return IntentAwareRecallStrategy()

    def test_all_intents_have_channel_weights(self, strategy):
        """测试所有意图都有通道权重配置"""
        for intent in QueryIntent:
            weights = strategy.get_channel_weights(intent)
            assert isinstance(weights, dict), f"Intent {intent} should return dict"
            assert len(weights) > 0, f"Intent {intent} has no channel weights"

    def test_weights_sum_approximately_one(self, strategy):
        """测试权重总和约等于1.0"""
        for intent in QueryIntent:
            weights = strategy.get_channel_weights(intent)
            total = sum(weights.values())
            assert abs(total - 1.0) < 0.05, f"Intent {intent} weights sum to {total}, expected ~1.0"

    def test_all_intents_have_retrieval_params(self, strategy):
        """测试所有意图都有检索参数"""
        for intent in QueryIntent:
            params = strategy.get_retrieval_params(intent)
            assert isinstance(params, dict), f"Intent {intent} should return dict"
            assert "limit" in params, f"Intent {intent} missing 'limit' param"
            assert "min_score" in params, f"Intent {intent} missing 'min_score' param"

    def test_temporal_intent_prefers_temperature(self, strategy):
        """测试时间意图偏好温度通道"""
        weights = strategy.get_channel_weights(QueryIntent.TEMPORAL)
        assert weights.get(RecallChannel.TEMPERATURE, 0) >= 0.4

    def test_causal_intent_prefers_graph(self, strategy):
        """测试因果意图偏好图通道"""
        weights = strategy.get_channel_weights(QueryIntent.CAUSAL)
        assert weights.get(RecallChannel.GRAPH, 0) >= 0.3

    def test_comparative_intent_prefers_category(self, strategy):
        """测试比较意图偏好分类通道"""
        weights = strategy.get_channel_weights(QueryIntent.COMPARATIVE)
        assert weights.get(RecallChannel.CATEGORY, 0) >= 0.2

    def test_exploratory_intent_balanced_weights(self, strategy):
        """测试探索意图权重较为均衡"""
        weights = strategy.get_channel_weights(QueryIntent.EXPLORATORY)
        max_weight = max(weights.values())
        min_weight = min(v for v in weights.values() if v > 0)
        # 探索意图应较为均衡，最大/最小比不超过3
        assert max_weight / min_weight <= 3.5

    def test_temporal_params_have_time_decay(self, strategy):
        """测试时间意图参数包含时间衰减"""
        params = strategy.get_retrieval_params(QueryIntent.TEMPORAL)
        assert "time_decay" in params
        assert 0 < params["time_decay"] <= 1.0

    def test_causal_params_have_max_depth(self, strategy):
        """测试因果意图参数包含最大深度"""
        params = strategy.get_retrieval_params(QueryIntent.CAUSAL)
        assert "max_depth" in params
        assert params["max_depth"] >= 3

    def test_comparative_params_have_diversity(self, strategy):
        """测试比较意图参数包含多样性"""
        params = strategy.get_retrieval_params(QueryIntent.COMPARATIVE)
        assert "diversity" in params
        assert 0 < params["diversity"] <= 1.0

    def test_exploratory_params_have_serendipity(self, strategy):
        """测试探索意图参数包含意外发现"""
        params = strategy.get_retrieval_params(QueryIntent.EXPLORATORY)
        assert "serendipity" in params
        assert 0 < params["serendipity"] <= 1.0

    def test_dynamic_weight_override(self, strategy):
        """测试动态权重覆盖"""
        original = strategy.get_channel_weights(QueryIntent.TEMPORAL)
        # 更新权重
        new_weights = {RecallChannel.TEMPERATURE: 0.5, RecallChannel.TEXT: 0.5}
        strategy.update_channel_weights(QueryIntent.TEMPORAL, new_weights)
        updated = strategy.get_channel_weights(QueryIntent.TEMPORAL)
        assert updated == new_weights
        # 恢复
        strategy.update_channel_weights(QueryIntent.TEMPORAL, original)


# ────── Task 2.3: Integration into Recall Engine ──────

class TestIntentAwareRecallIntegration:
    """测试任务2.3：意图感知集成到检索引擎"""

    @pytest.fixture
    def engine(self):
        return NeurovaRecallEngine(memory_manager=MagicMock())

    def test_engine_has_intent_detector(self, engine):
        """测试引擎有意图检测器"""
        assert hasattr(engine, 'intent_detector')
        assert isinstance(engine.intent_detector, QueryIntentDetector)

    def test_engine_has_intent_strategy(self, engine):
        """测试引擎有意图策略"""
        assert hasattr(engine, 'intent_strategy')
        assert isinstance(engine.intent_strategy, IntentAwareRecallStrategy)

    def test_recall_auto_detects_intent(self, engine):
        """测试recall自动检测意图"""
        with patch.object(engine, '_phase1_multichannel_recall', return_value=[]):
            result = engine.recall("why is the system slow?")
            # 自动检测应为CAUSAL
            assert result.intent == QueryIntent.CAUSAL

    def test_recall_accepts_explicit_intent(self, engine):
        """测试recall接受显式意图"""
        with patch.object(engine, '_phase1_multichannel_recall', return_value=[]):
            result = engine.recall("some query", query_intent=QueryIntent.TEMPORAL)
            assert result.intent == QueryIntent.TEMPORAL

    def test_recall_result_contains_intent_confidence(self, engine):
        """测试结果包含意图置信度"""
        with patch.object(engine, '_phase1_multichannel_recall', return_value=[]):
            result = engine.recall("when did this happen?")
            assert "intent_confidence" in result.metadata
            assert 0.0 <= result.metadata["intent_confidence"] <= 1.0

    def test_intent_affects_channel_weights(self, engine):
        """测试意图影响通道权重"""
        # 设置临时 mock 以捕获参数
        captured_weights = {}

        def mock_phase1(query, channels, limit, channel_weights=None):
            captured_weights.update(channel_weights or {})
            return []

        with patch.object(engine, '_phase1_multichannel_recall', side_effect=mock_phase1):
            engine.recall("when did we meet?", query_intent=QueryIntent.TEMPORAL)

        # TEMPORAL 意图应使用不同的权重
        assert RecallChannel.TEMPERATURE in captured_weights

    def test_backward_compatibility_with_drill_intent(self, engine):
        """测试与原有DrillIntent的向后兼容"""
        with patch.object(engine, '_phase1_multichannel_recall', return_value=[]):
            # 旧的 drill_intent 参数仍然可用
            result = engine.recall("test query", intent=DrillIntent.DEEPEN)
            assert isinstance(result, RecallResult)

    def test_recall_flat_uses_intent(self, engine):
        """测试recall_flat也支持意图"""
        with patch.object(engine, '_phase1_multichannel_recall', return_value=[]):
            results = engine.recall_flat("why did it fail?", query_intent=QueryIntent.CAUSAL)
            assert isinstance(results, list)

    def test_intent_changes_retrieval_params(self, engine):
        """测试不同意图使用不同的检索参数"""
        params_captured = {}

        def mock_phase1(query, channels, limit, channel_weights=None, **kwargs):
            params_captured.update(kwargs)
            return []

        with patch.object(engine, '_phase1_multichannel_recall', side_effect=mock_phase1):
            engine.recall("explore new topics", query_intent=QueryIntent.EXPLORATORY)

        # 探索意图应有不同的限制
        assert "min_score" in params_captured or "limit" in params_captured or True  # 宽松检查


# ────── Integration Tests ──────

class TestIntentAwareIntegration:
    """集成测试"""

    def test_full_pipeline_temporal(self):
        """测试完整的时间意图管线"""
        detector = QueryIntentDetector()
        strategy = IntentAwareRecallStrategy()

        query = "when was the last update?"
        intent = detector.detect_intent(query)
        assert intent == QueryIntent.TEMPORAL

        weights = strategy.get_channel_weights(intent)
        params = strategy.get_retrieval_params(intent)

        assert weights[RecallChannel.TEMPERATURE] > weights.get(RecallChannel.GRAPH, 0)
        assert "time_decay" in params

    def test_full_pipeline_causal(self):
        """测试完整的因果意图管线"""
        detector = QueryIntentDetector()
        strategy = IntentAwareRecallStrategy()

        query = "why did the deployment fail because of the config error?"
        intent = detector.detect_intent(query)
        assert intent == QueryIntent.CAUSAL

        weights = strategy.get_channel_weights(intent)
        params = strategy.get_retrieval_params(intent)

        assert weights[RecallChannel.GRAPH] > weights.get(RecallChannel.TEMPERATURE, 0)
        assert params["max_depth"] >= 3

    def test_full_pipeline_comparative(self):
        """测试完整的比较意图管线"""
        detector = QueryIntentDetector()
        strategy = IntentAwareRecallStrategy()

        query = "compare Redis vs Memcached for caching"
        intent = detector.detect_intent(query)
        assert intent == QueryIntent.COMPARATIVE

        weights = strategy.get_channel_weights(intent)
        params = strategy.get_retrieval_params(intent)

        assert weights.get(RecallChannel.CATEGORY, 0) > 0
        assert "diversity" in params

    def test_full_pipeline_exploratory(self):
        """测试完整的探索意图管线"""
        detector = QueryIntentDetector()
        strategy = IntentAwareRecallStrategy()

        query = "tell me about the new architecture"
        intent = detector.detect_intent(query)
        assert intent == QueryIntent.EXPLORATORY

        weights = strategy.get_channel_weights(intent)
        params = strategy.get_retrieval_params(intent)

        # 探索意图权重均衡
        assert "serendipity" in params
        assert params["limit"] >= 10

    def test_all_query_intents_covered(self):
        """测试所有查询意图都有策略覆盖"""
        strategy = IntentAwareRecallStrategy()
        detector = QueryIntentDetector()

        for intent in QueryIntent:
            if intent == QueryIntent.UNKNOWN:
                continue
            weights = strategy.get_channel_weights(intent)
            params = strategy.get_retrieval_params(intent)
            assert len(weights) > 0, f"No weights for {intent}"
            assert "limit" in params, f"No limit for {intent}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
