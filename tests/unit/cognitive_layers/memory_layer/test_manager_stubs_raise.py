"""阶段10 已完成: 所有 72 个 stub 方法已委托到 modules/ 下的真实模块

本文件原用于验证 stub 方法抛出 NotImplementedError（阶段1 RED）。
阶段10 GREEN 完成后，所有 stub 已委托，原测试不再适用。

委托验证请见: test_manager_full_delegation.py
EKI/Sleep 委托验证请见: test_manager_eki_sleep_delegation.py

保留下列真实实现验证测试，确保核心功能未被破坏。
"""
from __future__ import annotations

import os
import sys

import pytest

# 确保能导入 neurova
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..")))

from neurova.cognitive_layers.memory_layer.manager import MemoryManager


@pytest.fixture
def manager(tmp_path):
    """提供独立的 MemoryManager 实例"""
    db_path = str(tmp_path / "test_stubs.db")
    return MemoryManager(db_path=db_path, agent_id="test", user_id="test")


# ────── 已委托方法（原 stub 测试已移除，见 test_manager_full_delegation.py） ──────
#
# 以下 72 个方法已全部委托到 modules/ 下的真实模块，不再抛出 NotImplementedError：
#
#   - Buffer (1): flush_all_pending_updates → BufferModule
#   - Classification (1): classify_memory → ClassifierModule
#   - Emotion (11): get_emotion_summary 等 → EmotionModule
#   - SelfModel (4): get_self_model 等 → SelfModelModule
#   - MetaCognition (13): meta_monitor 等 → MetaCognitionModule
#   - TKG (6): tkg_add_fact 等 → TKGModule
#   - WorkingMemory (8): wm_add_turn 等 → WorkingMemoryModule
#   - SelfManager (12): self_get_commands 等 → SelfManagerModule
#   - AutoUpdate (2): start_auto_update/stop_auto_update → AutoContextModule
#   - Conflict (5): get_traces_by_trigger 等 → ConflictModule
#   - Relation (4+2): add_relation 等 + relate/recall_graph → RelationModule
#   - Explainability (2): get_explanation_chain 等 → ExplainabilityModule
#   - ForgettingRecovery (1): get_recovery_history → ForgettingRecoveryModule
#   - EKI (10): eki_process_task 等 → EKIModule（阶段2委托）
#   - Sleep (4): run_light_sleep_cycle 等 → SleepModule（阶段2委托）


# ────── 真实实现验证 (确保核心功能未被破坏) ──────


class TestRealMethodsStillWork:
    """验证已实现的核心方法仍正常工作 (非 stub)"""

    def test_remember_works(self, manager):
        mem_id = manager.remember("test content")
        assert mem_id is not None

    def test_recall_works(self, manager):
        manager.remember("test content for recall")
        results = manager.recall("test")
        assert isinstance(results, list)

    def test_search_memories_works(self, manager):
        manager.remember("searchable content")
        results = manager.search_memories("searchable")
        assert isinstance(results, list)

    def test_explain_memory_works(self, manager):
        """explain_memory 是真实实现, 不应抛出异常"""
        mem_id = manager.remember("explainable content")
        result = manager.explain_memory(mem_id)
        assert result["memory_id"] == mem_id

    def test_analyze_emotion_works(self, manager):
        """analyze_emotion 委托到 EmotionModule, 不应抛出异常"""
        result = manager.analyze_emotion("happy text")
        assert isinstance(result, dict)

    def test_archive_memory_works(self, manager):
        """archive_memory 是真实实现"""
        mem_id = manager.remember("to archive")
        assert manager.archive_memory(mem_id) is True

    def test_update_memory_temperature_works(self, manager):
        """update_memory_temperature 是真实实现"""
        mem_id = manager.remember("temperature test")
        assert manager.update_memory_temperature(mem_id) is True

    def test_run_decay_cycle_works(self, manager):
        """run_decay_cycle 是真实实现"""
        manager.remember("decay test")
        count = manager.run_decay_cycle()
        assert isinstance(count, int)
