# -*- coding: utf-8 -*-
"""D5 温度语义修复（2026-11-24）红绿灯判据。

覆盖：R1 出生温度 60 / R2 比例回温 k=0.25 / R3+R9 冻结门 95（具名常量）/
R5 同轮命中去重 / R8 温度分布统计。
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.temperature import (
    TemperatureEngine,
    apply_recall_gain,
)


# ---------------------------------------------------------------------------
# R3 + R9：冻结门 95（具名常量）
# ---------------------------------------------------------------------------

def _iso(days_ago: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()


class TestR3FreezeGate:
    def test_constant_is_95(self):
        from neurova.cognitive_layers.memory_layer.temperature import DECAY_FREEZE_TEMP
        assert DECAY_FREEZE_TEMP == 95.0

    def test_at_95_no_decay(self):
        out = TemperatureEngine().on_decay(95.0, last_accessed=_iso(10))
        assert out["new_temp"] == 95.0 and out["decay_amount"] == 0.0

    def test_above_95_no_decay(self):
        out = TemperatureEngine().on_decay(99.0, last_accessed=_iso(30))
        assert out["new_temp"] == 99.0

    def test_below_95_decays(self):
        out = TemperatureEngine().on_decay(94.9, last_accessed=_iso(10), importance=0.3)
        assert out["new_temp"] < 94.9 and out["decay_amount"] > 0.0

    def test_old_80_band_no_longer_freezes(self):
        out = TemperatureEngine().on_decay(82.0, last_accessed=_iso(10), importance=0.3)
        assert out["new_temp"] < 82.0, "82° 在旧门下被冻结，新门 95 下必须衰减"

    def test_crystallized_still_exempt_at_any_temp(self):
        out = TemperatureEngine().on_decay(50.0, last_accessed=_iso(30), is_crystallized=True)
        assert out["new_temp"] == 50.0


# ---------------------------------------------------------------------------
# R2：比例回温
# ---------------------------------------------------------------------------

class TestR2ProportionalGain:
    def test_cold_memory_first_hit(self):
        assert apply_recall_gain(20.0) == pytest.approx(40.0)

    def test_hot_memory_marginal(self):
        assert apply_recall_gain(95.0) == pytest.approx(96.25)

    def test_bounded_by_100(self):
        assert apply_recall_gain(99.9) == pytest.approx(99.925)
        assert apply_recall_gain(100.0) == 100.0

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_HIT_GAIN", "0.5")
        assert apply_recall_gain(20.0) == pytest.approx(60.0)

    def test_env_invalid_falls_back(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_MEMORY_HIT_GAIN", "oops")
        assert apply_recall_gain(20.0) == pytest.approx(40.0)


# ---------------------------------------------------------------------------
# R1：出生温度 60
# ---------------------------------------------------------------------------

class TestR1BirthTemperature:
    def test_memory_model_default_is_60(self):
        from neurova.cognitive_layers.memory_layer.models import Memory
        mem = Memory.from_dict({"id": "m1", "content": "c"})
        assert mem.temperature == 60.0

    def test_memory_model_field_default_is_60(self):
        from neurova.cognitive_layers.memory_layer.models import Memory
        import inspect
        sig = inspect.signature(Memory)
        assert sig.parameters["temperature"].default == 60.0

    def test_schema_default_is_60(self, tmp_path):
        manager = MemoryManager(db_path=str(tmp_path / "m.db"), agent_id="r1")
        conn = sqlite3.connect(str(manager._persist_db_path))
        row = conn.execute("PRAGMA table_info(memories)").fetchall()
        conn.close()
        temp_col = [r for r in row if r[1] == "temperature"][0]
        # SQLite 的 dflt_value 以文本返回（"60.0"），转 float 再比
        assert float(temp_col[4]) == 60.0, "建表默认值必须是 60（dflt_value 列）"


# ---------------------------------------------------------------------------
# R2 + R5：creditRecallHits 集成（比例回温 + 同轮去重）
# ---------------------------------------------------------------------------

def _seed_memory(manager: MemoryManager, memory_id: str, temperature: float) -> None:
    conn = sqlite3.connect(str(manager._persist_db_path))
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO memories (id, content, temperature, agent_id, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (memory_id, "内容", temperature, manager._agent_id, now, now),
    )
    conn.commit()
    conn.close()


def _read_temp(manager: MemoryManager, memory_id: str) -> float:
    conn = sqlite3.connect(str(manager._persist_db_path))
    row = conn.execute(
        "SELECT temperature FROM memories WHERE id = ?", (memory_id,)
    ).fetchone()
    conn.close()
    return float(row[0])


@pytest.fixture()
def credit_manager(tmp_path):
    from neurova.core.cancel_token import clearTurnCancelToken

    clearTurnCancelToken()
    manager = MemoryManager(db_path=str(tmp_path / "credit.db"), agent_id="credit")
    yield manager
    clearTurnCancelToken()


class TestR2R5CreditRecall:
    def test_proportional_credit_on_hit(self, credit_manager):
        manager = credit_manager
        _seed_memory(manager, "m1", 20.0)
        manager.creditRecallHits(["m1"])
        assert _read_temp(manager, "m1") == pytest.approx(40.0)

    def test_same_turn_double_credit_counts_once(self, credit_manager):
        from neurova.core.cancel_token import resetTurnCancelToken

        manager = credit_manager
        _seed_memory(manager, "m2", 20.0)
        resetTurnCancelToken()
        manager.creditRecallHits(["m2"])
        manager.creditRecallHits(["m2"])
        manager.creditRecallHits(["m2"])
        assert _read_temp(manager, "m2") == pytest.approx(40.0), "同轮重复命中只记一次"

    def test_new_turn_counts_again(self, credit_manager):
        from neurova.core.cancel_token import resetTurnCancelToken

        manager = credit_manager
        _seed_memory(manager, "m3", 20.0)
        resetTurnCancelToken()
        manager.creditRecallHits(["m3"])
        first = _read_temp(manager, "m3")
        resetTurnCancelToken()  # 新的一轮
        manager.creditRecallHits(["m3"])
        second = _read_temp(manager, "m3")
        assert second > first, "跨轮命中应再次回温"

    def test_no_turn_context_credits_directly(self, credit_manager):
        manager = credit_manager
        _seed_memory(manager, "m4", 20.0)
        manager.creditRecallHits(["m4"])
        manager.creditRecallHits(["m4"])
        # 无轮次上下文（管理端/巡检等）：保持直接记账，不去重
        assert _read_temp(manager, "m4") == pytest.approx(40.0 + (100 - 40) * 0.25)


# ---------------------------------------------------------------------------
# R8：温度分布统计
# ---------------------------------------------------------------------------

class TestR8TemperatureDistribution:
    def test_distribution_bands(self, tmp_path):
        manager = MemoryManager(db_path=str(tmp_path / "dist.db"), agent_id="dist")
        for i, temp in enumerate([10.0, 30.0, 60.0, 90.0, 97.0]):
            _seed_memory(manager, f"d{i}", temp)
        dist = manager.temperature_distribution()
        assert dist["total"] == 5
        assert dist["bands"]["<20"] == 1
        assert dist["bands"]["20-49"] == 1
        assert dist["bands"]["50-79"] == 1
        assert dist["bands"]["80-94"] == 1
        assert dist["bands"][">=95"] == 1
        assert dist["frozen"] == 1
        assert dist["avg"] == pytest.approx((10 + 30 + 60 + 90 + 97) / 5)

    def test_distribution_empty(self, tmp_path):
        manager = MemoryManager(db_path=str(tmp_path / "empty.db"), agent_id="empty")
        dist = manager.temperature_distribution()
        assert dist["total"] == 0 and dist["avg"] is None


# ---------------------------------------------------------------------------
# R7：融合召回命中记账
# ---------------------------------------------------------------------------

class TestR7FusionRecallCredit:
    def test_credit_recalled_memories_warms_temperature(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.neurova_recall import (
            NeurovaRecallEngine,
            RecalledMemory,
        )

        manager = MemoryManager(db_path=str(tmp_path / "r7.db"), agent_id="r7")
        _seed_memory(manager, "m7", 20.0)
        engine = object.__new__(NeurovaRecallEngine)
        engine.memory_manager = manager

        engine._creditRecalledMemories(
            [RecalledMemory(memory_id="m7", score=1.0)]
        )
        assert _read_temp(manager, "m7") == pytest.approx(40.0)

    def test_credit_failure_does_not_raise(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.neurova_recall import (
            NeurovaRecallEngine,
            RecalledMemory,
        )

        manager = MemoryManager(db_path=str(tmp_path / "r7b.db"), agent_id="r7b")
        engine = object.__new__(NeurovaRecallEngine)
        engine.memory_manager = manager
        # 不存在的 id：creditRecallHits 内部跳过，不外抛
        engine._creditRecalledMemories([RecalledMemory(memory_id="no-such", score=1.0)])

    def test_empty_results_noop(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.neurova_recall import (
            NeurovaRecallEngine,
        )

        manager = MemoryManager(db_path=str(tmp_path / "r7c.db"), agent_id="r7c")
        engine = object.__new__(NeurovaRecallEngine)
        engine.memory_manager = manager
        engine._creditRecalledMemories([])  # 空结果零副作用
