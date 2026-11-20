"""
主动回忆机制 RED 测试 — 定时回忆巩固 + 上下文触发回忆 + 任务驱动回忆

设计稿：docs/01-architecture/14-proactive-recall-mechanism.md
事实源核验（2026-11-20）：原台账声称的 neurova/memory/core/proactive_recall.py
不存在；本测试钉住落地契约：

- runScheduledRecallCycle：扫描久未访问记忆 → 模拟回忆（可配置升温 +
  刷新 last_accessed_at），遗忘概率高者优先，结晶/已遗忘跳过，开关可关
- contextTriggeredRecall：时间模式（metadata.time_pattern）与情感强度
  触发主动召回，与调用方去重合并
- taskDrivenRecall：按任务描述召回经验/教训/技能/偏好（本仓枚举映射）
- MemoryManager.markSimulatedRecall：模拟回忆落盘（温度+boost、
  last_accessed_at 刷新、access_count+1）
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


def _makeManager(tmp_path, agent_id: str = "proactive-test"):
    from neurova.cognitive_layers.memory_layer.manager import MemoryManager

    return MemoryManager(
        db_path=str(tmp_path / f"{agent_id}.db"),
        agent_id=agent_id,
        neuser_id="u1",
        user_id="u1",
        enable_buffer=False,
    )


def _rememberQuiet(manager, **kwargs):
    """静默写入：关掉自动分类与自动情感分析，避免旁路依赖影响断言。"""
    kwargs.setdefault("auto_classify", False)
    kwargs.setdefault("auto_analyze_emotion", False)
    return manager.remember(**kwargs)


def _ageLastAccessed(manager, memory_id: str, days: float) -> None:
    """把指定记忆的 last_accessed_at 拨回 days 天前并落盘。"""
    mem = manager._memories[memory_id]
    mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=days)
    manager._persist_memory(mem)


def _bodyById(manager, memory_id: str):
    for mem in manager.iterBodyMemories(limit=100):
        if mem.id == memory_id:
            return mem
    return None


class TestMarkSimulatedRecall:
    """MemoryManager.markSimulatedRecall — 模拟回忆落盘"""

    def test_markSimulatedRecall_updatesTemperatureAndTimestamp(self, tmp_path):
        """RED: 升温 +boost、刷新 last_accessed_at、access_count+1，且真落盘"""
        manager = _makeManager(tmp_path)
        memory_id = _rememberQuiet(manager, content="三天前记下的部署要点", temperature=50.0)
        before = datetime.now(timezone.utc) - timedelta(days=4)
        mem = manager._memories[memory_id]
        mem.last_accessed_at = before
        manager._persist_memory(mem)

        ok = manager.markSimulatedRecall(memory_id, boost=5.0)

        assert ok is True
        row = _bodyById(manager, memory_id)
        assert row is not None
        assert row.temperature == pytest.approx(55.0)
        assert row.access_count == 1
        assert row.last_accessed_at is not None
        assert row.last_accessed_at > before

    def test_markSimulatedRecall_capsAtMax(self, tmp_path):
        """RED: 温度封顶 100，不溢出"""
        manager = _makeManager(tmp_path)
        memory_id = _rememberQuiet(manager, content="接近沸点的记忆", temperature=99.0)

        manager.markSimulatedRecall(memory_id, boost=5.0)

        row = _bodyById(manager, memory_id)
        assert row.temperature == pytest.approx(100.0)

    def test_markSimulatedRecall_missingIdReturnsFalse(self, tmp_path):
        """RED: 不存在的 id 返回 False，不抛错不插行"""
        manager = _makeManager(tmp_path)
        assert manager.markSimulatedRecall("no-such-memory", boost=5.0) is False


class TestScheduledRecallCycle:
    """定时回忆巩固 — 睡眠周期尾部调用的扫描升温"""

    def test_boostsStaleImportantMemory(self, tmp_path):
        """RED: 重要记忆 3 天未访问 → 被模拟回忆升温"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            runScheduledRecallCycle,
        )

        manager = _makeManager(tmp_path)
        stale_id = _rememberQuiet(
            manager, content="重要的旧架构决策", is_important=True, temperature=50.0
        )
        _ageLastAccessed(manager, stale_id, days=4.0)
        fresh_id = _rememberQuiet(
            manager, content="刚刚还想起的事实", is_important=True, temperature=50.0
        )

        stats = runScheduledRecallCycle(manager)

        assert stats["recalled_count"] >= 1
        assert stale_id in stats["recalled_ids"]
        assert fresh_id not in stats["recalled_ids"]
        assert _bodyById(manager, stale_id).temperature == pytest.approx(55.0)
        assert _bodyById(manager, fresh_id).temperature == pytest.approx(50.0)

    def test_normalMemoryUsesSevenDayThreshold(self, tmp_path):
        """RED: 普通记忆阈值 7 天 — 6 天不动、8 天动"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            runScheduledRecallCycle,
        )

        manager = _makeManager(tmp_path)
        six_days_id = _rememberQuiet(manager, content="六天前的普通记录", temperature=50.0)
        _ageLastAccessed(manager, six_days_id, days=6.0)
        eight_days_id = _rememberQuiet(manager, content="八天前的普通记录", temperature=50.0)
        _ageLastAccessed(manager, eight_days_id, days=8.0)

        runScheduledRecallCycle(manager)

        assert _bodyById(manager, six_days_id).temperature == pytest.approx(50.0)
        assert _bodyById(manager, eight_days_id).temperature == pytest.approx(55.0)

    def test_prioritizesHigherForgettingProbability(self, tmp_path):
        """RED: 限量 1 时，遗忘概率更高的（更久未访问）优先被回忆"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            runScheduledRecallCycle,
        )

        manager = _makeManager(tmp_path)
        colder_id = _rememberQuiet(manager, content="十五天前的重要记忆", is_important=True, temperature=40.0)
        _ageLastAccessed(manager, colder_id, days=15.0)
        warmer_id = _rememberQuiet(manager, content="四天前的重要记忆", is_important=True, temperature=80.0)
        _ageLastAccessed(manager, warmer_id, days=4.0)

        stats = runScheduledRecallCycle(manager, max_memories=1)

        assert stats["recalled_ids"] == [colder_id]
        assert _bodyById(manager, colder_id).temperature == pytest.approx(45.0)
        assert _bodyById(manager, warmer_id).temperature == pytest.approx(80.0)

    def test_skipsCrystallizedAndForgotten(self, tmp_path):
        """RED: 结晶（永久）与已遗忘记忆不进定时回忆"""
        from neurova.cognitive_layers.memory_layer.models import LifecycleStage
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            runScheduledRecallCycle,
        )

        manager = _makeManager(tmp_path)
        crystal_id = _rememberQuiet(manager, content="已结晶的永久事实", temperature=50.0)
        forgotten_id = _rememberQuiet(manager, content="已遗忘的旧事", temperature=50.0)
        for memory_id, stage in ((crystal_id, LifecycleStage.CRYSTALLIZED), (forgotten_id, LifecycleStage.FORGOTTEN)):
            mem = manager._memories[memory_id]
            mem.lifecycle_stage = stage
            mem.last_accessed_at = datetime.now(timezone.utc) - timedelta(days=30)
            manager._persist_memory(mem)

        stats = runScheduledRecallCycle(manager)

        assert crystal_id not in stats["recalled_ids"]
        assert forgotten_id not in stats["recalled_ids"]

    def test_disabledSwitchSkipsWork(self, tmp_path):
        """RED: proactive_recall.enabled=False 时整轮跳过"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            runScheduledRecallCycle,
        )
        from neurova.cognitive_layers.memory_layer.settings_config import (
            get_memory_settings,
        )

        manager = _makeManager(tmp_path)
        memory_id = _rememberQuiet(manager, content="开着也不会动的记忆", is_important=True, temperature=50.0)
        _ageLastAccessed(manager, memory_id, days=10.0)
        get_memory_settings().update({"proactive_recall.enabled": False})
        try:
            stats = runScheduledRecallCycle(manager)
            assert stats["recalled_count"] == 0
            assert _bodyById(manager, memory_id).temperature == pytest.approx(50.0)
        finally:
            get_memory_settings().reset(["proactive_recall.enabled"])


class TestContextTriggeredRecall:
    """上下文触发回忆 — 时间模式 + 情感强度"""

    def test_timePatternTriggersRecall(self, tmp_path):
        """RED: metadata.time_pattern 命中当前小时窗口的记忆被主动带出"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            contextTriggeredRecall,
        )

        manager = _makeManager(tmp_path)
        _rememberQuiet(
            manager,
            content="每天早上九点站会",
            metadata={"time_pattern": {"hour": 9}},
            temperature=60.0,
        )
        _rememberQuiet(manager, content="毫无时间规律的一句话", temperature=60.0)

        recalled = contextTriggeredRecall(
            manager, currentTime=datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc)
        )

        ids = {m["id"] for m in recalled}
        assert len(ids) >= 1
        contents = {m["content"] for m in recalled}
        assert "每天早上九点站会" in contents

    def test_emotionTriggerRespectsIntensityThreshold(self, tmp_path):
        """RED: 当前情感强度 ≥ 阈值带出同情感记忆；低于阈值不带"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            contextTriggeredRecall,
        )

        manager = _makeManager(tmp_path)
        _rememberQuiet(manager, content="上次拿奖的开心事", emotion="joy", temperature=60.0)
        _rememberQuiet(manager, content="无关中性事实", emotion="neutral", temperature=60.0)

        strong = contextTriggeredRecall(
            manager,
            currentTime=datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc),
            emotionProvider=lambda: ("joy", 0.8),
        )
        weak = contextTriggeredRecall(
            manager,
            currentTime=datetime(2026, 11, 20, 12, 0, 0, tzinfo=timezone.utc),
            emotionProvider=lambda: ("joy", 0.2),
        )

        assert "上次拿奖的开心事" in {m["content"] for m in strong}
        assert "上次拿奖的开心事" not in {m["content"] for m in weak}

    def test_mergesDedupsAndLimits(self, tmp_path):
        """RED: 时间+情感双触发去重合并，且限量 max_context_recall"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            contextTriggeredRecall,
        )

        manager = _makeManager(tmp_path)
        _rememberQuiet(
            manager,
            content="既带时间模式又带情感的记录",
            emotion="joy",
            metadata={"time_pattern": {"hour": 9}},
            temperature=60.0,
        )
        for idx in range(15):
            _rememberQuiet(
                manager, content=f"批量情感记忆{idx}", emotion="joy", temperature=60.0
            )

        recalled = contextTriggeredRecall(
            manager,
            currentTime=datetime(2026, 11, 20, 10, 0, 0, tzinfo=timezone.utc),
            emotionProvider=lambda: ("joy", 0.9),
        )

        ids = [m["id"] for m in recalled]
        assert len(ids) == len(set(ids)), "去重失败"
        assert len(recalled) <= 10


