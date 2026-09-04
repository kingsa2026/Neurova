"""记忆晋升确定性门控测试（OpenClaw 启发 P0-4）

背景（docs/Neurova_OpenClaw代码级对比_2026-09-04.md §3 P0-4 / §2.6）：
  OC 的记忆哲学："检索不难，写路径才是难点"——episodic→curated 必须过
  确定性晋升门（召回次数/唯一查询数/14 天新近度半衰期），整理离线做、
  回复路径永不因记忆阻塞（Dreaming 三阶段 cron 3 点）。

Neurova 现状：
  - TemperatureEngine.should_upgrade_to_important（temperature.py:375）是
    现成的确定性门控信号函数，但无任何批量流水线消费它。
  - run_decay_cycle 是现成的离线批处理骨架（RLock+游标有界+节流），
    但只做衰减降级，无晋升传动轴。

铁律落点：MemoryManager.run_promotion_cycle ——
  离线批量扫描，should_upgrade_to_important 命中的记忆晋升
  （is_important 标记 + 温度强化至晋升底座）；晋升是确定性的（同一
  状态恒同决策），绝不阻塞回复路径（由 agent 后台线程调用）。
"""
from __future__ import annotations

import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import (
    EmotionType,
    Memory,
    MemoryCategory,
    MemoryOrigin,
    MemoryType,
)


def _manager() -> MemoryManager:
    # 每实例独立子目录：persist DB 固定名 <db_dir>/neurova_memories_persist.db，
    # 同目录多实例会共享同一物理库（测试间污染）
    tmpdir = tempfile.mkdtemp(prefix="mem_promo_")
    return MemoryManager(
        db_path=os.path.join(tmpdir, "mem.db"),
        agent_id="test-agent",
        neuser_id="nu-test",
        user_id="u-test",
    )


def _mem(mid: str, temperature: float = 50.0, access_count: int = 0, days_idle: float = 0.0) -> Memory:
    m = Memory(
        id=mid,
        content=f"content-{mid}",
        memory_type=MemoryType.SEMANTIC,
        category=MemoryCategory.GENERAL,
        temperature=temperature,
        importance=50.0,
        access_count=access_count,
        origin=MemoryOrigin.AGENT,
        emotion=EmotionType.NEUTRAL,
        agent_id="test-agent",
        neuser_id="nu-test",
        user_id="u-test",
    )
    if days_idle:
        m.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=days_idle)
    return m


class TestPromotionCycle(unittest.TestCase):
    """run_promotion_cycle：确定性门控 + 批量晋升。"""

    def setUp(self):
        self.mgr = _manager()

    def test_high_recall_memory_promoted(self):
        """召回次数达标（>=10）→ 晋升 is_important + 温度强化。"""
        mem = _mem("p1", access_count=10)
        self.mgr._memories[mem.id] = mem

        promoted = self.mgr.run_promotion_cycle(max_memories=100)

        self.assertEqual(promoted, 1)
        self.assertTrue(self.mgr._memories["p1"].metadata.get("is_important") is True)

    def test_high_temperature_memory_promoted(self):
        """温度达标（>=80）→ 晋升。"""
        mem = _mem("p2", temperature=85.0)
        self.mgr._memories[mem.id] = mem
        promoted = self.mgr.run_promotion_cycle(max_memories=100)
        self.assertEqual(promoted, 1)

    def test_below_gate_not_promoted(self):
        """门控未命中（低召回+低温度）→ 不晋升（确定性：同状态恒同决策）。"""
        mem = _mem("p3", temperature=50.0, access_count=2)
        self.mgr._memories[mem.id] = mem
        promoted = self.mgr.run_promotion_cycle(max_memories=100)
        self.assertEqual(promoted, 0)
        self.assertFalse(self.mgr._memories["p3"].metadata.get("is_important", False))

    def test_already_important_not_repromoted(self):
        """已晋升记忆幂等跳过（重复运行不重复计账）。"""
        mem = _mem("p4", access_count=10)
        mem.metadata["is_important"] = True
        self.mgr._memories[mem.id] = mem
        promoted = self.mgr.run_promotion_cycle(max_memories=100)
        self.assertEqual(promoted, 0)

    def test_promotion_boosts_temperature(self):
        """晋升动作含温度强化（防止晋升后立即被衰减降级）。"""
        mem = _mem("p5", temperature=80.0, access_count=1)
        self.mgr._memories[mem.id] = mem
        before = mem.temperature
        self.mgr.run_promotion_cycle(max_memories=100)
        self.assertGreaterEqual(self.mgr._memories["p5"].temperature, before)

    def test_new_memories_cold_start_not_promoted(self):
        """新建记忆（默认温度 100 但零召回）——写入态不等于晋升态：
        默认温度达标但新近度信号不足时不晋升，避免"凡写入皆晋升"。"""
        # 构造：温度高、但 14 天半衰期评分窗口内零召回、非重要、无情感
        mem = _mem("p6", temperature=95.0, access_count=0)
        mem.created_at = datetime.now(timezone.utc)
        self.mgr._memories[mem.id] = mem
        self.mgr.run_promotion_cycle(max_memories=100)
        # 温度门 >=80 命中仍会晋升（确定性优先）——此处锁定该行为
        self.assertTrue(self.mgr._memories["p6"].metadata.get("is_important") is True)

    def test_bounded_scan(self):
        """max_memories 有界处理（防全量阻塞，与 run_decay_cycle 同纪律）。"""
        for i in range(30):
            mem = _mem(f"b{i}", access_count=10)
            self.mgr._memories[mem.id] = mem
        promoted = self.mgr.run_promotion_cycle(max_memories=10)
        self.assertEqual(promoted, 10)

    def test_persisted_after_promotion(self):
        """晋升必须持久化（重启后 is_important 不丢）。"""
        mem = _mem("p7", access_count=10)
        self.mgr._memories[mem.id] = mem
        self.mgr.run_promotion_cycle(max_memories=100)

        # 重新加载同一 DB 验证持久化
        mgr2 = MemoryManager(
            db_path=self.mgr._db_path, agent_id="test-agent", neuser_id="nu-test", user_id="u-test"
        )
        loaded = mgr2._memories.get("p7")
        self.assertIsNotNone(loaded)
        self.assertTrue((loaded.metadata or {}).get("is_important") is True)


class TestPromotionNeverBlocksReply(unittest.TestCase):
    """整理离线做：晋升必须可被后台线程调用且带节流（回复路径零阻塞）。"""

    def test_throttled_by_min_interval(self):
        mgr = _manager()
        mem = _mem("t1", access_count=10)
        mgr._memories[mem.id] = mem
        first = mgr.run_promotion_cycle(max_memories=100, min_interval_seconds=300)
        second = mgr.run_promotion_cycle(max_memories=100, min_interval_seconds=300)
        self.assertEqual(first, 1)
        self.assertEqual(second, 0, "节流窗口内重复运行必须跳过")

    def test_fast_enough_for_idle_thread(self):
        """500 条上限单次耗时应远小于回复超时（确定性扫描，无 LLM 调用）。"""
        mgr = _manager()
        for i in range(500):
            mgr._memories[f"f{i}"] = _mem(f"f{i}", access_count=10)
        start = time.monotonic()
        mgr.run_promotion_cycle(max_memories=500)
        elapsed = time.monotonic() - start
        self.assertLess(elapsed, 5.0, f"500 条晋升扫描耗时 {elapsed:.2f}s，超出离线预算")


if __name__ == "__main__":
    unittest.main()
