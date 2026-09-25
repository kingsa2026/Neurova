# -*- coding: utf-8 -*-
"""情绪效价单一真源测试（2026-09-19，情绪变化时间轴的前置）。

背景：带符号效价表被手抄成两份且都不完备——
`emotion_module._VALENCE_MAP`（7 键）与 `manager.update_emotional_state` 内的
`valence_map`（6 键），二者都缺 trust / anticipation，`.get(primary, 0.0)` 把它们
静默折成"中性 0.0"；同方法内的 `emotion_map` 只列 6 个类型，连 primary 都识别不出。
时间轴的 Y 轴直接消费效价，这类静默折零会把积极情绪画成中性。

契约：9 类持久化情绪各有一个带符号效价，写链（语义/规则/manager）与读链共用一份常量。
"""
from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.modules.emotion_module import (
    EMOTION_VALENCE,
    EmotionModule,
    EmotionType,
)

# 自我决定论口径下的正向补值：信任温和偏正，期待弱于惊喜之上、低于快乐
_EXPECTED_MIN = {
    "joy": 0.8, "trust": 0.6, "anticipation": 0.4, "surprise": 0.3,
    "neutral": 0.0,
    "fear": -0.5, "sadness": -0.6, "anger": -0.7, "disgust": -0.9,
}


def test_valence_table_covers_every_persisted_emotion_type():
    assert set(EMOTION_VALENCE) == {e.value for e in EmotionType}


@pytest.mark.parametrize("emotion", sorted(_EXPECTED_MIN))
def test_valence_value_matches_signed_scale(emotion):
    assert EMOTION_VALENCE[emotion] == pytest.approx(_EXPECTED_MIN[emotion])
    assert -1.0 <= EMOTION_VALENCE[emotion] <= 1.0


def test_semantic_path_gives_trust_a_positive_valence():
    """修复前：_VALENCE_MAP 无 trust 键 → 落到默认 0.0（画成中性）"""
    classifier = MagicMock()
    classifier.analyze.return_value = ("trust", 0.6)
    module = EmotionModule()
    module.set_semantic_classifier(classifier)

    state = module.analyze_text_emotion("我相信你的判断")

    assert state.primary_emotion is EmotionType.TRUST
    assert state.valence > 0.0


def test_emotion_module_map_is_the_shared_constant_not_a_copy():
    assert EmotionModule._VALENCE_MAP is EMOTION_VALENCE


@pytest.mark.parametrize(
    "emotion,expected_sign",
    [("trust", 1), ("anticipation", 1), ("disgust", -1)],
)
def test_manager_state_update_recognizes_all_persisted_types(tmp_path, emotion, expected_sign):
    """修复前：manager 内手抄的 emotion_map 只列 6 类，trust/anticipation/disgust
    连 primary 都识别不出，效价表补全也走不到这条链。"""
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    manager = MemoryManager(
        db_path=str(tmp_path / "emotion_valence.db"),
        agent_id="test_agent",
        user_id="test_user",
    )
    try:
        manager.update_emotional_state({emotion: 0.6})
        state = manager._emotion_module.get_emotion("_current_state")
        assert state is not None
        assert state.primary_emotion.value == emotion
        assert state.valence * expected_sign > 0.0
    finally:
        manager.close()
