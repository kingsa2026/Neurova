# -*- coding: utf-8 -*-
"""跨进程可见性：`MemoryManager.reload_memories()` 把外来写入增量拉进内存快照。

红灯依据（Issue #81 / F-05 后半，设计 §6-B）：

记忆快照只在进程构造时读一次盘（`_load_from_db` 是唯一读盘入口）。于是 CLI
在**另一个进程**里导入的记忆，对运行中的服务一条都看不见——报告写着"已写入"、
界面上却什么都没有，是第三种假成功（既不是拒绝，也不是申报）。

可见性条件是「服务重启」或「显式 `reload_memories`」。本测试锁定后半条，判据：

1. **增量**：只拉本进程缺失的行；已有的行不重复装载；
2. **幂等**：连拉两次，第二次 0 条；
3. **召回面真的并入了**：关键词倒排逐条 upsert（不是 `build_keyword_index`
   那种 clear 全量重建——那会抹掉既有倒排），内容门索引同步并入，
   所以 reload 后 `remember()` 同一句会被门挡住而不是新增第二行；
4. **不写盘**：reload 是读侧可见性通道，不改动任何持久行（写侧另有其路）。
"""
from __future__ import annotations

from pathlib import Path

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.records import MemoryRecord

_RUN = "nvimp-reload-1"


def _memory_db_path(base: Path) -> Path:
    return base / "memory" / "memory.db"


def _manager(base: Path, user_id: str = "default") -> MemoryManager:
    return MemoryManager(
        db_path=str(_memory_db_path(base)),
        agent_id="reload-agent",
        user_id=user_id,
        enable_buffer=False,
    )


def _record(seq: int, content: str) -> MemoryRecord:
    return MemoryRecord(identity_key=f"ik-reload-{seq}", content=content,
                        memory_type="semantic", category="general", origin="owner",
                        importance=60.0, ts=f"2026-05-0{seq}T10:00:00+00:00")


def _imported_elsewhere(running: MemoryManager, *contents: str) -> None:
    """模拟另一个进程往同一份库写入：真 MemoryManager + 真导入写入口，写完即关。

    生产场景正是如此：CLI 在**另一个进程**里跑导入，运行中的服务进程对此一无所知
    （它的快照是构造时读的那一份）。同库不同实例即可复刻——两边各自持一份内存快照。
    """
    writer = MemoryManager(
        db_path=running._persist_db_path,
        agent_id="reload-agent",
        user_id="default",
        enable_buffer=False,
    )
    writer.import_memories([_record(i + 1, text) for i, text in enumerate(contents)],
                           ingest_run_id=_RUN)
    writer.close()


def _contents(manager: MemoryManager) -> list:
    return [row["content"] for row in manager.get_memories(agent_wide=True, limit=500)]


class TestReloadPullsForeignRowsIntoTheSnapshot:
    def test_row_written_by_another_process_is_invisible_until_reload(self, tmp_path):
        running = _manager(tmp_path)
        _imported_elsewhere(running, "跨进程导入的记忆锚点")

        assert "跨进程导入的记忆锚点" not in _contents(running), (
            "不重启就看见了外来行——判据本身失效，本测试失去意义"
        )

        added = running.reload_memories()

        assert added == 1, f"reload 应拉进 1 条，实得 {added}"
        assert "跨进程导入的记忆锚点" in _contents(running)

    def test_reload_is_idempotent_and_incremental(self, tmp_path):
        running = _manager(tmp_path)
        _imported_elsewhere(running, "第一条", "第二条")

        first = running.reload_memories()
        second = running.reload_memories()

        assert (first, second) == (2, 0), (
            f"增量判据不成立：首次 {first} 条、二次 {second} 条（应为 2/0）"
        )

    def test_reload_keeps_rows_already_in_memory(self, tmp_path):
        """本进程自己的运行期记忆不得被 reload 抹掉或重复装载。"""
        running = _manager(tmp_path)
        running.remember("本进程运行期记忆", category="general")
        _imported_elsewhere(running, "外来记忆")

        running.reload_memories()

        contents = _contents(running)
        assert contents.count("本进程运行期记忆") == 1
        assert "外来记忆" in contents

    def test_reload_does_not_write_persisted_rows(self, tmp_path):
        """reload 是读侧通道：不新增、不改写任何盘上行。"""
        running = _manager(tmp_path)
        _imported_elsewhere(running, "外来记忆")
        running.reload_memories()

        reopened = _manager(tmp_path)
        contents = _contents(reopened)
        assert contents.count("外来记忆") == 1, f"盘上行被改动: {contents}"
        reopened.close()


