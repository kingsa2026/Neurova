# -*- coding: utf-8 -*-
"""B6-7：归档时刻是读侧排序/打分的**唯一事实源**（Issue #90 · B5 尾巴三）。

红灯依据（改前实证）：

- `ContextInput` 有两个时刻字段：`created_at`（归档时刻，写入咽喉落库、召回时
  由 `resolveArchivedCreatedAt` 还原）与 `updated_at`（构造时同值，**全仓零写入方**）；
- 读侧 freshness 打分读的是 `updated_at`（`semantic_drawer._calculate_freshness_score`）。
  于是召回一条 30 天前的归档：`created_at` 是正确的归档时刻，而 `updated_at` 是
  **本次构造时刻** → `exp(-0.1×0)` = 1.0 —— 越老的归档越"新鲜"，相关性打分被污染。
  该形态在 `test_context_ledger_migration` 的注释里已被点名（"freshness 打分拿到
  的是假新鲜度"），只是当时只保证"事实取得回来"。

契约（修复后）：

1. 读侧排序与打分共用**同一个**归档时刻判据，且该判据只有一处定义；
2. 归档时刻越早 → freshness 越低（单调退火），与"这一轮什么时候构造的对象"无关；
3. 第二条时刻定义（`updated_at`）**删净**——它零写入方、与 `created_at` 同义，
   留着只会在读侧重新长出"假新鲜度"。
"""

from __future__ import annotations

import datetime as dt

import pytest

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.semantic_drawer import SemanticMatchDrawer


def _drawer():
    drawer = SemanticMatchDrawer(max_tokens=100000)
    drawer._vector_store = False  # 关键词刻度足够，本文件锁的是时间判据
    return drawer


def _entry(content: str, archivedAt: dt.datetime):
    return ContextInput(
        source=ContextSource.MEMORY,
        content=content,
        priority=60,
        tokens=5,
        created_at=archivedAt,
    )


class TestArchiveMomentIsSingleSource:
    def test_no_second_timestamp_definition(self):
        """第二条时刻定义必须删净：零写入方的同义字段是"假新鲜度"的宿主。"""
        assert not hasattr(ContextInput, "updated_at"), (
            "ContextInput 仍有 `updated_at`：它零写入方、与 created_at 同义，"
            "读侧一旦有人读它就会拿到构造时刻而非归档时刻"
        )
        assert "updated_at" not in ContextInput(
            source=ContextSource.MEMORY, content="探针"
        ).to_dict(), "归档时刻之外的第二个时刻仍被序列化出去"

    def test_archive_moment_readable_from_both_paths(self):
        """写入路径与读侧判据读同一个字段（归档时刻只有一份）。"""
        archivedAt = dt.datetime(2026, 1, 2, 3, 4, 5)
        entry = _entry("归档正文", archivedAt)

        assert entry.created_at == archivedAt


class TestFreshnessFollowsArchiveMoment:
    def test_older_archive_scores_lower(self):
        """归档时刻越早 → freshness 越低（改前两者同为 1.0）。"""
        now = dt.datetime.now()
        fresh = _entry("刚归档的条目", now)
        old = _entry("三十天前的条目", now - dt.timedelta(days=30))

        drawer = _drawer()
        freshScore = drawer._calculate_freshness_score(fresh)
        oldScore = drawer._calculate_freshness_score(old)

        assert freshScore > oldScore, (
            f"老归档的 freshness（{oldScore}）不低于新归档（{freshScore}）——"
            "打分读的不是归档时刻"
        )
        assert oldScore < freshScore * 0.2, "退火幅度与归档时刻不相称"

    def test_recall_from_ledger_keeps_archive_moment(self, tmp_path):
        """跨重启召回：归档时刻经台账还原后，freshness 必须随它退火（真 DB 链路）。"""
        from neurova.context.eviction_ledger_db import EvictionLedgerDB

        store = EvictionLedgerDB(db_path=tmp_path / "archive.db", user_id="u1", agent_id="a1")
        oldStamp = (dt.datetime.now() - dt.timedelta(days=45)).isoformat()
        store.record(content="四十五天前的归档正文", created_at=oldStamp)
        store.record(content="今天的归档正文", created_at=dt.datetime.now().isoformat())

        pool = self._pool(tmp_path / "archive.db")
        recalled = {row.content: row for row in pool.recall_evicted(limit=10)}
        assert set(recalled) == {"四十五天前的归档正文", "今天的归档正文"}

        drawer = _drawer()
        oldScore = drawer._calculate_freshness_score(recalled["四十五天前的归档正文"])
        newScore = drawer._calculate_freshness_score(recalled["今天的归档正文"])

        assert oldScore < newScore, (
            f"跨重启召回后老归档反而更'新鲜'（{oldScore} vs {newScore}）——"
            "读侧打分没有用台账还原出的归档时刻"
        )

    @staticmethod
    def _pool(dbPath):
        from neurova.context_pool import ContextPool

        return ContextPool(
            user_id="u1",
            agent_id="a1",
            session_id=None,
            ledger_db=None if dbPath is None else _ledger(dbPath),
            ttl_seconds=0,
        )


def _ledger(path):
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    return EvictionLedgerDB(db_path=path, user_id="u1", agent_id="a1")


class TestOrderingSharesArchiveMoment:
    def test_draw_order_is_archive_order(self):
        """视图顺序按归档时刻稳定排序（跨轮前缀缓存契约），与本文件同一份判据。"""
        now = dt.datetime.now()
        entries = [
            _entry("第三条", now - dt.timedelta(hours=1)),
            _entry("第一条", now - dt.timedelta(hours=3)),
            _entry("第二条", now - dt.timedelta(hours=2)),
        ]
        selected = _drawer().draw(entries, need="")

        assert [e.content for e in selected] == ["第一条", "第二条", "第三条"]
