# -*- coding: utf-8 -*-
"""情绪变化时间轴聚合测试（2026-09-19）。

契约：
- X 轴粒度由 range 推导：24h→小时(24 桶)、7d→天(7)、30d→天(30)、90d→周(13)；
- Y 轴 = 桶内 Σ(valence×intensity)/Σ(intensity)，带符号（正=积极情绪，负=消极情绪）；
- 无情绪事件的桶为 None（前端画断点），不是 0——0 会被读成"中性"，抹掉"没发生情绪"；
- 每桶给一个峰值事件（|valence|×intensity 最大那条）作为"触发情绪变化的事件"，
  含其 content 摘要，供悬停显示；
- 只有 emotion_module 的标注行才算情绪事件：memories.emotion 列的 DDL 默认值就是
  'neutral'，"没分析过"与"判为中性"不可区分，计入会让未标注记忆把曲线拽向 0。
"""
from datetime import datetime, timedelta, timezone

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
    EmotionState,
    EmotionType,
)


@pytest.fixture()
def manager(tmp_path):
    mgr = MemoryManager(
        db_path=str(tmp_path / "emotion_timeline.db"),
        agent_id="tl_agent",
        user_id="tl_user",
    )
    yield mgr
    mgr.close()


def _seed(mgr, content, emotion, *, valence=None, intensity=None, minutes_ago=0):
    """写入一条带情绪的记忆；valence 为 None 时只留 emotion 列、不建标注行。"""
    memory_id = mgr.remember(content, emotion=emotion, auto_analyze_emotion=False)
    mgr._memories[memory_id].created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    if valence is not None:
        mgr._emotion_module.set_emotion(
            memory_id,
            EmotionState(
                primary_emotion=EmotionType(emotion),
                intensity=intensity,
                valence=valence,
                arousal=0.5,
            ),
        )
    return memory_id


@pytest.mark.parametrize(
    "range_key,expected_buckets,unit",
    [("24h", 24, "hour"), ("7d", 7, "day"), ("30d", 30, "day"), ("90d", 13, "week")],
)
def test_bucket_count_and_unit_per_range(manager, range_key, expected_buckets, unit):
    out = manager.get_emotion_timeline(range_key)

    assert out["range"] == range_key
    assert out["bucket"] == unit
    points = out["points"]
    assert len(points) == expected_buckets
    labels = [p["label"] for p in points]
    assert len(set(labels)) == expected_buckets, "桶标签不得重复（前端 X 轴按 label 定位）"
    assert all(p["ts"] for p in points)


def test_bucket_valence_is_intensity_weighted_mean(manager):
    # 同一桶两条：+0.8×0.2 与 -0.7×0.8 → (0.16 - 0.56) / 1.0 = -0.4
    _seed(manager, "收到用户好评", "joy", valence=0.8, intensity=0.2)
    _seed(manager, "网页搜索失败", "anger", valence=-0.7, intensity=0.8)

    point = manager.get_emotion_timeline("24h")["points"][-1]

    assert point["valence"] == pytest.approx(-0.4)
    assert point["count"] == 2


def test_bucket_without_emotion_event_is_none_not_zero(manager):
    _seed(manager, "三天前的开心", "joy", valence=0.8, intensity=0.5, minutes_ago=60 * 24 * 3)

    points = manager.get_emotion_timeline("24h")["points"]

    assert all(p["valence"] is None for p in points)
    assert all(p["count"] == 0 for p in points)


def test_peak_event_is_the_strongest_in_bucket(manager):
    _seed(manager, "有点意外", "surprise", valence=0.3, intensity=0.1)
    _seed(manager, "连续三次搜索都失败", "anger", valence=-0.7, intensity=0.9)

    point = manager.get_emotion_timeline("24h")["points"][-1]

    assert point["peak_emotion"] == "anger"
    assert point["excerpt"] == "连续三次搜索都失败"
    assert point["peak_intensity"] == pytest.approx(0.9)


def test_memory_without_annotation_row_is_not_an_emotion_event(manager):
    """`memories.emotion` 列的 DDL 默认值就是 'neutral'，因此"列值为 neutral"
    既可能是"分析过且判为中性"，也可能是"从没做过情绪分析"——两者不可区分。
    把它当效价样本计入均值，等于让未标注记忆把曲线拽向 0。
    标注表（emotion_module）是唯一权威源：没有标注行就不算情绪事件。"""
    _seed(manager, "重要文件被误删了", "anger")  # 只写 emotion 列，无标注行

    points = manager.get_emotion_timeline("24h")["points"]

    assert all(p["valence"] is None for p in points)
    assert all(p["count"] == 0 for p in points)
    assert all(p["peak_emotion"] is None for p in points)


def test_memories_outside_window_are_excluded(manager):
    _seed(manager, "一年前的愤怒", "anger", valence=-0.7, intensity=0.9, minutes_ago=60 * 24 * 400)

    points = manager.get_emotion_timeline("7d")["points"]

    assert all(p["valence"] is None for p in points)


def test_excerpt_is_truncated_for_long_content(manager):
    _seed(manager, "长" * 400, "anger", valence=-0.7, intensity=0.9)

    point = manager.get_emotion_timeline("24h")["points"][-1]

    assert len(point["excerpt"]) <= 90
    assert point["excerpt"].endswith("…")


def test_unknown_range_falls_back_to_default_window(manager):
    out = manager.get_emotion_timeline("nonsense")

    assert out["range"] == "7d"
    assert len(out["points"]) == 7
