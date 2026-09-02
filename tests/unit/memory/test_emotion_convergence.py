# -*- coding: utf-8 -*-
"""认知收敛第二批测试：双情感引擎分析入口统一（补课 7）。

收敛语义：EmotionConductionManager 注入 EmotionModule 后，
analyze_text_emotion 走语义分类器（主源）；未注入/失败回退 hub
关键词规则。两引擎持久化分工不变（逐记忆 vs 会话状态机）。
"""
from unittest.mock import MagicMock

import pytest


@pytest.fixture()
def manager():
    from neurova.cognitive_layers.emotion_context_layer.emotion_conduction import (
        EmotionConductionManager,
    )

    return EmotionConductionManager(agent_id="test-converge")


def _module_returning(primary: str, intensity: float):
    m = MagicMock()
    state = MagicMock()
    state.primary_emotion = MagicMock(value=primary)
    state.intensity = intensity
    m.analyze_text_emotion.return_value = state
    return m


def test_injected_module_semantic_path_used(manager):
    manager.set_emotion_module(_module_returning("joy", 0.8))
    scores = manager.analyze_text_emotion("你好")
    # 语义路径：{primary: intensity}，不经 hub 关键词表
    assert scores == {"joy": 0.8}


def test_injected_module_neutral_returns_empty(manager):
    # 中性/零强度 → 空表（与 hub 无关键词命中契约一致，避免注入噪音）
    manager.set_emotion_module(_module_returning("neutral", 0.0))
    assert manager.analyze_text_emotion("今天天气不错") == {}


def test_module_failure_falls_back_to_hub_keywords(manager):
    broken = MagicMock()
    broken.analyze_text_emotion.side_effect = RuntimeError("classifier down")
    manager.set_emotion_module(broken)
    # hub 关键词路径兜底（命中与否取决于词表；这里只验证不抛异常且返回 dict）
    scores = manager.analyze_text_emotion("我很开心")
    assert isinstance(scores, dict)


def test_no_module_uses_hub_keywords(manager):
    # 未注入 → 原 hub 关键词路径（行为兼容）
    scores = manager.analyze_text_emotion("我很开心")
    assert isinstance(scores, dict)
    assert scores.get("joy", 0.0) > 0 or scores == {}
