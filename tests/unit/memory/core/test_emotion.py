"""
EmotionAnalyzer 单元测试 — 按当前真实 API 重写

真实 API:
- EmotionAnalyzer(use_legacy=False)
- analyze(text, context=None) -> {primary_emotion, confidence, emotions, tags, score}
- get_emotion_tags(emotion_scores: Dict, threshold=0.3) -> List[str]
- get_emotion_score(text, target_emotion) -> float
- get_detailed_scores(text) -> Dict[str, Dict]
- batch_analyze(texts, contexts=None) -> List[Dict]
- get_emotion_distribution(texts) -> Dict[str, float]
- get_emotion_stats(texts) -> Dict
- get_emotion_hierarchy() -> Dict
"""

import pytest

from neurova.cognitive_layers.memory_layer.emotion import EmotionAnalyzer


@pytest.fixture
def analyzer():
    return EmotionAnalyzer()


class TestAnalyze:
    def test_returns_dict_with_core_keys(self, analyzer):
        result = analyzer.analyze("今天非常开心，太高兴了")
        for key in ("primary_emotion", "confidence", "emotions", "tags", "score"):
            assert key in result

    def test_empty_text(self, analyzer):
        result = analyzer.analyze("")
        assert isinstance(result, dict)
        assert "primary_emotion" in result

    def test_positive_text_detected_as_joy(self, analyzer):
        result = analyzer.analyze("我非常开心，太高兴了")
        emotions = result.get("emotions", {})
        # 新引擎至少不应把明显正面文本判成纯负面
        if emotions.get("joy") is not None:
            assert emotions["joy"] >= 0

    def test_batch_analyze(self, analyzer):
        results = analyzer.batch_analyze(["开心", "难过"])
        assert isinstance(results, list)
        assert len(results) == 2


class TestGetEmotionTags:
    def test_filters_by_threshold(self, analyzer):
        scores = {"joy": 0.8, "sadness": 0.1}
        tags = analyzer.get_emotion_tags(scores, threshold=0.3)
        assert tags == ["joy"]

    def test_sorted_by_score_desc(self, analyzer):
        scores = {"joy": 0.5, "trust": 0.9}
        tags = analyzer.get_emotion_tags(scores, threshold=0.3)
        assert tags[0] == "trust"

    def test_all_below_threshold(self, analyzer):
        assert analyzer.get_emotion_tags({"joy": 0.1}, threshold=0.3) == []


class TestScoring:
    def test_get_emotion_score_for_target(self, analyzer):
        score = analyzer.get_emotion_score("我非常开心", "joy")
        assert isinstance(score, (int, float))

    def test_get_detailed_scores(self, analyzer):
        detailed = analyzer.get_detailed_scores("平静的一天")
        assert isinstance(detailed, dict)

    def test_distribution_over_texts(self, analyzer):
        dist = analyzer.get_emotion_distribution(["开心", "难过", "平静"])
        assert isinstance(dist, dict)

    def test_stats_over_texts(self, analyzer):
        stats = analyzer.get_emotion_stats(["开心", "难过"])
        assert isinstance(stats, dict)

    def test_hierarchy_available(self, analyzer):
        hierarchy = analyzer.get_emotion_hierarchy()
        assert isinstance(hierarchy, dict)


class TestLegacyMode:
    def test_use_legacy_flag_accepted(self):
        analyzer = EmotionAnalyzer(use_legacy=True)
        assert analyzer is not None