class TestTaskDrivenRecall:
    """任务驱动回忆 — 按任务描述召回经验/教训/技能/偏好"""

    def test_recallsByCategoryBuckets(self, tmp_path):
        """RED: 按任务关键词召回，结果按经验/教训/技能/偏好分桶"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            taskDrivenRecall,
        )

        manager = _makeManager(tmp_path)
        _rememberQuiet(manager, content="部署过同样的 k8s 集群", category="experience")
        _rememberQuiet(manager, content="反思：直接删 pod 会雪崩", category="reflection")
        _rememberQuiet(manager, content="kubectl 滚动更新命令模板", category="tool_usage")
        _rememberQuiet(manager, content="用户偏好中文回复", category="user_preference")
        _rememberQuiet(manager, content="完全无关的菜谱", category="conversation")

        result = taskDrivenRecall(manager, taskDescription="k8s 集群部署更新")

        assert isinstance(result, dict)
        flat = [c for bucket in result.values() for c in bucket]
        assert "部署过同样的 k8s 集群" in flat or any("k8s" in c for c in flat)
        assert "完全无关的菜谱" not in flat

    def test_emptyTaskReturnsEmptyBuckets(self, tmp_path):
        """RED: 空任务描述返回空桶，不抛错"""
        from neurova.cognitive_layers.memory_layer.proactive_recall import (
            taskDrivenRecall,
        )

        manager = _makeManager(tmp_path)
        result = taskDrivenRecall(manager, taskDescription="")
        assert result == {}


class TestWiring:
    """接线钉子：睡眠周期尾部与上下文注入器确实消费主动回忆"""

    def test_idleTrackerTailRunsScheduledRecall(self, tmp_path):
        """RED: idle_tracker 巩固尾部调用 runScheduledRecallCycle 并真实升温"""
        from neurova.core.idle_tracker import IdleTimeTracker

        manager = _makeManager(tmp_path)
        memory_id = _rememberQuiet(
            manager, content="关机前的重要旧账", is_important=True, temperature=50.0
        )
        _ageLastAccessed(manager, memory_id, days=9.0)

        tracker = IdleTimeTracker()
        tracker._memory_manager = manager
        tracker._run_scheduled_recall()

        assert _bodyById(manager, memory_id).temperature == pytest.approx(55.0)

    def test_injectorMergesProactiveRecall(self, tmp_path, monkeypatch):
        """RED: retrieve_memories 合并上下文触发召回结果并去重"""
        from neurova.context.injector import UnifiedContextInjector

        manager = _makeManager(tmp_path)
        injector = UnifiedContextInjector(
            memory_manager=manager, enable_cache=False, enable_compression=False
        )
        proactive_row = {
            "id": "proactive-1",
            "content": "时间模式带出的记忆",
            "temperature": 88.0,
            "is_crystallized": False,
        }
        monkeypatch.setattr(
            "neurova.cognitive_layers.memory_layer.proactive_recall.contextTriggeredRecall",
            lambda *args, **kwargs: [proactive_row],
        )

        rows = injector.retrieve_memories(query="随便", limit=5)

        assert proactive_row["id"] in {r["id"] for r in rows}
