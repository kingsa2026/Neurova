"""记忆类型页签/结晶闭环/温度死锁 三根因修复测试

背景（2026-09-08 记忆页页签同质化事故）：
  1. 页签契约断裂：前端页签 key（episodic/semantic/...）从未传到后端，
     后端 GET /memory 也无 memory_type 过滤参数 → 四个类型页签同一查询。
  2. 结晶写入路径缺失：全库零处赋值 lifecycle_stage=CRYSTALLIZED，
     API is_crystallized=True 只落 metadata（写入存 A、读取判 B）。
  3. 温度死锁：新记忆初始温度 100 ≥ 高温不衰减阈值 80 → 恒不衰减，
     热点页签 = 全量页签。

测试口径：
  - manager 层用独立 tmpdir（persist DB 固定名，同目录会互相污染）
  - settings 用 MemorySettingsConfig.reset_instance + data_dir 隔离
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import (
    LifecycleStage,
    MemoryType,
)
from neurova.cognitive_layers.memory_layer.settings_config import (
    MemorySettingsConfig,
    reset_memory_settings,
)


def _manager(**overrides) -> MemoryManager:
    tmpdir = tempfile.mkdtemp(prefix="mem_tabfix_")
    kwargs = dict(
        db_path=os.path.join(tmpdir, "mem.db"),
        agent_id="test-agent",
        neuser_id="nu-test",
        user_id="u-test",
    )
    kwargs.update(overrides)
    return MemoryManager(**kwargs)


def _isolate_settings(monkeypatched: dict | None = None):
    """隔离记忆设置为独立 data_dir，可选预置覆盖值"""
    tmpdir = tempfile.mkdtemp(prefix="mem_settings_")
    reset_memory_settings()
    cfg = MemorySettingsConfig.get_instance(data_dir=tmpdir)
    if monkeypatched:
        cfg.update_and_save(monkeypatched)
    return cfg


class TestTabContractFixBase(unittest.TestCase):
    def setUp(self):
        _isolate_settings()
        self.mgr = _manager()

    def tearDown(self):
        reset_memory_settings()


class TestCrystallizeClosure(TestTabContractFixBase):
    """结晶闭环：metadata.is_crystallized=True 必须同步 lifecycle_stage。"""

    def test_remember_is_crystallized_sets_stage(self):
        """API is_crystallized=True → lifecycle_stage=CRYSTALLIZED（写入侧闭环）。"""
        mid = self.mgr.remember("我的生日是 1990-01-01", is_crystallized=True)
        mem = self.mgr._memories[mid]
        self.assertEqual(mem.lifecycle_stage, LifecycleStage.CRYSTALLIZED)
        self.assertTrue(mem.to_dict()["is_crystallized"])

    def test_remember_not_crystallized_keeps_active(self):
        """默认创建不结晶。"""
        mid = self.mgr.remember("普通记忆")
        self.assertEqual(self.mgr._memories[mid].lifecycle_stage, LifecycleStage.ACTIVE)

    def test_crystallized_survives_reload(self):
        """结晶持久化：重载同库后 lifecycle_stage 不丢（write A read B 断根）。"""
        self.mgr.remember("纪念日", is_crystallized=True)
        mgr2 = MemoryManager(
            db_path=self.mgr._db_path,
            agent_id="test-agent",
            neuser_id="nu-test",
            user_id="u-test",
        )
        loaded = [m for m in mgr2._memories.values() if m.lifecycle_stage == LifecycleStage.CRYSTALLIZED]
        self.assertEqual(len(loaded), 1)
        self.assertTrue(loaded[0].to_dict()["is_crystallized"])

    def test_get_crystallized_returns_crystallized(self):
        """读取端不再是死列表：remember(is_crystallized=True) 后 get_crystallized 命中。"""
        self.mgr.remember("密码是 123456", is_crystallized=True)
        self.mgr.remember("今天天气不错")
        result = self.mgr.get_crystallized(limit=10, agent_wide=True)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["content"], "密码是 123456")

    def test_metadata_backward_compat_migration_on_load(self):
        """存量迁移：库中 metadata.is_crystallized=True 但 stage=active 的旧行，
        装载时收敛为 CRYSTALLIZED（修复前存量数据）。"""
        mid = self.mgr.remember("旧格式结晶记忆")
        # 模拟存量坏数据：metadata 有标记、stage 停在 active
        self.mgr._memories[mid].metadata["is_crystallized"] = True
        self.mgr._memories[mid].lifecycle_stage = LifecycleStage.ACTIVE
        self.mgr._persist_memory(self.mgr._memories[mid])

        mgr2 = MemoryManager(
            db_path=self.mgr._db_path,
            agent_id="test-agent",
            neuser_id="nu-test",
            user_id="u-test",
        )
        fixed = mgr2._memories[mid]
        self.assertEqual(fixed.lifecycle_stage, LifecycleStage.CRYSTALLIZED)


class TestPromotionToCrystallized(TestTabContractFixBase):
    """晋升链走完最后一步：CONSOLIDATED→CRYSTALLIZED（硬信号 N 次后）。"""

    def _mem(self, mid, temperature=50.0, access_count=0, importance=50.0):
        from neurova.cognitive_layers.memory_layer.models import (
            EmotionType,
            Memory,
            MemoryCategory,
            MemoryOrigin,
        )

        return Memory(
            id=mid,
            content=f"content-{mid}",
            memory_type=MemoryType.SEMANTIC,
            category=MemoryCategory.GENERAL,
            temperature=temperature,
            importance=importance,
            access_count=access_count,
            origin=MemoryOrigin.AGENT,
            emotion=EmotionType.NEUTRAL,
            agent_id="test-agent",
            neuser_id="nu-test",
            user_id="u-test",
        )

    def test_promoted_memory_crystallizes_after_n_cycles(self):
        """晋升（CONSOLIDATED）后继续满足硬信号 → 达到 N 次阈值结晶。"""
        mem = self._mem("c1", temperature=85.0)
        self.mgr._memories[mem.id] = mem
        # 第一轮：ACTIVE → 晋升
        self.mgr.run_promotion_cycle(max_memories=100)
        stage_after_first = self.mgr._memories["c1"].lifecycle_stage
        self.assertIn(
            stage_after_first,
            (LifecycleStage.CONSOLIDATED, LifecycleStage.CRYSTALLIZED),
            f"首轮应至少晋升到 CONSOLIDATED，实际 {stage_after_first}",
        )
        if stage_after_first == LifecycleStage.CRYSTALLIZED:
            return  # 阈值=1 的配置下首轮即结晶，亦合法
        # 后续轮：继续满足硬信号 → 计数累积 → 结晶
        for _ in range(10):
            self.mgr._last_promotion_at = None  # 绕过节流
            self.mgr.run_promotion_cycle(max_memories=100)
        self.assertEqual(self.mgr._memories["c1"].lifecycle_stage, LifecycleStage.CRYSTALLIZED)

    def test_crystallize_threshold_configurable(self):
        """结晶阈值 N 可配置（manager.crystallize_cycles，默认 3）。"""
        cfg = _isolate_settings({"manager.crystallize_cycles": 1})
        try:
            mgr = _manager()
            mem = self._mem("c2", temperature=85.0)
            mgr._memories[mem.id] = mem
            mgr.run_promotion_cycle(max_memories=100)
            self.assertEqual(mgr._memories["c2"].lifecycle_stage, LifecycleStage.CRYSTALLIZED)
        finally:
            reset_memory_settings()

    def test_non_qualifying_memory_never_crystallizes(self):
        """未命中硬信号的记忆不被结晶（确定性门控不被稀释）。"""
        mem = self._mem("c3", temperature=30.0, access_count=1)
        self.mgr._memories[mem.id] = mem
        for _ in range(12):
            self.mgr._last_promotion_at = None
            self.mgr.run_promotion_cycle(max_memories=100)
        self.assertNotEqual(self.mgr._memories["c3"].lifecycle_stage, LifecycleStage.CRYSTALLIZED)


class TestInitialTemperature(TestTabContractFixBase):
    """温度死锁：初始温度默认落入衰减曲线工作区（60~70）。"""

    def test_default_initial_temperature_in_working_range(self):
        cfg = _isolate_settings()
        try:
            self.assertLessEqual(cfg.get("manager.new_memory_temperature"), 70.0)
            self.assertGreaterEqual(cfg.get("manager.new_memory_temperature"), 60.0)
        finally:
            reset_memory_settings()

    def test_new_memory_can_decay(self):
        """新记忆初始温度 <80 → 衰减引擎真正作用于它（死锁解除）。"""
        mid = self.mgr.remember("会衰减的记忆")
        mem = self.mgr._memories[mid]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=7)
        # 衰减一周
        self.mgr._last_decay_at = None
        self.mgr.run_decay_cycle(max_memories=100)
        self.assertLess(self.mgr._memories[mid].temperature, 65.0)

    def test_schema_default_updated(self):
        """schema 默认值同步更新（未覆盖用户即生效）。"""
        from neurova.cognitive_layers.memory_layer.settings_config import PARAM_SCHEMAS

        schema = {s.key: s for s in PARAM_SCHEMAS}
        self.assertLessEqual(schema["manager.new_memory_temperature"].default, 70.0)


class TestExplicitOverrideStillWorks(TestTabContractFixBase):
    """显式传参优先于配置（既有契约不回退）。"""

    def test_explicit_temperature_respected(self):
        mid = self.mgr.remember("显式温度", temperature=99.0)
        self.assertEqual(self.mgr._memories[mid].temperature, 99.0)


if __name__ == "__main__":
    unittest.main()
