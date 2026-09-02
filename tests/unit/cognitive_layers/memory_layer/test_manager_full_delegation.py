"""阶段10 RED: 验证 manager.py 72 个 stub 全量委托到真实模块

TDD 红灯阶段: 测试预期 72 个 stub 方法委托到对应 modules/ 下的真实模块，
而非抛出 NotImplementedError。

覆盖模块（按委托分组）:
  - Buffer (1): flush_all_pending_updates → BufferModule
  - Classification (1): classify_memory → ClassifierModule
  - Emotion (11): get_emotion_summary 等 → EmotionModule（已初始化）
  - SelfModel (4): get_self_model 等 → SelfModelModule
  - MetaCognition (13): meta_monitor 等 → MetaCognitionModule
  - TKG (6): tkg_add_fact 等 → TKGModule
  - WorkingMemory (8): wm_add_turn 等 → WorkingMemoryModule
  - SelfManager (12): self_get_commands 等 → SelfManagerModule
  - AutoUpdate (2): start_auto_update/stop_auto_update → AutoContextModule
  - Conflict (5): get_traces_by_trigger 等 → ConflictModule
  - Relation (4): add_relation 等 → RelationModule
  - Explainability (2): get_explanation_chain 等 → ExplainabilityModule
  - ForgettingRecovery (1): get_recovery_history → ForgettingRecoveryModule
  - Relation extra (2): relate/recall_graph → RelationModule
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
    db_path = str(tmp_path / "test_full_delegation.db")
    return MemoryManager(db_path=db_path, agent_id="test", user_id="test")


# ────── Buffer 委托测试 ──────


class TestBufferDelegation:
    """验证 Buffer stub 委托到 BufferModule"""

    def test_flush_all_pending_updates_no_longer_raises(self, manager):
        """flush_all_pending_updates 不应抛出 NotImplementedError"""
        try:
            manager.flush_all_pending_updates()
        except NotImplementedError:
            pytest.fail("flush_all_pending_updates should delegate to BufferModule, not raise NotImplementedError")

    def test_flush_all_pending_updates_returns_int(self, manager):
        """flush_all_pending_updates 应返回 int（刷入条目数）"""
        result = manager.flush_all_pending_updates()
        assert isinstance(result, int)

    def test_buffer_module_initialized_after_call(self, manager):
        """调用后 _buffer_module 应被初始化"""
        manager.flush_all_pending_updates()
        assert manager._buffer_module is not None


# ────── Classification 委托测试 ──────


class TestClassificationDelegation:
    """验证 Classification stub 委托到 ClassifierModule"""

    def test_classify_memory_no_longer_raises(self, manager):
        """classify_memory 不应抛出 NotImplementedError"""
        try:
            manager.classify_memory("test content")
        except NotImplementedError:
            pytest.fail("classify_memory should delegate to ClassifierModule, not raise NotImplementedError")

    def test_classify_memory_returns_dict(self, manager):
        """classify_memory 应返回 dict（含分类信息）"""
        result = manager.classify_memory("test content about work")
        assert isinstance(result, dict)

    def test_classifier_module_initialized_after_call(self, manager):
        """调用后 _classifier_module 应被初始化"""
        manager.classify_memory("test content")
        assert manager._classifier_module is not None


# ────── Emotion 委托测试 ──────


class TestEmotionDelegation:
    """验证 Emotion stub 委托到 EmotionModule（已初始化为 self._emotion_module）"""

    def test_get_emotion_summary_no_longer_raises(self, manager):
        try:
            manager.get_emotion_summary()
        except NotImplementedError:
            pytest.fail("get_emotion_summary should delegate to EmotionModule")

    def test_get_emotion_summary_returns_dict(self, manager):
        result = manager.get_emotion_summary()
        assert isinstance(result, dict)

    def test_get_emotion_distribution_no_longer_raises(self, manager):
        try:
            manager.get_emotion_distribution()
        except NotImplementedError:
            pytest.fail("get_emotion_distribution should delegate to EmotionModule")

    def test_get_emotion_distribution_returns_dict(self, manager):
        result = manager.get_emotion_distribution()
        assert isinstance(result, dict)

    def test_update_emotional_state_no_longer_raises(self, manager):
        try:
            manager.update_emotional_state("happy text")
        except NotImplementedError:
            pytest.fail("update_emotional_state should delegate to EmotionModule")

    def test_update_emotional_state_returns_dict(self, manager):
        result = manager.update_emotional_state("happy text")
        assert isinstance(result, dict)

    def test_get_emotional_state_no_longer_raises(self, manager):
        try:
            manager.get_emotional_state()
        except NotImplementedError:
            pytest.fail("get_emotional_state should delegate to EmotionModule")

    def test_get_emotional_state_returns_dict(self, manager):
        result = manager.get_emotional_state()
        assert isinstance(result, dict)

    def test_get_dominant_emotion_no_longer_raises(self, manager):
        try:
            manager.get_dominant_emotion()
        except NotImplementedError:
            pytest.fail("get_dominant_emotion should delegate to EmotionModule")

    def test_get_dominant_emotion_returns_str(self, manager):
        result = manager.get_dominant_emotion()
        # P-2 契约：返回 (emotion_str, score_float) tuple
        assert isinstance(result, tuple) and len(result) == 2
        assert isinstance(result[0], str)
        assert isinstance(result[1], float)

    def test_get_emotion_bias_no_longer_raises(self, manager):
        try:
            manager.get_emotion_bias()
        except NotImplementedError:
            pytest.fail("get_emotion_bias should delegate to EmotionModule")

    def test_get_emotion_bias_returns_float(self, manager):
        result = manager.get_emotion_bias()
        assert isinstance(result, (int, float))

    def test_apply_emotion_to_temperature_no_longer_raises(self, manager):
        try:
            manager.apply_emotion_to_temperature(0.7)
        except NotImplementedError:
            pytest.fail("apply_emotion_to_temperature should delegate to EmotionModule")

    def test_apply_emotion_to_temperature_returns_float(self, manager):
        result = manager.apply_emotion_to_temperature(0.7)
        assert isinstance(result, (int, float))

    def test_apply_emotion_to_style_no_longer_raises(self, manager):
        try:
            manager.apply_emotion_to_style("text")
        except NotImplementedError:
            pytest.fail("apply_emotion_to_style should delegate to EmotionModule")

    def test_apply_emotion_to_style_returns_str(self, manager):
        result = manager.apply_emotion_to_style("text")
        assert isinstance(result, str)

    def test_get_emotion_history_no_longer_raises(self, manager):
        try:
            manager.get_emotion_history()
        except NotImplementedError:
            pytest.fail("get_emotion_history should delegate to EmotionModule")

    def test_get_emotion_history_returns_list(self, manager):
        result = manager.get_emotion_history()
        assert isinstance(result, list)

    def test_reset_emotion_to_baseline_no_longer_raises(self, manager):
        try:
            manager.reset_emotion_to_baseline()
        except NotImplementedError:
            pytest.fail("reset_emotion_to_baseline should delegate to EmotionModule")

    def test_merge_with_user_emotion_no_longer_raises(self, manager):
        try:
            manager.merge_with_user_emotion("user text")
        except NotImplementedError:
            pytest.fail("merge_with_user_emotion should delegate to EmotionModule")

    def test_merge_with_user_emotion_returns_dict(self, manager):
        result = manager.merge_with_user_emotion("user text")
        assert isinstance(result, dict)


# ────── SelfModel 委托测试 ──────


class TestSelfModelDelegation:
    """验证 SelfModel stub 委托到 SelfModelModule"""

    def test_get_self_model_no_longer_raises(self, manager):
        try:
            manager.get_self_model()
        except NotImplementedError:
            pytest.fail("get_self_model should delegate to SelfModelModule")

    def test_get_self_model_returns_dict(self, manager):
        result = manager.get_self_model()
        assert isinstance(result, dict)

    def test_update_self_model_no_longer_raises(self, manager):
        try:
            manager.update_self_model()
        except NotImplementedError:
            pytest.fail("update_self_model should delegate to SelfModelModule")

    def test_update_self_model_returns_bool(self, manager):
        result = manager.update_self_model()
        assert isinstance(result, bool)

    def test_update_user_profile_no_longer_raises(self, manager):
        try:
            manager.update_user_profile()
        except NotImplementedError:
            pytest.fail("update_user_profile should delegate to SelfModelModule")

    def test_update_user_profile_returns_bool(self, manager):
        result = manager.update_user_profile()
        assert isinstance(result, bool)

    def test_get_user_profile_no_longer_raises(self, manager):
        try:
            manager.get_user_profile()
        except NotImplementedError:
            pytest.fail("get_user_profile should delegate to SelfModelModule")

    def test_get_user_profile_returns_dict(self, manager):
        result = manager.get_user_profile()
        assert isinstance(result, dict)

    def test_self_model_module_initialized_after_call(self, manager):
        manager.get_self_model()
        assert manager._self_model_module is not None


# ────── MetaCognition 委托测试 ──────


class TestMetaCognitionDelegation:
    """验证 MetaCognition stub 委托到 MetaCognitionModule"""

    def test_meta_monitor_no_longer_raises(self, manager):
        try:
            manager.meta_monitor()
        except NotImplementedError:
            pytest.fail("meta_monitor should delegate to MetaCognitionModule")

    def test_meta_monitor_returns_dict(self, manager):
        result = manager.meta_monitor()
        assert isinstance(result, dict)

    def test_meta_reflect_no_longer_raises(self, manager):
        try:
            manager.meta_reflect()
        except NotImplementedError:
            pytest.fail("meta_reflect should delegate to MetaCognitionModule")

    def test_meta_reflect_returns_dict(self, manager):
        result = manager.meta_reflect()
        assert isinstance(result, dict)

    def test_meta_optimize_no_longer_raises(self, manager):
        try:
            manager.meta_optimize()
        except NotImplementedError:
            pytest.fail("meta_optimize should delegate to MetaCognitionModule")

    def test_meta_optimize_returns_dict(self, manager):
        result = manager.meta_optimize()
        assert isinstance(result, dict)

    def test_meta_evolve_skills_no_longer_raises(self, manager):
        try:
            manager.meta_evolve_skills()
        except NotImplementedError:
            pytest.fail("meta_evolve_skills should delegate to MetaCognitionModule")

    def test_meta_evolve_skills_returns_dict(self, manager):
        result = manager.meta_evolve_skills()
        assert isinstance(result, dict)

    def test_meta_get_health_report_no_longer_raises(self, manager):
        try:
            manager.meta_get_health_report()
        except NotImplementedError:
            pytest.fail("meta_get_health_report should delegate to MetaCognitionModule")

    def test_meta_get_health_report_returns_dict(self, manager):
        result = manager.meta_get_health_report()
        assert isinstance(result, dict)

    def test_meta_get_reflection_report_no_longer_raises(self, manager):
        try:
            manager.meta_get_reflection_report()
        except NotImplementedError:
            pytest.fail("meta_get_reflection_report should delegate to MetaCognitionModule")

    def test_meta_get_reflection_report_returns_list(self, manager):
        result = manager.meta_get_reflection_report()
        assert isinstance(result, list)

    def test_meta_get_skill_stats_no_longer_raises(self, manager):
        try:
            manager.meta_get_skill_stats()
        except NotImplementedError:
            pytest.fail("meta_get_skill_stats should delegate to MetaCognitionModule")

    def test_meta_get_skill_stats_returns_dict(self, manager):
        result = manager.meta_get_skill_stats()
        assert isinstance(result, dict)

    def test_meta_get_all_skills_no_longer_raises(self, manager):
        try:
            manager.meta_get_all_skills()
        except NotImplementedError:
            pytest.fail("meta_get_all_skills should delegate to MetaCognitionModule")

    def test_meta_get_all_skills_returns_list(self, manager):
        result = manager.meta_get_all_skills()
        assert isinstance(result, list)

    def test_meta_match_skills_no_longer_raises(self, manager):
        try:
            manager.meta_match_skills("query")
        except NotImplementedError:
            pytest.fail("meta_match_skills should delegate to MetaCognitionModule")

    def test_meta_match_skills_returns_list(self, manager):
        result = manager.meta_match_skills("query")
        assert isinstance(result, list)

    def test_meta_should_monitor_no_longer_raises(self, manager):
        try:
            manager.meta_should_monitor()
        except NotImplementedError:
            pytest.fail("meta_should_monitor should delegate to MetaCognitionModule")

    def test_meta_should_monitor_returns_bool(self, manager):
        result = manager.meta_should_monitor()
        assert isinstance(result, bool)

    def test_meta_should_reflect_no_longer_raises(self, manager):
        try:
            manager.meta_should_reflect()
        except NotImplementedError:
            pytest.fail("meta_should_reflect should delegate to MetaCognitionModule")

    def test_meta_should_reflect_returns_bool(self, manager):
        result = manager.meta_should_reflect()
        assert isinstance(result, bool)

    def test_meta_should_optimize_no_longer_raises(self, manager):
        try:
            manager.meta_should_optimize()
        except NotImplementedError:
            pytest.fail("meta_should_optimize should delegate to MetaCognitionModule")

    def test_meta_should_optimize_returns_bool(self, manager):
        result = manager.meta_should_optimize()
        assert isinstance(result, bool)

    def test_meta_should_evolve_skills_no_longer_raises(self, manager):
        try:
            manager.meta_should_evolve_skills()
        except NotImplementedError:
            pytest.fail("meta_should_evolve_skills should delegate to MetaCognitionModule")

    def test_meta_should_evolve_skills_returns_bool(self, manager):
        result = manager.meta_should_evolve_skills()
        assert isinstance(result, bool)

    def test_meta_cognition_module_initialized_after_call(self, manager):
        manager.meta_monitor()
        assert manager._meta_cognition_module is not None


# ────── TKG 委托测试 ──────


class TestTKGDelegation:
    """验证 TKG stub 委托到 TKGModule"""

    def test_tkg_add_fact_no_longer_raises(self, manager):
        try:
            manager.tkg_add_fact(subject="Alice", predicate="knows", obj="Bob")
        except NotImplementedError:
            pytest.fail("tkg_add_fact should delegate to TKGModule")

    def test_tkg_add_fact_returns_str(self, manager):
        result = manager.tkg_add_fact(subject="Alice", predicate="knows", obj="Bob")
        assert isinstance(result, str)

    def test_tkg_query_current_no_longer_raises(self, manager):
        try:
            manager.tkg_query_current(subject="Alice")
        except NotImplementedError:
            pytest.fail("tkg_query_current should delegate to TKGModule")

    def test_tkg_query_current_returns_list(self, manager):
        result = manager.tkg_query_current(subject="Alice")
        assert isinstance(result, list)

    def test_tkg_query_at_time_no_longer_raises(self, manager):
        try:
            manager.tkg_query_at_time(subject="Alice", time_from=0.0)
        except NotImplementedError:
            pytest.fail("tkg_query_at_time should delegate to TKGModule")

    def test_tkg_query_at_time_returns_list(self, manager):
        result = manager.tkg_query_at_time(subject="Alice", time_from=0.0)
        assert isinstance(result, list)

    def test_tkg_get_history_no_longer_raises(self, manager):
        try:
            manager.tkg_get_history(subject="Alice")
        except NotImplementedError:
            pytest.fail("tkg_get_history should delegate to TKGModule")

    def test_tkg_get_history_returns_list(self, manager):
        result = manager.tkg_get_history(subject="Alice")
        assert isinstance(result, list)

    def test_tkg_detect_conflicts_no_longer_raises(self, manager):
        try:
            manager.tkg_detect_conflicts(subject="Alice", predicate="knows", obj="Bob")
        except NotImplementedError:
            pytest.fail("tkg_detect_conflicts should delegate to TKGModule")

    def test_tkg_detect_conflicts_returns_list(self, manager):
        result = manager.tkg_detect_conflicts(subject="Alice", predicate="knows", obj="Bob")
        assert isinstance(result, list)

    def test_tkg_get_stats_no_longer_raises(self, manager):
        try:
            manager.tkg_get_stats()
        except NotImplementedError:
            pytest.fail("tkg_get_stats should delegate to TKGModule")

    def test_tkg_get_stats_returns_dict(self, manager):
        result = manager.tkg_get_stats()
        assert isinstance(result, dict)

    def test_tkg_module_initialized_after_call(self, manager):
        manager.tkg_get_stats()
        assert manager._tkg_module is not None


# ────── WorkingMemory 委托测试 ──────


class TestWorkingMemoryDelegation:
    """验证 WorkingMemory stub 委托到 WorkingMemoryModule"""

    def test_wm_add_turn_no_longer_raises(self, manager):
        try:
            manager.wm_add_turn(role="user", content="hello")
        except NotImplementedError:
            pytest.fail("wm_add_turn should delegate to WorkingMemoryModule")

    def test_wm_get_context_no_longer_raises(self, manager):
        try:
            manager.wm_get_context()
        except NotImplementedError:
            pytest.fail("wm_get_context should delegate to WorkingMemoryModule")

    def test_wm_get_context_returns_list(self, manager):
        result = manager.wm_get_context()
        assert isinstance(result, list)

    def test_wm_compress_turn_no_longer_raises(self, manager):
        try:
            manager.wm_compress_turn(turn_id="turn_1")
        except NotImplementedError:
            pytest.fail("wm_compress_turn should delegate to WorkingMemoryModule")

    def test_wm_cache_plan_no_longer_raises(self, manager):
        try:
            manager.wm_cache_plan(plan_id="plan_1", plan={"step": 1})
        except NotImplementedError:
            pytest.fail("wm_cache_plan should delegate to WorkingMemoryModule")

    def test_wm_retrieve_plan_no_longer_raises(self, manager):
        try:
            manager.wm_retrieve_plan(plan_id="plan_1")
        except NotImplementedError:
            pytest.fail("wm_retrieve_plan should delegate to WorkingMemoryModule")

    def test_wm_record_plan_result_no_longer_raises(self, manager):
        try:
            manager.wm_record_plan_result(plan_id="plan_1", success=True)
        except NotImplementedError:
            pytest.fail("wm_record_plan_result should delegate to WorkingMemoryModule")

    def test_wm_get_stats_no_longer_raises(self, manager):
        try:
            manager.wm_get_stats()
        except NotImplementedError:
            pytest.fail("wm_get_stats should delegate to WorkingMemoryModule")

    def test_wm_get_stats_returns_dict(self, manager):
        result = manager.wm_get_stats()
        assert isinstance(result, dict)

    def test_wm_clear_no_longer_raises(self, manager):
        try:
            manager.wm_clear()
        except NotImplementedError:
            pytest.fail("wm_clear should delegate to WorkingMemoryModule")

    def test_working_memory_module_initialized_after_call(self, manager):
        manager.wm_get_stats()
        assert manager._working_memory_module is not None


# ────── SelfManager 委托测试 ──────


class TestSelfManagerDelegation:
    """验证 SelfCommands stub 委托到 SelfManagerModule"""

    def test_self_get_commands_no_longer_raises(self, manager):
        try:
            manager.self_get_commands()
        except NotImplementedError:
            pytest.fail("self_get_commands should delegate to SelfManagerModule")

    def test_self_get_commands_returns_list(self, manager):
        result = manager.self_get_commands()
        assert isinstance(result, list)

    def test_self_add_command_no_longer_raises(self, manager):
        try:
            manager.self_add_command(name="cmd1", description="test")
        except NotImplementedError:
            pytest.fail("self_add_command should delegate to SelfManagerModule")

    def test_self_add_command_returns_str(self, manager):
        result = manager.self_add_command(name="cmd1", description="test")
        assert isinstance(result, str)

    def test_self_update_command_no_longer_raises(self, manager):
        try:
            manager.self_update_command(name="cmd1", description="updated")
        except NotImplementedError:
            pytest.fail("self_update_command should delegate to SelfManagerModule")

    def test_self_update_command_returns_bool(self, manager):
        result = manager.self_update_command(name="cmd1", description="updated")
        assert isinstance(result, bool)

    def test_self_delete_command_no_longer_raises(self, manager):
        try:
            manager.self_delete_command(name="cmd1")
        except NotImplementedError:
            pytest.fail("self_delete_command should delegate to SelfManagerModule")

    def test_self_delete_command_returns_bool(self, manager):
        result = manager.self_delete_command(name="cmd1")
        assert isinstance(result, bool)

    def test_self_get_heart_beat_tasks_no_longer_raises(self, manager):
        try:
            manager.self_get_heart_beat_tasks()
        except NotImplementedError:
            pytest.fail("self_get_heart_beat_tasks should delegate to SelfManagerModule")

    def test_self_get_heart_beat_tasks_returns_list(self, manager):
        result = manager.self_get_heart_beat_tasks()
        assert isinstance(result, list)

    def test_self_get_due_tasks_no_longer_raises(self, manager):
        try:
            manager.self_get_due_tasks()
        except NotImplementedError:
            pytest.fail("self_get_due_tasks should delegate to SelfManagerModule")

    def test_self_get_due_tasks_returns_list(self, manager):
        result = manager.self_get_due_tasks()
        assert isinstance(result, list)

    def test_self_add_heart_beat_task_no_longer_raises(self, manager):
        try:
            manager.self_add_heart_beat_task(name="task1", cron="* * * * *")
        except NotImplementedError:
            pytest.fail("self_add_heart_beat_task should delegate to SelfManagerModule")

    def test_self_add_heart_beat_task_returns_str(self, manager):
        result = manager.self_add_heart_beat_task(name="task1", cron="* * * * *")
        assert isinstance(result, str)

    def test_self_update_heart_beat_task_no_longer_raises(self, manager):
        try:
            manager.self_update_heart_beat_task(name="task1", cron="0 * * * *")
        except NotImplementedError:
            pytest.fail("self_update_heart_beat_task should delegate to SelfManagerModule")

    def test_self_update_heart_beat_task_returns_bool(self, manager):
        result = manager.self_update_heart_beat_task(name="task1", cron="0 * * * *")
        assert isinstance(result, bool)

    def test_self_record_task_run_no_longer_raises(self, manager):
        try:
            manager.self_record_task_run(name="task1", success=True)
        except NotImplementedError:
            pytest.fail("self_record_task_run should delegate to SelfManagerModule")

    def test_self_record_task_run_returns_bool(self, manager):
        result = manager.self_record_task_run(name="task1", success=True)
        assert isinstance(result, bool)

    def test_self_delete_heart_beat_task_no_longer_raises(self, manager):
        try:
            manager.self_delete_heart_beat_task(name="task1")
        except NotImplementedError:
            pytest.fail("self_delete_heart_beat_task should delegate to SelfManagerModule")

    def test_self_delete_heart_beat_task_returns_bool(self, manager):
        result = manager.self_delete_heart_beat_task(name="task1")
        assert isinstance(result, bool)

    def test_self_get_system_prompt_context_no_longer_raises(self, manager):
        try:
            manager.self_get_system_prompt_context()
        except NotImplementedError:
            pytest.fail("self_get_system_prompt_context should delegate to SelfManagerModule")

    def test_self_get_system_prompt_context_returns_str(self, manager):
        result = manager.self_get_system_prompt_context()
        assert isinstance(result, str)

    def test_self_get_status_no_longer_raises(self, manager):
        try:
            manager.self_get_status()
        except NotImplementedError:
            pytest.fail("self_get_status should delegate to SelfManagerModule")

    def test_self_get_status_returns_dict(self, manager):
        result = manager.self_get_status()
        assert isinstance(result, dict)

    def test_self_manager_module_initialized_after_call(self, manager):
        manager.self_get_status()
        assert manager._self_manager_module is not None


# ────── AutoUpdate 委托测试 ──────


class TestAutoUpdateDelegation:
    """验证 AutoUpdate stub 委托到 AutoContextModule"""

    def test_start_auto_update_no_longer_raises(self, manager):
        try:
            manager.start_auto_update(interval=60.0)
        except NotImplementedError:
            pytest.fail("start_auto_update should delegate to AutoContextModule")

    def test_stop_auto_update_no_longer_raises(self, manager):
        try:
            manager.stop_auto_update()
        except NotImplementedError:
            pytest.fail("stop_auto_update should delegate to AutoContextModule")

    def test_auto_context_module_initialized_after_call(self, manager):
        manager.start_auto_update(interval=60.0)
        assert manager._auto_context_module is not None


# ────── Conflict 委托测试 ──────


class TestConflictDelegation:
    """验证 Conflict stub 委托到 ConflictModule"""

    def test_get_traces_by_trigger_no_longer_raises(self, manager):
        try:
            manager.get_traces_by_trigger(trigger="test")
        except NotImplementedError:
            pytest.fail("get_traces_by_trigger should delegate to ConflictModule")

    def test_get_traces_by_trigger_returns_list(self, manager):
        result = manager.get_traces_by_trigger(trigger="test")
        assert isinstance(result, list)

    def test_detect_conflict_no_longer_raises(self, manager):
        try:
            manager.detect_conflict(memory_id_1="m1", content_1="a", memory_id_2="m2", content_2="b")
        except NotImplementedError:
            pytest.fail("detect_conflict should delegate to ConflictModule")

    def test_detect_conflict_returns_list(self, manager):
        result = manager.detect_conflict(memory_id_1="m1", content_1="a", memory_id_2="m2", content_2="b")
        assert isinstance(result, list)

    def test_detect_time_conflicts_no_longer_raises(self, manager):
        try:
            manager.detect_time_conflicts()
        except NotImplementedError:
            pytest.fail("detect_time_conflicts should delegate to ConflictModule")

    def test_detect_time_conflicts_returns_list(self, manager):
        result = manager.detect_time_conflicts()
        assert isinstance(result, list)

    def test_detect_all_conflicts_no_longer_raises(self, manager):
        try:
            manager.detect_all_conflicts()
        except NotImplementedError:
            pytest.fail("detect_all_conflicts should delegate to ConflictModule")

    def test_detect_all_conflicts_returns_list(self, manager):
        result = manager.detect_all_conflicts()
        assert isinstance(result, list)

    def test_get_conflict_summary_no_longer_raises(self, manager):
        try:
            manager.get_conflict_summary()
        except NotImplementedError:
            pytest.fail("get_conflict_summary should delegate to ConflictModule")

    def test_get_conflict_summary_returns_dict(self, manager):
        result = manager.get_conflict_summary()
        assert isinstance(result, dict)

    def test_conflict_module_initialized_after_call(self, manager):
        manager.get_conflict_summary()
        assert manager._conflict_module is not None


# ────── Relation 委托测试 ──────


class TestRelationDelegation:
    """验证 Relation stub 委托到 RelationModule"""

    def test_add_relation_no_longer_raises(self, manager):
        try:
            manager.add_relation(source_id="m1", target_id="m2", relation_type="similar")
        except NotImplementedError:
            pytest.fail("add_relation should delegate to RelationModule")

    def test_add_relation_returns_bool(self, manager):
        result = manager.add_relation(source_id="m1", target_id="m2", relation_type="similar")
        assert isinstance(result, bool)

    def test_get_relations_no_longer_raises(self, manager):
        try:
            manager.get_relations(memory_id="m1")
        except NotImplementedError:
            pytest.fail("get_relations should delegate to RelationModule")

    def test_get_relations_returns_list(self, manager):
        result = manager.get_relations(memory_id="m1")
        assert isinstance(result, list)

    def test_delete_relation_no_longer_raises(self, manager):
        try:
            manager.delete_relation(relation_id="r1")
        except NotImplementedError:
            pytest.fail("delete_relation should delegate to RelationModule")

    def test_delete_relation_returns_bool(self, manager):
        result = manager.delete_relation(relation_id="r1")
        assert isinstance(result, bool)

    def test_get_memory_graph_no_longer_raises(self, manager):
        try:
            manager.get_memory_graph()
        except NotImplementedError:
            pytest.fail("get_memory_graph should delegate to RelationModule")

    def test_get_memory_graph_returns_dict(self, manager):
        result = manager.get_memory_graph()
        assert isinstance(result, dict)

    def test_relate_no_longer_raises(self, manager):
        try:
            manager.relate("m1", "m2", "similar")
        except NotImplementedError:
            pytest.fail("relate should delegate to RelationModule")

    def test_relate_returns_bool(self, manager):
        result = manager.relate("m1", "m2", "similar")
        assert isinstance(result, bool)

    def test_recall_graph_no_longer_raises(self, manager):
        try:
            manager.recall_graph("query")
        except NotImplementedError:
            pytest.fail("recall_graph should delegate to RelationModule")

    def test_recall_graph_returns_dict(self, manager):
        result = manager.recall_graph("query")
        assert isinstance(result, dict)

    def test_relation_module_initialized_after_call(self, manager):
        manager.get_memory_graph()
        assert manager._relation_module is not None


# ────── Explainability 委托测试 ──────


class TestExplainabilityDelegation:
    """验证 Explainability stub 委托到 ExplainabilityModule"""

    def test_get_explanation_chain_no_longer_raises(self, manager):
        try:
            manager.get_explanation_chain(memory_id="m1")
        except NotImplementedError:
            pytest.fail("get_explanation_chain should delegate to ExplainabilityModule")

    def test_get_explanation_chain_returns_list(self, manager):
        result = manager.get_explanation_chain(memory_id="m1")
        assert isinstance(result, list)

    def test_visualize_chain_no_longer_raises(self, manager):
        try:
            manager.visualize_chain(memory_id="m1")
        except NotImplementedError:
            pytest.fail("visualize_chain should delegate to ExplainabilityModule")

    def test_visualize_chain_returns_str(self, manager):
        result = manager.visualize_chain(memory_id="m1")
        assert isinstance(result, str)

    def test_explainability_module_initialized_after_call(self, manager):
        manager.get_explanation_chain(memory_id="m1")
        assert manager._explainability_module is not None


# ────── ForgettingRecovery 委托测试 ──────


class TestForgettingRecoveryDelegation:
    """验证 get_recovery_history 委托到 ForgettingRecoveryModule"""

    def test_get_recovery_history_no_longer_raises(self, manager):
        try:
            manager.get_recovery_history()
        except NotImplementedError:
            pytest.fail("get_recovery_history should delegate to ForgettingRecoveryModule")

    def test_get_recovery_history_returns_list(self, manager):
        result = manager.get_recovery_history()
        assert isinstance(result, list)

    def test_forgetting_recovery_module_initialized_after_call(self, manager):
        manager.get_recovery_history()
        assert manager._forgetting_recovery_module is not None
