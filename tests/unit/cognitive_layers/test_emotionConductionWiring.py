# -*- coding: utf-8 -*-
"""D5 接线做实判据（2026-11-14 死码退役批 B-3）。

EmotionConductionModule（记忆间 BFS 情感传导/关联图/极性检索）此前是
manager._emotion_conduction 恒 None 死槽位后的零消费模块。本档钉住接线后的闭环：
- manager 懒装配 + 委托面（set/get/add_association/conduct/极性检索）
- 关系面 add_relation 自动回流为传导关联图边（关联图数据来源做实）
- 快照持久化：同库路径的新 manager 恢复情感状态（持久化做实）
- 记忆硬删同步摘除传导图节点
"""
from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.modules.emotion_conduction_module import (
    EmotionConductionModule,
)

pytestmark = pytest.mark.timeout(120)


def testManagerLazilyWiresConductionModule(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    module = manager._ensure_emotion_conduction()
    assert isinstance(module, EmotionConductionModule)


def testSetGetEmotionViaManager(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    manager.set_memory_emotion("m1", 0.9)
    assert manager.get_memory_emotion("m1") == pytest.approx(0.9)


def testRelationFeedsAssociationAndConductionReachesNeighbor(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    # 关系面写边 → 自动回流为传导关联
    manager.add_relation(source_id="ma", target_id="mb", relation_type="association", strength=0.8)
    affected = manager.conduct_memory_emotion("ma", 0.9)
    assert "mb" in affected
    assert affected["mb"] > 0
    assert manager.get_memory_emotion("mb") > 0


def testForgetHardDeleteRemovesConductionNode(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    mid = manager.remember("将被硬删的记忆", category="fact", importance=0.5)
    manager.set_memory_emotion(mid, 0.9)
    assert manager.get_memory_emotion(mid) == pytest.approx(0.9)

    assert manager.forget(mid, soft=False, agent_wide=True) is True
    assert manager.get_memory_emotion(mid) == 0.0


def testSnapshotPersistsAcrossManagers(tmp_path):
    db = str(tmp_path / "mem.db")
    first = MemoryManager(db_path=db, agent_id="agent_a")
    first.set_memory_emotion("keep_me", -0.7)
    assert first.flush_emotion_conduction() is True

    second = MemoryManager(db_path=db, agent_id="agent_a")
    assert second.get_memory_emotion("keep_me") == pytest.approx(-0.7)


def testPolarityRetrieval(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    manager.set_memory_emotion("pos", 0.9)
    manager.set_memory_emotion("neg", -0.9)
    manager.set_memory_emotion("mid", 0.0)
    assert "pos" in manager.getMemoryIdsByEmotionPolarity("positive")
    assert "neg" in manager.getMemoryIdsByEmotionPolarity("negative")
    assert "mid" in manager.getMemoryIdsByEmotionPolarity("neutral")
