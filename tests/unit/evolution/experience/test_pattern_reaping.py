"""017-b · 结晶模式的淘汰路径（红绿灯 TDD）。

017-a 挡住了"自述成功率换来永久豁免"（温度封顶在豁免区之下），但如果没有任何
东西真的衰减它们、也没有任何读侧看不见冷掉的条目，那只是把数字改小而已。
本文件钉的是"淘汰真的发生、且看得见"：

1. `reap_stale_patterns()` 按闲置天数给结晶模式降温（写入方 = post_chat 复盘通道）；
2. 冷到档下的模式**退出注入**（读侧带最低温度过滤）——淘汰必须可观测；
3. 反向锁：刚被取用（006 记账会刷新 `updated_at`）与仍热的模式不得被扫掉；
4. 冷档只作用于结晶模式，普通语义/情景记忆不受这条规则影响。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from neurova.cognitive_layers.memory_layer.cognitive_storage_engine import (
    CognitiveStorageEngine,
    MemoryType,
    StorageLayer,
    UnifiedMemoryNode,
)
from neurova.cognitive_layers.memory_layer.pattern_crystallizer import (
    COLD_PATTERN_TEMPERATURE,
)


def _pattern(content: str, temperature: float) -> UnifiedMemoryNode:
    return UnifiedMemoryNode(
        content=content,
        memory_type=MemoryType.PATTERN,
        category="crystallized",
        temperature=temperature,
        layer=StorageLayer.L1_HOT,
    )


def _store_flushed(engine, node) -> str:
    """入库并立刻落 L1 —— 冷档判据读的是 L1 行的 updated_at/temperature。"""
    nid = engine.store(node)
    engine._flush_l0_to_l1()
    return nid


def _age_days(engine: CognitiveStorageEngine, node_id: str, days: int) -> None:
    stamp = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    engine._db.execute("UPDATE memories SET updated_at = ? WHERE id = ?", (stamp, node_id))
    engine._db.commit()


@pytest.fixture()
def engine(tmp_path):
    eng = CognitiveStorageEngine(agent_id="cse-017", data_dir=str(tmp_path / "cse"))
    yield eng
    eng._db.close()


@pytest.fixture()
def crystallizer(engine):
    from neurova.cognitive_layers.memory_layer.pattern_crystallizer import PatternCrystallizer

    return PatternCrystallizer(engine=engine)


class TestReapDecaysIdlePatterns:
    def test_idle_pattern_gets_colder(self, engine, crystallizer):
        nid = _store_flushed(engine, _pattern("pattern_idle_flow", 70.0))
        _age_days(engine, nid, days=40)
        before = engine._db.execute(
            "SELECT temperature FROM memories WHERE id = ?", (nid,)
        ).fetchone()[0]
        summary = crystallizer.reap_stale_patterns(idle_days=30.0)
        after = engine._db.execute(
            "SELECT temperature FROM memories WHERE id = ?", (nid,)
        ).fetchone()[0]
        assert summary["decayed"] == 1
        assert after < before, "闲置 40 天的结晶模式必须被降温"

    def test_recently_used_pattern_is_left_alone(self, engine, crystallizer):
        """反向锁：刚被取用的模式（006 记账刷新 updated_at）不得被扫掉。"""
        nid = _store_flushed(engine, _pattern("pattern_hot_flow", 70.0))
        engine.retrieve("pattern_hot_flow", limit=5)
        summary = crystallizer.reap_stale_patterns(idle_days=30.0)
        assert summary["decayed"] == 0
        row = engine._db.execute(
            "SELECT temperature FROM memories WHERE id = ?", (nid,)
        ).fetchone()[0]
        assert row == pytest.approx(80.0), "检索记账应把它抬到 70+10"

    def test_other_memory_types_are_not_touched(self, engine, crystallizer):
        nid = _store_flushed(engine, UnifiedMemoryNode(
            content="semantic_fact_about_user", memory_type=MemoryType.SEMANTIC,
            category="general", layer=StorageLayer.L1_HOT, temperature=70.0,
        ))
        _age_days(engine, nid, days=400)
        crystallizer.reap_stale_patterns(idle_days=30.0)
        row = engine._db.execute(
            "SELECT temperature FROM memories WHERE id = ?", (nid,)
        ).fetchone()[0]
        assert row == 70.0, "冷档规则只作用于结晶模式"


class TestColdPatternsLeaveInjection:
    def test_cold_pattern_is_not_retrievable(self, engine, crystallizer):
        nid = _store_flushed(engine, _pattern("pattern_dying_flow", 25.0))
        _age_days(engine, nid, days=400)
        crystallizer.reap_stale_patterns(idle_days=30.0)
        hits = engine.retrieve(
            "pattern_dying_flow", limit=5,
            filters={"memory_type": "pattern", "category": "crystallized",
                     "min_temperature": COLD_PATTERN_TEMPERATURE},
        )
        assert hits == [], "冷到档下的结晶模式必须退出注入"

    def test_warm_pattern_still_retrievable(self, engine):
        _store_flushed(engine, _pattern("pattern_alive_flow", 60.0))
        hits = engine.retrieve(
            "pattern_alive_flow", limit=5,
            filters={"memory_type": "pattern", "category": "crystallized",
                     "min_temperature": COLD_PATTERN_TEMPERATURE},
        )
        assert [n.content for n in hits] == ["pattern_alive_flow"]

    def test_retrieve_path_applies_the_floor(self, engine, crystallizer, tmp_path):
        """注入读路径（crystallizer.search）必须带上冷档过滤，否则淘汰只是写在纸上。"""
        _store_flushed(engine, _pattern("pattern_dying_flow", COLD_PATTERN_TEMPERATURE - 0.1))
        _store_flushed(engine, _pattern("pattern_alive_flow", 60.0))
        found = [item["content"] for item in crystallizer.retrieve("pattern", limit=10)]
        assert found == ["pattern_alive_flow"]

    def test_floor_filter_does_not_hide_warm_patterns(self, engine, crystallizer):
        _store_flushed(engine, _pattern("pattern_alive_flow", COLD_PATTERN_TEMPERATURE + 0.1))
        assert len(crystallizer.retrieve("pattern", limit=10)) == 1
