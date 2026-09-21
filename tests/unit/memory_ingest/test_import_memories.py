# -*- coding: utf-8 -*-
"""MemoryManager.import_memories：回填历史与运行期写入是两套语义（设计 §4）。

导入不得跑内容门、不喂关键词倒排、不同步 MoE 向量库——历史记忆不该被当成
"刚发生的经验"重新定温或裁决；同时必须落进内存表，否则导入完当前实例看不见。
"""
from pathlib import Path

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import MemoryOrigin
from neurova.memory_ingest.bundle.records import MemoryRecord

_RUN = "nvimp-test-1"


def _manager(tmp_path: Path) -> MemoryManager:
    return MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))


def _record(seq: int, content: str) -> MemoryRecord:
    return MemoryRecord(identity_key=f"ik-{seq}", content=content, memory_type="semantic",
                        category="general", origin="owner", importance=60.0,
                        ts=f"2026-05-01T10:00:{seq:02d}+00:00")


def test_import_memories_visible_without_restart_and_keeps_history_ts(tmp_path: Path):
    manager = _manager(tmp_path)

    outcome = manager.import_memories([_record(1, "历史记忆一")], ingest_run_id=_RUN)

    stored = next(m for m in manager._memories.values() if m.content == "历史记忆一")
    assert (outcome["added"], outcome["skipped"]) == (1, 0)
    assert stored.origin is MemoryOrigin.OWNER
    assert stored.created_at.isoformat().startswith("2026-05-01")   # 不被 now() 覆盖
    assert stored.temperature == 100.0
    assert stored.metadata["ingest_run_id"] == _RUN


def test_import_memories_is_idempotent(tmp_path: Path):
    manager = _manager(tmp_path)
    records = [_record(1, "同一内容"), _record(2, "另一条")]

    first = manager.import_memories(records, ingest_run_id=_RUN)
    second = manager.import_memories(records, ingest_run_id=_RUN)

    assert (first["added"], first["skipped"]) == (2, 0)
    assert (second["added"], second["skipped"]) == (0, 2)
    assert len(manager._memories) == 2


def test_import_memories_persists_across_instances(tmp_path: Path):
    """落盘同一份库：重启后仍可见（走的是既有 upsert，不是第二套写路径）。"""
    first = _manager(tmp_path)
    first.import_memories([_record(1, "跨实例可见")], ingest_run_id=_RUN)
    first.close()

    reopened = MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))
    reopened._load_from_db()

    assert any(m.content == "跨实例可见" for m in reopened._memories.values())


def test_import_does_not_trigger_runtime_side_effects(tmp_path: Path, monkeypatch):
    manager = _manager(tmp_path)
    touched = []
    monkeypatch.setattr(manager, "_sync_runtime_vector_store",
                        lambda *a, **k: touched.append("vector"))
    monkeypatch.setattr("neurova.cognitive_layers.memory_layer.semantic_search"
                        ".get_semantic_search",
                        lambda: (_ for _ in ()).throw(AssertionError("关键词索引被写入")))

    manager.import_memories([_record(1, "无副作用")], ingest_run_id=_RUN)

    assert touched == []
    assert manager._content_index == {}          # 内容门索引未被填充
    assert manager._stats.get("remember_count", 0) == 0


def test_unknown_memory_type_keeps_declaration_instead_of_silent_swap(tmp_path: Path):
    """沿用 012 的口径：未知类型不静默换掉，原始声明留痕。"""
    manager = _manager(tmp_path)
    rec = MemoryRecord(identity_key="ik-x", content="奇型记忆", memory_type="vibes",
                       category="general", origin="owner", importance=50.0,
                       ts="2026-05-01T10:00:00+00:00")

    manager.import_memories([rec], ingest_run_id=_RUN)

    stored = next(m for m in manager._memories.values() if m.content == "奇型记忆")
    assert stored.metadata.get("_declared_memory_type") == "vibes"


def test_import_requires_run_id(tmp_path: Path):
    manager = _manager(tmp_path)

    with pytest.raises(ValueError, match="ingest_run_id"):
        manager.import_memories([_record(1, "x")], ingest_run_id="")


def test_delete_ingested_memories_rolls_back_exactly_that_run(tmp_path: Path):
    manager = _manager(tmp_path)
    manager.import_memories([_record(1, "本批")], ingest_run_id=_RUN)
    manager.remember("运行期记忆", category="general")

    removed = manager.delete_ingested_memories(_RUN)

    assert removed == 1
    assert all(m.metadata.get("ingest_run_id") != _RUN for m in manager._memories.values())
    assert any(m.content == "运行期记忆" for m in manager._memories.values())


def test_undo_removes_the_row_even_when_called_from_another_scope(tmp_path: Path):
    """撤销按**行自带**三元组删盘：CLI 在实例默认作用域调用，导入却可能发生在别的上下文。

    实测复现：在 u1 作用域导入、在默认作用域撤销——内存里删掉了，盘上的行还在
    （`_delete_persisted_memory` 按**当前**生效三元组删，u1 那行删不掉），重启即复活。
    """
    manager = _manager(tmp_path)
    with manager.request_scope("default", "u1"):
        manager.import_memories([_record(1, "u1 的历史")], ingest_run_id=_RUN)

    removed = manager.delete_ingested_memories(_RUN)
    manager.close()

    reopened = MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))

    assert removed == 1
    assert reopened._memories == {}


def test_undo_does_not_touch_rows_outside_the_batch(tmp_path: Path):
    """按行自带三元组删，不等于放开越权：只删本批的行，其他作用域的行一条不动。"""
    manager = _manager(tmp_path)
    with manager.request_scope("default", "u1"):
        manager.import_memories([_record(1, "u1 的历史")], ingest_run_id=_RUN)
    with manager.request_scope("default", "u2"):
        manager.import_memories([_record(2, "u2 的历史")], ingest_run_id="nvimp-other")

    removed = manager.delete_ingested_memories(_RUN)
    manager.close()
    reopened = MemoryManager(db_path=str(tmp_path / "memory" / "memory.db"))

    assert removed == 1
    assert [(m.content, m.user_id) for m in reopened._memories.values()] == [("u2 的历史", "u2")]


def test_imported_history_is_not_instantly_forgotten_by_idle_time(tmp_path: Path):
    """回填的历史不该因为"事件发生得早"就被判为空闲半年。

    根因：`run_decay_cycle` 的 days_idle 取 `last_accessed_at or created_at`，而导入行
    只写了历史 created_at（事件时刻），于是"系统刚获知"被算成"闲置了半年"——实测
    days_idle=200 时温度 10 直接落 FORGOTTEN、30 落 ARCHIVED。
    事件时刻与获知时刻是两个时刻：created_at 记事件，last_accessed_at 记系统获知
    （导入时刻）——在**产生这个非法状态的上游**（导入路径）定标，而不是去改衰减消费方。
    """
    manager = _manager(tmp_path)
    manager.import_memories(
        [MemoryRecord(identity_key="ik-old", content="半年前的历史", memory_type="semantic",
                      category="general", origin="owner", importance=50.0, temperature=10.0,
                      ts="2026-03-01T10:00:00+00:00")], ingest_run_id=_RUN)
    stored = next(m for m in manager._memories.values() if m.content == "半年前的历史")

    manager.run_decay_cycle(hours=1.0, rate=1.0)

    assert stored.created_at.isoformat().startswith("2026-03-01")   # 事件时刻照原样保留
    assert stored.last_accessed_at is not None                      # 获知时刻被定标
    assert stored.lifecycle_stage.value == "active"                 # 不是被闲置时间判死
