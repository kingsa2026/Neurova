# -*- coding: utf-8 -*-
"""B4-001 跨重启召回：池的归档写入路径必须写穿持久台账。

根因（审计 P1-3 + 决策 D1，本文件红灯即证）：

`ContextPool` 的持久化写入只挂在 ``_archive_evicted`` 上，而该方法的两个调用方
都不可达——生产构造面下 ``resident_limit=None``（不回收）、``ttl_seconds=0``
（``cleanup_expired()`` 立即返回 0，且全 ``neurova/`` 无生产调用点）。于是：

- 池本体（``_collector._contexts``）是进程内 list，没有任何持久化；
- 台账 DB 行数恒 0，``recall_evicted()`` 的子串模式**按构造恒空**；
- 模型侧 ``recall_history`` 仍被告知"可召回被折叠/驱逐的内容"——承诺无人兑现。

契约（修复后，判据 A1）：

- 归档条目**落常驻即写穿台账**（写入咽喉 = ``add_context``，所有旁路写入方共用）；
- 写失败必须**显式可见**：``get_retention_stats()`` 上报失败计数与原因，日志点名，
  不静默（本条不阻断归档主流程，内存归档仍有效）；
- 同一个条目只写一次（落常驻写穿后，驱逐不再重复写——否则台账线性膨胀）；
- 丢弃实例、以同库新建实例后，``recall_evicted(query)`` 取回原文，条数与内容逐字相等。

构造面纪律（审计 §8）：用例一律走**生产构造形状**（不传 ``resident_limit``、
``ttl_seconds=0``、``session_id`` 可为 None），不得靠手工触发驱逐来伪造"落盘"。
"""

import logging

import pytest

from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool

_SECRETS = [
    "第一轮：设备固件升级窗口定在周四凌晨两点",
    "第二轮：固件校验和用 sha256 而不是 md5",
    "第三轮：灰度顺序是先华东后华南",
]


def _productionPool(db_path, **kwargs):
    """生产构造形状（与 `ContextOrchestrator.__init__` 同型）：不传 resident_limit。"""
    return ContextPool(
        user_id="u1",
        agent_id="a1",
        session_id="s1",
        ttl_seconds=0,
        ledger_db=EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1"),
        **kwargs,
    )


def _archive(pool, content, turn_id):
    pool.add_context(
        ContextInput(
            source=ContextSource.CONVERSATION,
            content=content,
            priority=60,
            metadata={"role": "user", "turn_id": turn_id},
        )
    )


class TestCrossRestartRecall:
    """A1：写 → 丢弃实例 → 新实例同库 → 取回原文。"""

    def test_archive_survives_restart(self, tmp_path):
        db_path = tmp_path / "l.db"
        pool = _productionPool(db_path)
        # 生产构造面下既无容量驱逐也无 TTL：这两条出口都不产生台账写入
        assert pool.resident_limit is None
        for i, content in enumerate(_SECRETS):
            _archive(pool, content, f"turn_{i}")
        assert pool.cleanup_expired() == 0

        del pool  # 丢弃实例（等同进程退出：常驻集随进程消失）

        restarted = _productionPool(db_path)
        assert restarted.resident_count() == 0, "常驻集是进程内的，新实例不该有旧内容"
        recalled = restarted.recall_evicted(query="固件", limit=10)
        assert [c.content for c in recalled] == [
            "第二轮：固件校验和用 sha256 而不是 md5",
            "第一轮：设备固件升级窗口定在周四凌晨两点",
        ], "归档没能活过一次重启"
        assert all(c.metadata.get("recalled_from") == "ledger_db" for c in recalled)

    def test_archived_payload_is_byte_identical_after_restart(self, tmp_path):
        db_path = tmp_path / "l.db"
        pool = _productionPool(db_path)
        payload = "".join(_SECRETS)
        _archive(pool, payload, "turn_0")
        del pool

        recalled = _productionPool(db_path).recall_evicted(query="灰度顺序", limit=10)
        assert len(recalled) == 1
        assert recalled[0].content == payload, "取回的原文与写入内容不逐字相等"

    def test_write_through_is_reported(self, tmp_path):
        """写入计数必须可观测（否则"写穿"只能靠日志猜）。"""
        pool = _productionPool(tmp_path / "l.db")
        for i, content in enumerate(_SECRETS):
            _archive(pool, content, f"turn_{i}")
        stats = pool.get_retention_stats()["ledger_persistence"]
        assert stats["enabled"] is True
        assert stats["written"] == len(_SECRETS)
        assert stats["failed"] == 0
        assert stats["last_error"] is None

    def test_no_ledger_means_no_persistence_claim(self, tmp_path):
        """未注入台账：不得谎报"已持久化"（enabled=False 且不写）。"""
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0)
        _archive(pool, _SECRETS[0], "turn_0")
        stats = pool.get_retention_stats()["ledger_persistence"]
        assert stats["enabled"] is False
        assert stats["written"] == 0


