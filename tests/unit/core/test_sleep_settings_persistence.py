"""睡眠设置持久化与冲突解决产出测试

遗留问题修复 (SleepSettingsPage 报告):
1. 设置仅存内存, agent 重启即丢 → SleepConsolidation 支持 settings_path
   JSON 持久化, update_settings 落盘, 初始化时加载。
2. sleep_threshold_minutes 无消费方 → 自动阶段迁移 (active → 睡眠阶段)
   要求空闲时长 ≥ 阈值分钟数; 深层迁移与手动阶段不受限。
3. conflict_resolution_enabled 无产出 → 多成员簇合并时记录冲突解决
   审计记录 (前端 /conflicts 列表的数据源), 并提供 resolve 入口。
"""

import time
from unittest.mock import MagicMock

import pytest

from neurova.core.idle_tracker import IdleTimeTracker
from neurova.core.sleep_settings_store import SleepSettingsStore
from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation


@pytest.fixture
def consolidation(tmp_path):
    return SleepConsolidation(memory_manager=None, storage=None)


def _store(tmp_path, agent_id="agent_a") -> SleepSettingsStore:
    return SleepSettingsStore(agent_id, base_dir=str(tmp_path))


def _record(rid: str, content: str, **kwargs) -> MemoryRecord:
    return MemoryRecord(id=rid, content=content, **kwargs)


class TestSettingsPersistence:
    def test_update_settings_persists_to_disk(self, tmp_path):
        c = SleepConsolidation(settings_store=_store(tmp_path))
        c.update_settings({"auto_sleep_enabled": False, "sleep_threshold_minutes": 45})

        data = _store(tmp_path).load()
        assert data["auto_sleep_enabled"] is False
        assert data["sleep_threshold_minutes"] == 45

    def test_new_instance_loads_persisted_settings(self, tmp_path):
        c1 = SleepConsolidation(settings_store=_store(tmp_path))
        c1.update_settings({"sleep_duration_minutes": 90, "dream_replay_enabled": False})

        c2 = SleepConsolidation(settings_store=_store(tmp_path))
        s = c2.get_settings()
        assert s["sleep_duration_minutes"] == 90
        assert s["dream_replay_enabled"] is False
        # 未覆盖的键保持默认
        assert s["auto_sleep_enabled"] is True

    def test_persisted_unknown_keys_ignored(self, tmp_path):
        store = _store(tmp_path)
        store.save({"sleep_duration_minutes": 42, "bogus": 1})
        c = SleepConsolidation(settings_store=store)
        s = c.get_settings()
        assert s["sleep_duration_minutes"] == 42
        assert "bogus" not in s

    def test_store_rejects_unsafe_agent_id(self, tmp_path):
        """agent_id 白名单: 目录穿越/特殊字符被拒绝"""
        for bad in ["../evil", "a/b", "a b", ".hidden", "", "a" * 65]:
            with pytest.raises(ValueError):
                SleepSettingsStore(bad, base_dir=str(tmp_path))

    def test_no_store_no_persistence(self, consolidation):
        consolidation.update_settings({"auto_sleep_enabled": False})
        # 未提供 store 时保持旧行为: 仅内存
        assert consolidation.get_settings()["auto_sleep_enabled"] is False