class TestReloadAlignsTheRecallSurfaces:
    def test_reloaded_row_is_keyword_searchable(self, tmp_path):
        """关键词倒排必须并入（逐条 upsert），否则 reload 后召回仍搜不到。"""
        from neurova.cognitive_layers.memory_layer.semantic_search import (
            get_semantic_search, reset_semantic_search,
        )

        reset_semantic_search()
        try:
            running = _manager(tmp_path)
            running.remember("运行期已有的关键句", category="general")
            _imported_elsewhere(running, "跨进程的关键句锚点")

            running.reload_memories()
            search = get_semantic_search()
            hits = search.search_by_keywords("跨进程的关键句锚点", limit=20)
            reloaded = next(m.id for m in running._memories.values()
                            if m.content == "跨进程的关键句锚点")

            assert reloaded in hits, (
                "reload 后关键词倒排里没有外来行——召回面没并入，界面照样搜不到"
            )
        finally:
            reset_semantic_search()

    def test_reload_does_not_rebuild_the_whole_inverted_index(self, tmp_path):
        """并入必须是增量 upsert；`build_keyword_index` 会 clear 掉既有倒排。"""
        from neurova.cognitive_layers.memory_layer.semantic_search import (
            get_semantic_search, reset_semantic_search,
        )

        reset_semantic_search()
        try:
            running = _manager(tmp_path)
            running.remember("运行期已有的关键句", category="general")
            _imported_elsewhere(running, "跨进程的关键句锚点")

            search = get_semantic_search()
            search.build_keyword_index([m.to_dict() for m in running._memories.values()])
            before = search.search_by_keywords("运行期已有的关键句", limit=20)

            running.reload_memories()

            after = search.search_by_keywords("运行期已有的关键句", limit=20)
            assert before == after, (
                "reload 把既有倒排清掉了（全量重建而非增量并入）: "
                f"{before} → {after}"
            )
        finally:
            reset_semantic_search()

    def test_content_gate_sees_the_reloaded_row(self, tmp_path):
        """内容门索引同样要并入：否则 reload 后同键写入会另起一行。

        门键含 origin（同文本不同信任级是两条语义不同的记忆），故这里按**同一份
        门键**写入——判的是"来行有没有进门索引"，不是"门要不要放宽口径"。
        """
        running = _manager(tmp_path)
        _imported_elsewhere(running, "会被门挡住的那句话")
        running.reload_memories()

        mid = running.remember("会被门挡住的那句话", category="general", origin="owner")

        stored = running._memories[mid]
        assert stored.metadata.get("ingest_run_id") == _RUN, (
            "reload 后的行没进内容门索引：同键写入被当成新记忆另起了一行"
        )
        assert _contents(running).count("会被门挡住的那句话") == 1


class TestReloadRespectsTheScopeOfEachRow:
    def test_reload_brings_rows_of_every_scope(self, tmp_path):
        """快照口径与 `_load_from_db` 同源（agent 全量），reload 不得收窄成当前作用域。

        行落的是 u1 作用域、读取实例是 u2：reload 要拉得进来（快照本就 agent 全量），
        但**不因此放宽检索隔离**——u2 的默认视图仍看不到 u1 的行。
        """
        running = _manager(tmp_path, user_id="u2")
        writer = _manager(tmp_path, user_id="u1")
        writer.import_memories([_record(1, "u1 的历史")], ingest_run_id=_RUN)
        writer.close()

        added = running.reload_memories()

        assert added == 1, f"reload 未拉进 u1 作用域的行，实得 {added}"
        u1_rows = [m for m in running._memories.values() if m.user_id == "u1"]
        assert [m.content for m in u1_rows] == ["u1 的历史"]
        assert "u1 的历史" not in [
            row["content"] for row in running.get_memories(limit=100)]
