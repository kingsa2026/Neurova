# -*- coding: utf-8 -*-
"""B4-008 召回作用域闸口：持久层是第二条读路径，必须与视图路径同源。

根因（规格 D13，本文件红灯即证）：

`orchestrator` 的视图路径在 B2 已过 `filter_by_scope`，而**持久层这条读路径
完全不过闸口**，且库里取回的条目按 `session_id` 做**精确等值过滤**：

- 单聊池（`session_id=s_direct`）召回群聊归档 = **0 条**（恒空，不是被挡住，是查不到）；
- 无会话池（`session_id=None`）召回群聊归档 = **1 条**，且无任何闸口 → 房间内容可见。

契约（修复后，判据 A8）：

- `recall_evicted` 过与视图路径**同一个** `collaboration.memory_scope.filter_by_scope`
  ——不新写第二份作用域规则与阈值；
- 单聊轮（`collab=False`）只见 `direct`；群 R 轮见 `direct + room:R`；跨房间互不可见；
- 无会话池同样不得泄露房间内容；
- 不能修过头：本群自己的归档仍可召回（隔离不等于全挡）；
- 双源去重不破：同内容在内存台账与持久台账各有一份时只出一条。
"""

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool

ROOM_CONTENT = "群聊归档：量子项目代号 ZEPHYR-9"
DIRECT_CONTENT = "单聊归档：家里地址在某某路"


def _pool(db_path, *, session_id, **kwargs):
    return ContextPool(
        user_id="u1", agent_id="a1", session_id=session_id, ttl_seconds=0,
        ledger_db=EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1"),
        **kwargs,
    )


def _seed(db_path):
    """预置两类归档：一个房间条目 + 一个单聊条目。"""
    ledger = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
    ledger.record(content=ROOM_CONTENT, session_id="project_roomB", chat_scope="room:project_roomB")
    ledger.record(content=DIRECT_CONTENT, session_id="s_direct", chat_scope="direct")
    ledger.close()


def _contents(items):
    return [str(getattr(c, "content", "")) for c in items]


class TestRecallScopeGate:
    def test_direct_turn_never_sees_room_content(self, tmp_path):
        """单聊轮召回不得出现房间归档（改前恒空是因为按 session 精确过滤，不是闸口）。"""
        db_path = tmp_path / "gate.db"
        _seed(db_path)
        pool = _pool(db_path, session_id="s_direct")

        recalled = pool.recall_evicted(limit=10)

        assert ROOM_CONTENT not in _contents(recalled), (
            f"群聊归档在单聊轮可见：{_contents(recalled)}"
        )
        assert DIRECT_CONTENT in _contents(recalled), "单聊自己的归档也被挡掉了（修过头）"

    def test_sessionless_pool_never_sees_room_content(self, tmp_path):
        """无会话池（session_id=None）不得泄露房间内容。"""
        db_path = tmp_path / "gate_none.db"
        _seed(db_path)
        pool = _pool(db_path, session_id=None)

        recalled = pool.recall_evicted(limit=10)

        assert ROOM_CONTENT not in _contents(recalled), (
            f"无会话池看到了房间内容：{_contents(recalled)}"
        )

    def test_group_turn_sees_direct_plus_own_room(self, tmp_path):
        """群轮见 direct + 本群；本群自己的归档必须仍可召回。"""
        db_path = tmp_path / "gate_room.db"
        _seed(db_path)
        pool = _pool(db_path, session_id="project_roomB")
        pool.turn_scope = "room:project_roomB"

        recalled = pool.recall_evicted(limit=10)

        assert ROOM_CONTENT in _contents(recalled), "本群归档被挡掉了（修过头）"
        assert DIRECT_CONTENT in _contents(recalled), "群轮应可见 direct 归档"

    def test_other_room_content_invisible(self, tmp_path):
        """跨房间互不可见。"""
        db_path = tmp_path / "gate_other.db"
        _seed(db_path)
        pool = _pool(db_path, session_id="project_roomA")
        pool.turn_scope = "room:project_roomA"

        recalled = pool.recall_evicted(limit=10)

        assert ROOM_CONTENT not in _contents(recalled), (
            f"他群内容在 roomA 轮可见：{_contents(recalled)}"
        )

    def test_same_judgementAsViewPath(self, tmp_path, monkeypatch):
        """判据同源：断言召回路径确实经 `memory_scope.filter_by_scope`。

        探针打在**事实源函数**上（而非某个模块的属性）：若召回侧自己复刻了一份
        作用域判定，这个探针就不会被触发——复制规则必然在此暴露。
        """
        from neurova.collaboration import memory_scope

        calls = []
        original = memory_scope.filter_by_scope

        def countingFilter(items, metadata_of, **kwargs):
            calls.append(kwargs)
            return original(items, metadata_of, **kwargs)

        db_path = tmp_path / "gate_src.db"
        _seed(db_path)
        pool = _pool(db_path, session_id="s_direct")
        monkeypatch.setattr(memory_scope, "filter_by_scope", countingFilter)

        pool.recall_evicted(limit=10)

        assert calls, "召回路径没有调用 memory_scope.filter_by_scope（自己复刻了第二份规则）"

    def test_dualSourceDedupStillHolds(self, tmp_path):
        """双源去重不破：内存台账与持久台账同内容只出一条（且仍过闸口）。"""
        db_path = tmp_path / "gate_dedup.db"
        _seed(db_path)
        pool = _pool(db_path, session_id="s_direct")
        pool._archive_evicted(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content=DIRECT_CONTENT,
                metadata={"chat_scope": "direct", "session_id": "s_direct"},
            )
        )

        recalled = pool.recall_evicted(limit=10)

        assert _contents(recalled).count(DIRECT_CONTENT) == 1, "同内容召回出两条"

    def test_memoryLedgerAlsoGated(self, tmp_path):
        """内存台账（第二条源）同样过闸口——只挡持久源等于半个闸口。"""
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s_direct", ttl_seconds=0)
        pool._archive_evicted(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content=ROOM_CONTENT,
                metadata={"chat_scope": "room:project_roomB", "session_id": "project_roomB"},
            )
        )

        recalled = pool.recall_evicted(limit=10)

        assert ROOM_CONTENT not in _contents(recalled), "内存台账里的房间内容未被闸口拦住"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