class TestIdleThresholdGate:
    """sleep_threshold_minutes: active 阶段的自动迁移需空闲 ≥ 阈值分钟"""

    def _tracker(self, consolidation, threshold_minutes: int) -> IdleTimeTracker:
        t = IdleTimeTracker()
        t._monitor_running = False
        t.set_sleep_consolidation(consolidation)
        t.set_memory_manager(MagicMock())
        consolidation.update_settings({"sleep_threshold_minutes": threshold_minutes})
        # 温度模式 + 低温 (温度条件满足, 只剩空闲门)
        t._temperature_provider = lambda: 10.0
        t._sleep_mode = "temperature"
        t._current_phase = "active"
        return t

    def test_gate_blocks_when_idle_below_threshold(self, consolidation):
        t = self._tracker(consolidation, 30)
        t._last_activity_time = time.time() - 5 * 60  # 空闲 5 分钟 < 30

        assert t.check_and_update_phase() is None
        assert t.get_current_phase() == "active"

    def test_gate_passes_when_idle_above_threshold(self, consolidation):
        t = self._tracker(consolidation, 30)
        t._last_activity_time = time.time() - 31 * 60  # 空闲 31 分钟

        assert t.check_and_update_phase() == "light_sleep"

    def test_gate_not_applied_to_deeper_transitions(self, consolidation):
        """已处于睡眠阶段时, 深化迁移不受该门限制 (空闲从阶段起点计)"""
        t = self._tracker(consolidation, 30)
        t._current_phase = "light_sleep"
        t._phase_start_time = time.time() - 3600  # 阶段持续 60 分钟

        assert t.check_and_update_phase() == "deep_sleep"

    def test_zero_threshold_disables_gate(self, consolidation):
        t = self._tracker(consolidation, 0)
        t._last_activity_time = time.time() - 5  # 刚活跃

        assert t.check_and_update_phase() == "light_sleep"

    def test_record_activity_resets_idle(self, consolidation):
        t = self._tracker(consolidation, 30)
        t._last_activity_time = time.time() - 31 * 60
        t.record_activity()

        assert t.check_and_update_phase() is None


class TestConflictResolutionRecords:
    """conflict_resolution_enabled: 多成员簇合并产出冲突解决审计记录"""

    def test_merge_records_conflict(self, consolidation):
        consolidation.merge_cluster(
            [_record("m1", "用户喜欢咖啡", temperature=60.0), _record("m2", "用户喜欢咖啡和茶", temperature=40.0)]
        )
        records = consolidation.get_conflict_resolutions()
        assert len(records) == 1
        rec = records[0]
        assert rec["field"] == "content"
        assert rec["resolved"] is True
        assert rec["source_memories"] == ["m1", "m2"]
        assert rec["local_value"]  # 保留内容预览
        assert rec["remote_value"]  # 被合并内容预览
        assert rec["id"]

    def test_merge_conflict_disabled_no_records(self, consolidation):
        consolidation.update_settings({"conflict_resolution_enabled": False})
        consolidation.merge_cluster(
            [_record("m1", "内容甲", temperature=60.0), _record("m2", "内容乙不同", temperature=40.0)]
        )
        assert consolidation.get_conflict_resolutions() == []

    def test_single_member_cluster_no_record(self, consolidation):
        consolidation.merge_cluster([_record("m1", "独立记忆")])
        assert consolidation.get_conflict_resolutions() == []

    def test_identical_contents_no_record(self, consolidation):
        """内容完全相同的重复记忆是普通去重, 不是冲突"""
        consolidation.merge_cluster([_record("m1", "相同内容"), _record("m2", "相同内容")])
        assert consolidation.get_conflict_resolutions() == []

    def test_newest_first_and_pagination(self, consolidation):
        for i in range(3):
            consolidation.merge_cluster(
                [_record(f"a{i}", f"甲{i}"), _record(f"b{i}", f"乙{i}不同")]
            )
            time.sleep(0.002)  # 保证时间戳有序
        records = consolidation.get_conflict_resolutions(limit=2)
        assert len(records) == 2
        ids = {r["source_memories"][0] for r in records}
        assert ids == {"a2", "a1"}  # 最新在前

    def test_resolve_conflict_updates_record(self, consolidation):
        consolidation.merge_cluster([_record("m1", "甲"), _record("m2", "乙不同")])
        rec = consolidation.get_conflict_resolutions()[0]

        updated = consolidation.resolve_conflict(rec["id"], "keep_newest")
        assert updated is not None
        assert updated["resolved"] is True
        assert updated["resolution"] == "keep_newest"

        assert consolidation.resolve_conflict("nonexistent", "x") is None
