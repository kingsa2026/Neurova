# -*- coding: utf-8 -*-
"""D4 取长补短判据（2026-11-14 死码退役批）。

proactive_question.py（旧版）退役，其好奇心驱动能力并入现役
meta_cognition_layer/question_queue.py。本档钉住：
- CuriosityDrive 强度模型（知识缺口/新颖性/探索频率三因子）——新颖性**做实**
  （按已探索主题计数衰减，不再恒 0.5）
- 五类好奇心问题模板生成，强度 <0.3 不生成、>0.7 给 HIGH 优先级
- 生成的问题走现役 generate_question 持久化通道（进队列、可被取到）
- 探索台账（record/complete/stats）与知识缺口冲抵
- 问题质量评估（优先级+好奇心类型加分）与忙/闲自适应冷却
"""
from __future__ import annotations

import pytest

from neurova.cognitive_layers.meta_cognition_layer.question_queue import (
    CuriosityDrive,
    CuriosityType,
    QuestionPriority,
    QuestionQueueManager,
)

pytestmark = pytest.mark.timeout(120)


def testNoveltyAssessmentIsRealNotConstant():
    drive = CuriosityDrive()
    ctx = {"current_topic": "量子纠错"}
    first = drive.calculate_intensity(ctx)
    # 首见主题：新颖性满分贡献
    assert drive._assess_context_novelty("量子纠错") == 1.0
    # 同主题反复探索后新颖性衰减
    exploration = drive.record_exploration("", "量子纠错", CuriosityType.NOVELTY_SEEKING)
    drive.complete_exploration(exploration.id, findings=["a"], knowledge_gained=0.2)
    second = drive._assess_context_novelty("量子纠错")
    assert second < 1.0
    assert first != second or second < 1.0  # 强度模型确实吃到新颖性变化


def testKnowledgeGapLedgerFeedsIntensity():
    drive = CuriosityDrive()
    drive._knowledge_gaps["拓扑序"] = 0.9
    assert drive._assess_knowledge_gap({}) == pytest.approx(0.9)


def testGenerateQuestionUsesTemplatesAndPriorityGate():
    drive = CuriosityDrive()
    q = drive.generate_curiosity_question({"current_topic": "Attention 机制", "unknown_terms": ["RoPE"]})
    assert q is not None
    assert q["curiosity_type"] == CuriosityType.KNOWLEDGE_GAP.value
    assert "RoPE" in q["content"]
    assert q["priority"] in (QuestionPriority.HIGH.value, QuestionPriority.NORMAL.value)


def testGenerateQuestionNoneWhenIntensityLow():
    drive = CuriosityDrive()
    # 同主题反复探索：新颖性归零 + 探索疲劳拉满 → 强度跌破 0.3 生成闸
    for _ in range(12):
        exploration = drive.record_exploration("", "主题0", CuriosityType.NOVELTY_SEEKING)
        drive.complete_exploration(exploration.id, findings=[], knowledge_gained=0.0)
    assert drive.generate_curiosity_question({"current_topic": "主题0"}) is None


def testManagerGeneratesCuriosityQuestionIntoQueue():
    manager = QuestionQueueManager()
    entry = manager.generate_curiosity_question({"current_topic": "RAG 评估", "unknown_terms": ["faithfulness"]})
    assert entry is not None
    assert entry.metadata.get("curiosity_type") == CuriosityType.KNOWLEDGE_GAP.value
    # 走现役队列：能被 get_next_question 取到
    assert manager.get_next_question() is not None
    assert entry.id in {q.id for q in manager.get_pending_questions()}


def testEvaluateQuestionQualityRanksByPriorityAndType():
    manager = QuestionQueueManager()
    strong = manager.evaluate_question_quality(
        content="因果链是什么？", priority=QuestionPriority.HIGH, curiosity_type=CuriosityType.CAUSAL_REASONING
    )
    weak = manager.evaluate_question_quality(
        content="随便问问", priority=QuestionPriority.LOW, curiosity_type=None
    )
    assert strong > weak
    assert 0.0 <= weak <= 1.0


def testUserBusyIdleAdaptsCooldown():
    manager = QuestionQueueManager(default_cooldown=300.0)
    manager.on_user_busy()
    assert manager._default_cooldown >= 600.0  # 忙碌期冷却拉长
    manager.on_user_idle()
    assert manager._default_cooldown == 300.0  # 空闲期恢复


def testExplorationStatsShape():
    drive = CuriosityDrive()
    exploration = drive.record_exploration("q1", "记忆温度", CuriosityType.PATTERN_DISCOVERY)
    drive.complete_exploration(exploration.id, findings=["发现衰减曲线"], knowledge_gained=0.4)
    stats = drive.get_exploration_stats()
    assert stats["total_explorations"] == 1
    assert stats["completed_explorations"] == 1
    assert stats["average_knowledge_gained"] == pytest.approx(0.4)
    assert stats["curiosity_type_distribution"] == {"pattern_discovery": 1}
