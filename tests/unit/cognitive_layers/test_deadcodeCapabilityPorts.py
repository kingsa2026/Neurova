# -*- coding: utf-8 -*-
"""死码退役批（2026-11-14）取长补短的落点判据。

relation_mixin / forgetting_recovery_storage_mixin 退役时，其全仓唯一实装的能力
先并入活体再删（修复教义第 7 条，裁定见 docs/05-reports/全库代码审计报告_2026-11-14.md §5）。
本档钉住并入后的能力不回退：
- RelationModule.graph_density / most_connected（自 relation_mixin 迁入）
- MemoryManager.cleanup_old_archived / get_forgetting_statistics（自
  forgetting_recovery_storage_mixin 迁入；恢复计数为进程内累计）
"""
from __future__ import annotations

import datetime

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.modules.relation_module import (
    RelationModule,
    RelationType,
)

pytestmark = pytest.mark.timeout(120)


def _relationModule() -> RelationModule:
    module = RelationModule()
    module.init()
    return module


def testGraphDensityIsEmptyGraphZero():
    assert _relationModule().graph_density() == 0.0


def testGraphDensityTwoEdgesAmongThreeNodes():
    module = _relationModule()
    module.add_relation("a", "b", RelationType.CAUSE, strength=0.9)
    module.add_relation("b", "c", RelationType.SIMILAR, strength=0.8)
    # 3 节点无向完全图可能边数 = 3；实有 2 条
    assert module.graph_density() == pytest.approx(2 / 3)


def testGraphDensityCompleteTriangleIsOne():
    module = _relationModule()
    module.add_relation("a", "b", RelationType.CAUSE)
    module.add_relation("b", "c", RelationType.CAUSE)
    module.add_relation("a", "c", RelationType.CAUSE)
    assert module.graph_density() == pytest.approx(1.0)


def testMostConnectedRanksByDegree():
    module = _relationModule()
    module.add_relation("hub", "a", RelationType.CAUSE)
    module.add_relation("hub", "b", RelationType.CAUSE)
    module.add_relation("a", "b", RelationType.SIMILAR)
    ranked = module.most_connected(limit=2)
    assert ranked[0] == {"memory_id": "hub", "degree": 2}
    assert ranked[1]["memory_id"] in {"a", "b"}


def testCleanupOldArchivedPurgesOnlyStaleArchived(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    old_id = manager.remember("陈年归档", category="fact", importance=0.5)
    fresh_id = manager.remember("新鲜归档", category="fact", importance=0.5)
    manager.archive_memory(old_id)
    manager.archive_memory(fresh_id)
    # 把其中一条的 updated_at 拨回 2020 年，另一条保持现在
    manager._memories[old_id].updated_at = datetime.datetime(2020, 1, 1, tzinfo=datetime.timezone.utc)

    purged = manager.cleanup_old_archived(days=30)

    assert purged == 1
    assert old_id not in manager._memories
    assert fresh_id in manager._memories
    assert manager._memories[fresh_id].lifecycle_stage.value == "archived"


def testForgettingStatisticsCountsStagesAndRecoveries(tmp_path):
    manager = MemoryManager(db_path=str(tmp_path / "mem.db"), agent_id="agent_a")
    archived_id = manager.remember("归档后恢复", category="fact", importance=0.5)
    forgotten_id = manager.remember("软删不恢复", category="fact", importance=0.5)
    manager.archive_memory(archived_id)
    manager.forget(forgotten_id, soft=True)
    manager.recover_from_archive(archived_id)

    stats = manager.get_forgetting_statistics()

    assert stats["recovery_count"] == 1
    assert stats["recovery_from_archive"] == 1
    assert stats["recovery_from_soft_delete"] == 0
    assert stats["stage_distribution"].get("archived", 0) == 0
    assert stats["stage_distribution"].get("forgotten") == 1
    assert stats["stage_distribution"].get("active") == 1
    assert stats["recovery_rate"] == pytest.approx(1 / 2)