class TestSingleWritePoint:
    """落常驻即写穿 → 驱逐不得重复写（否则台账随会话线性膨胀）。"""

    def test_evicted_entry_is_not_written_twice(self, tmp_path):
        db_path = tmp_path / "l.db"
        ledger = EvictionLedgerDB(db_path=db_path, user_id="u1", agent_id="a1")
        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1",
            ttl_seconds=0.05, ledger_db=ledger,
        )
        _archive(pool, "只在台账里出现一次的上海天气讨论", "turn_0")
        assert ledger.count() == 1

        import time

        time.sleep(0.08)
        assert pool.cleanup_expired() == 1  # 驱逐：内容已持久，不得再写一遍
        assert ledger.count() == 1, "驱逐路径重复写台账（同一条内容出现两行）"


class TestWriteFailureIsVisible:
    """写失败显式上报：不阻断归档，也不静默。"""

    class _FailingLedger:
        """必然失败的台账替身（模拟磁盘不可写/库损坏）。"""

        def record(self, **kwargs):
            raise RuntimeError("disk I/O error: 台账库不可写")

        def gc_stale(self):
            return 0

        def search(self, query=None, session_id=None, limit=20):
            return []

        def count(self):
            return 0

    def test_failure_is_counted_and_named(self, tmp_path, caplog):
        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
            ledger_db=self._FailingLedger(),
        )
        with caplog.at_level(logging.WARNING, logger="neurova.context_pool"):
            _archive(pool, _SECRETS[0], "turn_0")  # 不抛：归档主流程不被打断

        stats = pool.get_retention_stats()["ledger_persistence"]
        assert stats["enabled"] is True
        assert stats["written"] == 0
        assert stats["failed"] == 1
        assert "RuntimeError" in (stats["last_error"] or "")
        assert "台账库不可写" in (stats["last_error"] or ""), "上报里没有点名失败原因"

        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("持久台账" in m and "台账库不可写" in m for m in warnings), (
            f"写失败未以警告形态点名原因：{warnings}"
        )

    def test_memory_archive_still_intact_after_write_failure(self, tmp_path):
        """写失败不阻断内存归档：本条仍在本进程可取，且召回出口不谎报。

        写穿失败 = 本条**只是没进持久台账**（重启后不可召回），不是没入池。
        因此诚实形态有两条：常驻视图仍给得出原文；``recall_evicted`` 不得
        凭空给出一份"可跨重启召回"的假象——能否召回由计数与原因上报说明。
        """
        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
            ledger_db=self._FailingLedger(),
        )
        _archive(pool, _SECRETS[0], "turn_0")
        assert pool.resident_count() == 1
        assert [c.content for c in pool.get_contexts()] == [_SECRETS[0]]
        assert pool.recall_evicted(query="固件") == []
        stats = pool.get_retention_stats()["ledger_persistence"]
        assert (stats["written"], stats["failed"]) == (0, 1)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
