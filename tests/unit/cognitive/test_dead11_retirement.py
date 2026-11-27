"""DEAD-11：时间感知与成长分析旧入口退役，在役读面保持可用。"""

import pytest

from neurova.cognitive_layers.emotion_context_layer.time_awareness import TimeAwareness
from neurova.cognitive_layers.growth_layer.analyzer import GrowthAnalyzer, GrowthDimension


@pytest.mark.parametrize(
    "attribute",
    [
        "analyze_patterns",
        "predict_events",
        "get_seasonal_preferences",
        "_get_recent_memories",
        "_analyze_daily_habits",
        "_analyze_periodic_events",
        "_analyze_time_distribution",
        "_analyze_monthly_trends",
        "_analyze_activity_patterns",
        "_predict_periodic_events",
        "_predict_seasonal_events",
        "_predict_habit_events",
        "_predict_category_events",
        "_calculate_date_confidence",
        "_deduplicate_predictions",
    ],
)
def test_timeAwarenessDeadEntryPointsAreRetired(attribute):
    assert not hasattr(TimeAwareness, attribute), f"旧入口 TimeAwareness.{attribute} 不得复活"


def test_timeContextHintRemainsLive():
    hint = TimeAwareness().get_time_context_hint()

    assert "季节:" in hint


@pytest.mark.parametrize(
    "attribute",
    [
        "get_growth_report",
        "_calculate_trend",
        "identify_improvement_areas",
        "suggest_learning_path",
        "_get_suggested_activities",
    ],
)
def test_growthAnalyzerDeadEntryPointsAreRetired(attribute):
    assert not hasattr(GrowthAnalyzer, attribute), f"旧入口 GrowthAnalyzer.{attribute} 不得复活"


def test_growthStatusRemainsLiveAfterReportRetirement():
    analyzer = GrowthAnalyzer(agent_id="dead11-status")
    analyzer.record_learning(
        dimension=GrowthDimension.LEARNING,
        score=80.0,
        learning_rate=1.0,
    )

    status = analyzer.get_growth_status(GrowthDimension.LEARNING)

    assert status["dimension"] == "learning"
    assert status["score"] == 80.0
    assert status["status"] == "expert"
    assert status["record_count"] == 1
