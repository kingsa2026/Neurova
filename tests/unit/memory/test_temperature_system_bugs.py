"""
温度系统 bug 修复测试 — Bug 1 + Bug 2

Bug 1: MemCore.update_memory_temperature 调用不存在的 TemperatureEngine.update_temperature
       - 现状：try/except 吞没 AttributeError，温度永不通过此路径更新
       - 修复：委托给 MemoryManager.update_memory_temperature（已存在且工作）

Bug 2: MemoryManager.run_decay_cycle 绕过 TemperatureEngine.on_decay
       - 现状：直接调 Memory.decay()（简单线性 temp -= rate*hours）
       - 修复：调用 TemperatureEngine.on_decay，应用贝叶斯遗忘曲线
       - 贝叶斯特性：固化不衰减、高温(>=80)不衰减、今天访问不衰减、情感保护、重要性保护

遵循 TDD 垂直切片：一次一个测试 → 一次一个修复。
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import Memory, MemoryType, LifecycleStage
from neurova.cognitive_layers.memory_layer.temperature import TemperatureEngine


# ──────────────────────────────────────────────────────────────────
# Bug 1: MemCore.update_memory_temperature 调用不存在的 TemperatureEngine.update_temperature
# ──────────────────────────────────────────────────────────────────


class TestBug1MemCoreUpdateTemperature:
    """Bug 1: MemCore.update_memory_temperature 应委托给 MemoryManager，而非调用不存在的方法"""

    def test_mem_core_update_memory_temperature_delegates_to_manager(self):
        """MemCore.update_memory_temperature 应调用 MemoryManager.update_memory_temperature

        根因：当前实现调用 self.temperature_engine.update_temperature()，
        但 TemperatureEngine 没有 update_temperature 方法 → AttributeError 被吞没。
        修复：委托给 self.memory_manager.update_memory_temperature()（已存在）。
        """
        from neurova.mem_core import MemCore

        mock_agent = MagicMock()
        mock_agent.memory_manager = MagicMock()
        mock_agent.memory_manager.update_memory_temperature.return_value = True
        mock_agent.temperature_engine = MagicMock()  # 即使存在也不应被调用

        mem_core = MemCore(mock_agent)
        mem_core.update_memory_temperature("mem_123", interaction_type="recall")

        # 应委托给 memory_manager.update_memory_temperature
        mock_agent.memory_manager.update_memory_temperature.assert_called_once_with(
            "mem_123", interaction_type="recall"
        )
        # 不应调用 temperature_engine.update_temperature（不存在的方法）
        mock_agent.temperature_engine.update_temperature.assert_not_called()

    def test_mem_core_update_memory_temperature_actually_updates_temp(self):
        """集成测试：MemCore.update_memory_temperature 应实际更新记忆温度

        验证修复后温度真的被更新（而非被 try/except 静默吞没）。
        """
        from neurova.mem_core import MemCore

        # 用真实 MemoryManager（:memory: SQLite）
        manager = MemoryManager(db_path=":memory:", agent_id="test_bug1")
        mem_id = manager.remember(content="Bug 1 集成测试", temperature=50.0)

        # 构造一个 mock agent，持有真实 manager
        mock_agent = MagicMock()
        mock_agent.memory_manager = manager
        mock_agent.temperature_engine = TemperatureEngine()  # 真实 TemperatureEngine

        mem_core = MemCore(mock_agent)

        # 修复前：调用不存在的 update_temperature → AttributeError 被吞没 → 温度不变
        # 修复后：委托给 manager.update_memory_temperature → touch() → 温度 +10
        mem_core.update_memory_temperature(mem_id, interaction_type="recall")

        assert manager._memories[mem_id].temperature == 60.0  # 50 + 10 = 60

    def test_mem_core_update_memory_temperature_handles_missing_manager(self):
        """memory_manager 为 None 时应优雅跳过，不抛异常"""
        from neurova.mem_core import MemCore

        mock_agent = MagicMock()
        mock_agent.memory_manager = None
        mock_agent.temperature_engine = MagicMock()

        mem_core = MemCore(mock_agent)
        # 不应抛异常
        mem_core.update_memory_temperature("mem_x", interaction_type="view")


# ──────────────────────────────────────────────────────────────────
# Bug 2: MemoryManager.run_decay_cycle 绕过 TemperatureEngine.on_decay
# ──────────────────────────────────────────────────────────────────


class TestBug2RunDecayCycleUsesTemperatureEngine:
    """Bug 2: run_decay_cycle 应调用 TemperatureEngine.on_decay，应用贝叶斯曲线"""

    def _make_manager(self, agent_id="test_bug2"):
        """创建隔离的 MemoryManager"""
        import uuid

        unique_id = f"{agent_id}_{uuid.uuid4().hex[:8]}"
        return MemoryManager(db_path=":memory:", agent_id=unique_id)

    def test_run_decay_cycle_uses_temperature_engine_on_decay(self):
        """run_decay_cycle 应调用 TemperatureEngine.on_decay

        根因：当前实现直接调 Memory.decay()（简单线性 temp -= rate*hours），
        完全绕过 TemperatureEngine.on_decay 的贝叶斯曲线。
        修复：通过 TemperatureEngine.on_decay 计算新温度。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="Bug 2 测试", temperature=50.0)

        # 修改 last_accessed_at 为 7 天前（触发衰减）
        mem = manager._memories[mem_id]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=7)

        # 监视 TemperatureEngine.on_decay 是否被调用
        # 注意：on_decay 是 @classmethod（同名覆盖实例方法），spy 必须用 classmethod 包装
        # 否则 Python 会把 engine 实例绑到第一个位置参数，与 cls 自动绑定冲突
        original_on_decay = TemperatureEngine.on_decay
        call_count = {"count": 0}

        @classmethod
        def spy_on_decay(cls, *args, **kwargs):
            call_count["count"] += 1
            return original_on_decay(*args, **kwargs)

        try:
            TemperatureEngine.on_decay = spy_on_decay
            manager.run_decay_cycle()
        finally:
            TemperatureEngine.on_decay = original_on_decay

        # 修复后：on_decay 应被调用至少一次
        assert call_count["count"] > 0, "run_decay_cycle 未调用 TemperatureEngine.on_decay"

    def test_run_decay_cycle_skips_crystallized_memories(self):
        """固化记忆（lifecycle_stage=CRYSTALLIZED）不应衰减

        贝叶斯特性：is_crystallized=True 时 on_decay 返回 new_temp=current_temp。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="固化记忆", temperature=50.0)

        mem = manager._memories[mem_id]
        mem.lifecycle_stage = LifecycleStage.CRYSTALLIZED
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=30)

        original_temp = mem.temperature
        manager.run_decay_cycle()

        # 固化记忆温度不变
        assert mem.temperature == original_temp, f"固化记忆被衰减: {original_temp} → {mem.temperature}"

    def test_run_decay_cycle_skips_high_temperature(self):
        """高温记忆（>=80）不应衰减（视为固化）

        贝叶斯特性：current_temp >= 80.0 时 on_decay 返回 new_temp=current_temp。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="高温记忆", temperature=85.0)

        mem = manager._memories[mem_id]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=30)

        original_temp = mem.temperature
        manager.run_decay_cycle()

        # 高温记忆温度不变
        assert mem.temperature == original_temp, f"高温记忆被衰减: {original_temp} → {mem.temperature}"

    def test_run_decay_cycle_skips_recently_accessed(self):
        """今天访问过的记忆（days_idle < 1）不应衰减

        贝叶斯特性：days_idle < 1.0 时 on_decay 返回 new_temp=current_temp。
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="刚访问的记忆", temperature=50.0)

        mem = manager._memories[mem_id]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(hours=2)  # 2 小时前

        original_temp = mem.temperature
        manager.run_decay_cycle()

        # 今天访问的记忆温度不变
        assert mem.temperature == original_temp, f"刚访问的记忆被衰减: {original_temp} → {mem.temperature}"

    def test_run_decay_cycle_applies_bayesian_curve_not_linear(self):
        """贝叶斯衰减应与简单线性衰减不同

        简单线性：temp -= rate*hours（等量衰减）
        贝叶斯：temp = temp * (1 - decay_rate)，decay_rate 受曲线因子、情感、重要性影响

        对于 7 天前访问、温度 50、重要性 50 的记忆：
        - 简单线性（rate=1, hours=1）：50 - 1 = 49
        - 贝叶斯：curve_factor(7d)=1.0, decay_rate 受多因子影响，new_temp = 50 * (1 - decay_rate)
        """
        manager = self._make_manager()
        mem_id = manager.remember(content="贝叶斯曲线测试", temperature=50.0, importance=50.0)

        mem = manager._memories[mem_id]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=7)

        manager.run_decay_cycle()  # 修复后用贝叶斯

        # 贝叶斯衰减后温度应大于简单线性衰减（49），因为曲线因子和重要性保护
        # 简单线性: 50 - 1*1 = 49
        # 贝叶斯 (估算): decay_rate ≈ 1.0 * 1.0 * 0.25 * 0.75 * 1.0 * 1.0 * 1.0 = 0.1875
        #              new_temp = 50 * (1 - 0.1875) = 40.625
        # 注意：贝叶斯可能比线性衰减更多（因为 50 * 0.8125 = 40.625 < 49）
        # 关键是：不等于 49（简单线性）
        assert mem.temperature != 49.0, (
            f"run_decay_cycle 仍使用简单线性衰减 (50-1=49)，未应用贝叶斯曲线。实际: {mem.temperature}"
        )

    def test_run_decay_cycle_updates_lifecycle_stage(self):
        """衰减后应更新 lifecycle_stage（基于贝叶斯曲线返回值）"""
        manager = self._make_manager()
        mem_id = manager.remember(content="阶段更新测试", temperature=30.0)

        mem = manager._memories[mem_id]
        mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=45)

        manager.run_decay_cycle()

        # 衰减后温度降低，lifecycle_stage 应从 ACTIVE 变为 SECONDARY 或 ARCHIVED
        # （_determine_stage: 30 度 + 45 天 → archived）
        assert mem.lifecycle_stage != LifecycleStage.ACTIVE or mem.temperature >= 60.0, (
            f"衰减后阶段未更新: stage={mem.lifecycle_stage}, temp={mem.temperature}"
        )

    def test_run_decay_cycle_thread_safe(self):
        """run_decay_cycle 应在锁保护下执行（线程安全）

        Bug 5 关联：原实现遍历 _memories 时无锁，并发调用可能 RuntimeError。
        """
        import threading

        manager = self._make_manager()
        # 添加多条记忆
        for i in range(20):
            mem_id = manager.remember(content=f"并发测试 {i}", temperature=50.0)
            manager._memories[mem_id].last_accessed_at = (
                datetime.now(timezone.utc) - timedelta(days=7)
            )

        errors = []

        def worker():
            try:
                manager.run_decay_cycle()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"并发 run_decay_cycle 抛出异常: {errors}"
