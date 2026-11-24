# -*- coding: utf-8 -*-
"""D5-R4：睡眠衰减必须用真实 last_accessed_at，而非 created_at。

红灯依据：sleep.py:472 把 `memory.created_at` 当 `last_accessed` 传给
on_decay——"昨天刚访问过但创建于一年前"的记忆会被按一年闲置重罚，
"创建于今天但从未访问"的记忆反而零衰减，方向完全相反。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from neurova.cognitive_layers.memory_layer.sleep import (
    MemoryRecord,
    SleepConsolidation,
)


def _iso(days_ago: float) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days_ago)


def test_memory_record_carries_last_accessed():
    la = _iso(40)
    rec = MemoryRecord.from_dict(
        {"id": "a", "content": "c", "created_at": _iso(0).isoformat(),
         "last_accessed_at": la.isoformat()}
    )
    assert rec.last_accessed_at is not None
    assert abs((rec.last_accessed_at - la).total_seconds()) < 1.0


def test_memory_record_last_accessed_defaults_none():
    rec = MemoryRecord.from_dict({"id": "a", "content": "c"})
    assert rec.last_accessed_at is None


def test_sleep_decay_uses_last_accessed_not_created():
    now = _iso(0)
    # A：今天创建、40 天前访问过 → 真实闲置 40 天，应重衰减
    a = MemoryRecord(id="a", content="apple banana", temperature=80.0,
                     importance=0.3, created_at=now, last_accessed_at=_iso(40))
    # B：40 天前创建、今天访问过 → 真实闲置 ~0，应不衰减
    b = MemoryRecord(id="b", content="cherry date", temperature=80.0,
                     importance=0.3, created_at=_iso(40), last_accessed_at=now)
    sc = SleepConsolidation(similarity_threshold=0.99, decay_rate=0.1)
    out = {r.id: r.temperature for r in sc.apply_sleep_decay([a, b])}
    assert out["a"] < 80.0, "40 天未访问的记忆必须衰减"
    assert out["b"] == 80.0, "今天访问过的记忆不得衰减（idle<1 天门）"


def test_sleep_decay_null_last_accessed_falls_back_to_created():
    # 从未访问（NULL）：回退 created_at 计闲置——保持可衰减
    rec = MemoryRecord(id="c", content="echo foxtrot", temperature=80.0,
                       importance=0.3, created_at=_iso(40), last_accessed_at=None)
    sc = SleepConsolidation(similarity_threshold=0.99, decay_rate=0.1)
    out = {r.id: r.temperature for r in sc.apply_sleep_decay([rec])}
    assert out["c"] < 80.0, "从未访问的旧记忆按创建时间计闲置，必须衰减"
