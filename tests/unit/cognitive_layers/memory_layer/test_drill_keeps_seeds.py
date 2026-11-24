# -*- coding: utf-8 -*-
"""D7 评测暴露的 Phase 2 钻取缺陷：五个钻取方法都 `return results[:limit]`——
扩芒为空时把 Phase 1 的相关种子整个丢掉。

"X是什么"类高频问句全部走 EXPLORE 钻取；语料无新类别记忆时返回空，
召回恒空（D7 三态基准 MRR≈0 的根因）。修复后：种子在前、扩芒补后、
按 id 去重、截断到 limit。
"""
from __future__ import annotations

from neurova.cognitive_layers.memory_layer.neurova_recall import (
    NeurovaRecallEngine,
    RecalledMemory,
)


def _engine() -> NeurovaRecallEngine:
    engine = object.__new__(NeurovaRecallEngine)
    engine.memory_manager = None  # 钻取在无管理器时也应保留种子
    return engine


def _mem(rid: str) -> RecalledMemory:
    return RecalledMemory(memory_id=rid, score=1.0)


def test_explore_keeps_seeds_when_expansion_empty():
    engine = _engine()
    seeds = [_mem("s1"), _mem("s2")]
    out = engine._drill_explore("这是什么", seeds, limit=5)
    assert [m.memory_id for m in out] == ["s1", "s2"]


def test_explore_appends_new_category_after_seeds():
    engine = _engine()

    class _Mgr:
        def get_all_memories(self, scoped=True):
            return [
                {"id": "s1", "content": "种子", "category": "general"},
                {"id": "new1", "content": "新类别", "category": "knowledge"},
            ]

    engine.memory_manager = _Mgr()
    seeds = [_mem("s1")]
    out = engine._drill_explore("这是什么", seeds, limit=5)
    assert [m.memory_id for m in out] == ["s1", "new1"]


def test_deepen_keeps_seeds_when_expansion_empty():
    engine = _engine()
    seeds = [_mem("s1")]
    out = engine._drill_deepen("为什么", seeds, limit=5)
    assert [m.memory_id for m in out] == ["s1"]


def test_connect_keeps_seeds_when_expansion_empty():
    engine = _engine()
    seeds = [_mem("s1"), _mem("s2")]
    out = engine._drill_connect("关联", seeds, limit=5)
    assert [m.memory_id for m in out] == ["s1", "s2"]


def test_contrast_keeps_seeds_when_expansion_empty():
    engine = _engine()
    seeds = [_mem("s1")]
    out = engine._drill_contrast("对比", seeds, limit=5)
    assert [m.memory_id for m in out] == ["s1"]


def test_validate_keeps_seeds_when_expansion_empty():
    engine = _engine()
    seeds = [_mem("s1")]
    out = engine._drill_validate("确认", seeds, limit=5)
    assert [m.memory_id for m in out] == ["s1"]


def test_merged_results_dedupe_and_cap_by_limit():
    engine = _engine()
    seeds = [_mem("s1"), _mem("s2")]
    expansions = [_mem("s2"), _mem("new1"), _mem("new2")]
    out = engine._merge_drill_results(seeds, expansions, limit=3)
    assert [m.memory_id for m in out] == ["s1", "s2", "new1"]
