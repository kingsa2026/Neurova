"""Issue #72 · 导入的历史记忆声明取代时，旧证据必须真的让位（红绿灯 TDD）。

断链形状：`MemoryRecord.supersedes`（源库 `supersedes_key`）= "这条新说法取代了谁"，
转换器一路把它搬进 `metadata["supersedes"]`，然后**没有任何读方**——
旧记忆照旧是 active，`recall` 会把新旧两条一起端出来。这正是审计 §5.3 说的
"新证据无法在记忆层取代旧证据"：写得进去、读不出来。

本文件锁定的契约：
- 声明取代的旧行，按内容身份（normalized_key）在本作用域内定位，并软遗忘（FORGOTTEN）；
  软遗忘是既有语义（可恢复、不删数据），不新造第二种"作废"。
- 旧行找不到时**如实申报**（计数进读数），不静默当成功——不然"取代了"又是一句空话。
- 软遗忘后，同内容重新学到必须能落新行（内容门既有契约，不能被取代路径破坏）。
"""

from __future__ import annotations

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.memory_layer.models import LifecycleStage
from neurova.memory_ingest.bundle.records import MemoryRecord


@pytest.fixture()
def manager(tmp_path):
    m = MemoryManager(
        db_path=str(tmp_path / "mem.db"),
        agent_id="ingest-agent",
        neuser_id="neu",
        user_id="u1",
        enable_buffer=False,
    )
    yield m
    m.close()


def _record(key: str, content: str, *, supersedes: str = "") -> MemoryRecord:
    return MemoryRecord(
        identity_key=key, content=content, memory_type="semantic", category="knowledge",
        origin="owner", importance=70.0, ts="2026-05-01T10:00:00+00:00",
        supersedes=supersedes,
    )


class TestDeclaredSupersedeTakesEffect:
    def test_oldEvidenceIsRetiredWhenNewOneDeclaresIt(self, manager):
        oldId = manager.remember("用户偏好浅色模式", category="user_preference")
        # 新说法与旧说法内容不同（改名/改值），但它声明取代的是同一件事的旧行
        manager.import_memories(
            [_record("mem#2", "用户偏好深色模式", supersedes="用户偏好浅色模式")],
            ingest_run_id="run-1",
        )

        assert manager.get_memory(oldId)["lifecycle_stage"] == LifecycleStage.FORGOTTEN.value, \
            "被声明取代的旧记忆必须让位，否则新旧两条会一起被召回"

    def test_recallNoLongerReturnsTheSupersededRow(self, manager):
        oldId = manager.remember("用户偏好浅色模式", category="user_preference")
        manager.import_memories(
            [_record("mem#2", "用户偏好深色模式", supersedes="用户偏好浅色模式")],
            ingest_run_id="run-1",
        )

        ids = [m["id"] for m in manager.recall("用户偏好", limit=10)]

        assert oldId not in ids

    def test_unresolvedDeclarationIsReportedNotSwallowed(self, manager):
        """取代目标找不到：如实申报（读数可见），不静默当成功。"""
        report = manager.import_memories(
            [_record("mem#3", "无人认领的新说法", supersedes="库里根本没有这句")],
            ingest_run_id="run-2",
        )

        assert report["superseded"] == []
        assert report["supersede_unresolved"] == ["库里根本没有这句"]
        assert manager._stats["supersede_unresolved_count"] == 1

    def test_unresolvedDeclarationIsVisibleAtTheReadingSurface(self, manager):
        """申报"找不到目标"要出现在**读取面**上，不能只有测试读私有 `_stats`。

        只写不读的读数等于没有读数：`/v1/memory/stats` 读的是 `get_stats()`，
        导入侧累计了这个数却没接到那条读路径，用户与运维都看不见
        "有取代声明落了空"。判据取的是公开读面，不是私有字段。
        """
        manager.import_memories(
            [_record("mem#5", "无人认领的新说法", supersedes="库里根本没有这句")],
            ingest_run_id="run-5",
        )

        assert manager.get_stats()["supersede_unresolved_count"] == 1, (
            "get_stats() 没暴露导入侧累计的 supersede_unresolved_count——"
            "这条读数只写不读，读取面看不见"
        )


class TestContentGateStillHolds:
    def test_relearningAfterSupersedeLandsANewRow(self, manager):
        """软遗忘的旧行不充当内容门拦截目标——重新学到同一句必须能再落一行。"""
        first = manager.remember("用户偏好浅色模式")
        manager.import_memories(
            [_record("mem#4", "用户偏好深色模式", supersedes="用户偏好浅色模式")],
            ingest_run_id="run-3",
        )

        again = manager.remember("用户偏好浅色模式")

        assert again != first
        assert manager.get_memory(again)["lifecycle_stage"] == LifecycleStage.ACTIVE.value
