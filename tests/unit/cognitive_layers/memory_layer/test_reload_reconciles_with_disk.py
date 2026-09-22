# -*- coding: utf-8 -*-
"""reload 双向对账：以盘为准回收已被撤销的行（Issue #81 断点①，用户拍板）。

红灯依据：`reload_memories` 原先只做**单向并入**（只补缺、不回收），而写路径
（`update_memory` / `remember`）命中内存快照后一律直接落盘。于是另一进程 `undo`
删掉的那条行，在运行实例里既不会消失、还能被用户的一次"强化"写回盘上：

    另一进程 apply → 后端 reload 后可见 → 另一进程 undo → 盘上 0 行
    → 后端列表仍显示它 → 用户点一次强化 → 盘上又回到 1 行 → 重开实例复活

修法（用户拍板"reload 双向对账"）：重新读盘时不只并入缺失行，还回收**盘上已不存在**
的行；判据 = 业务 id + 行自带三元组。回收后 `update_memory` 找不到该 id 即返回 False，
"复活"这条路径自然断掉——不在写路径加兜底判断。

判据（先红后绿）：
1. 回收：另一进程删盘后 `reload_memories()["reaped"] == 1`，快照里那条消失；
2. 不能被写回：回收后 `update_memory` 返回 False，重开实例仍是 0 行；
3. 幂等：再 reload 回收 0 条（已回收的不会重复计）；
4. 不误伤：本进程运行期写入的行在盘上存在，reload 不回收它；
5. 召回面同步摘除：回收行的关键词倒排不留残留文档。
"""
from __future__ import annotations

from pathlib import Path

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.memory_ingest.bundle.records import MemoryRecord

_RUN = "nvimp-reap-1"


def _manager(base: Path, user_id: str = "default") -> MemoryManager:
    return MemoryManager(
        db_path=str(base / "memory" / "memory.db"),
        agent_id="reap-agent",
        user_id=user_id,
        enable_buffer=False,
    )


def _record(seq: int, content: str) -> MemoryRecord:
    return MemoryRecord(identity_key=f"ik-reap-{seq}", content=content,
                        memory_type="semantic", category="general", origin="owner",
                        importance=60.0, ts=f"2026-05-0{seq}T10:00:00+00:00")


def _contents(manager: MemoryManager) -> list:
    return [row["content"] for row in manager.get_memories(agent_wide=True, limit=500)]


def _imported_elsewhere(running: MemoryManager, *contents: str) -> MemoryManager:
    """另一个进程往同一份库写入（真 MemoryManager + 真导入写入口），写完不关。"""
    writer = MemoryManager(db_path=running._persist_db_path, agent_id="reap-agent",
                           user_id="default", enable_buffer=False)
    writer.import_memories([_record(i + 1, text) for i, text in enumerate(contents)],
                           ingest_run_id=_RUN)
    return writer


class TestReloadReapsRowsThatVanishedFromDisk:
    def test_row_undone_by_another_process_is_reaped_on_reload(self, tmp_path):
        running = _manager(tmp_path)
        writer = _imported_elsewhere(running, "待撤销的锚点")
        assert running.reload_memories()["reloaded"] == 1
        assert "待撤销的锚点" in _contents(running)

        writer.delete_ingested_memories(_RUN)          # 另一进程撤销：盘上行已删

        outcome = running.reload_memories()

        assert outcome["reaped"] == 1, f"盘上已无该行，reload 未回收：{outcome}"
        assert "待撤销的锚点" not in _contents(running)
        writer.close()

    def test_reaped_row_cannot_be_written_back(self, tmp_path):
        """断点①的真实链路：列表里那条"还在"→ 用户点一次强化 → 盘上 0 → 1 行。"""
        running = _manager(tmp_path)
        writer = _imported_elsewhere(running, "会复活的那条")
        running.reload_memories()
        memory_id = next(m.id for m in running._memories.values() if m.content == "会复活的那条")

        writer.delete_ingested_memories(_RUN)
        running.reload_memories()

        assert running.update_memory(memory_id, importance=95.0) is False, (
            "被撤销的行仍能被改动并写回盘——复活路径没断"
        )
        writer.close()
        reopened = _manager(tmp_path)
        assert reopened.get_memories(agent_wide=True, limit=100) == []
        assert reopened._memories == {}, "重开实例后被撤销的行又回来了"
        reopened.close()

    def test_second_reload_reaps_nothing_more(self, tmp_path):
        running = _manager(tmp_path)
        writer = _imported_elsewhere(running, "一次性回收")
        running.reload_memories()
        writer.delete_ingested_memories(_RUN)

        first = running.reload_memories()["reaped"]
        second = running.reload_memories()["reaped"]

        assert (first, second) == (1, 0), f"回收不幂等：{first}/{second}"
        writer.close()

    def test_rows_written_by_this_process_are_not_reaped(self, tmp_path):
        """不误伤：本进程运行期写入的行在盘上存在，reload 不得回收它。"""
        running = _manager(tmp_path)
        running.remember("本进程运行期的锚点", category="general")

        outcome = running.reload_memories()

        assert outcome["reaped"] == 0
        assert "本进程运行期的锚点" in _contents(running)

    def test_reaped_row_is_dropped_from_the_keyword_index(self, tmp_path):
        from neurova.cognitive_layers.memory_layer.semantic_search import (
            get_semantic_search, reset_semantic_search,
        )

        reset_semantic_search()
        try:
            running = _manager(tmp_path)
            writer = _imported_elsewhere(running, "回收后不该被搜到的锚点")
            running.reload_memories()
            search = get_semantic_search()
            memory_id = next(m.id for m in running._memories.values()
                             if m.content == "回收后不该被搜到的锚点")
            assert memory_id in search.search_by_keywords("回收后不该被搜到的锚点", limit=20)

            writer.delete_ingested_memories(_RUN)
            running.reload_memories()

            assert memory_id not in search.search_by_keywords("回收后不该被搜到的锚点", limit=20), (
                "回收只动内存与盘，关键词倒排里留下指向不存在记忆的残留文档"
            )
            writer.close()
        finally:
            reset_semantic_search()
