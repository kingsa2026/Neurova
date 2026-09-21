# -*- coding: utf-8 -*-
"""B4-003 写侧批量提交（判据 A2）：事务边界 = 一次归档调用，连接常驻。

红灯依据（改前实证）：

- `record()` 每行一次 `connect` → 两条 `INSERT` → `commit` → `close`：24 条一轮
  在 10 万行存量库上实测 214–318 ms/轮（基线脚本 §2 的"现状形状"）；同一轮改为
  "常驻连接 + 一次事务" 实测 0.78–0.91 ms/轮，差 261–420×。
- 池侧没有任何"一次归档调用"的事务边界：`add_context` 逐条写穿、逐条提交
  （B4/001 把写穿点前移到咽喉时保留了逐条事务，本片补批量）。

契约（修复后）：

- `EvictionLedgerDB` 持一个常驻连接（WAL + `synchronous=NORMAL` + `busy_timeout`），
  `record()` 不再每次 connect/close；`close()` 释放它；
- `beginBatch()` / `commitBatch()`：批量内全部条目**共用一个事务**，`commitBatch()`
  返回前必须已提交（规格 D8：不做异步/后台缓冲刷盘，否则崩溃窗口内的内容连同
  "已归档"的承诺一起丢）；
- 批内任一条写失败 → **整批回滚**（不部分提交），并上抛点名原因；
- 池侧 `archiveBatch()` 是唯一的事务边界：批内计数由 scope 退出时一次结算
  （成功 = 本批条数计入 `written`；失败 = 本批条数计入 `failed` 并点名原因）；
- 提交后**立即可被另一连接读到**（WAL 下跨连接可见），不允许"提交了别人看不见"。
"""

import sqlite3
import statistics
import time

import pytest

from neurova.context import eviction_ledger_db as ledgerModule
from neurova.context.eviction_ledger_db import EvictionLedgerDB
from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context_pool import ContextPool

ROUND_SIZE = 24


def _turnContents(turnIndex, size=ROUND_SIZE):
    """生产形状一轮：中文段 / 英文段 / JSON 工具结果三分（同基线脚本）。"""
    rows = []
    for i in range(size):
        shape = i % 3
        if shape == 0:
            text = f"第{turnIndex}轮第{i}条：上下文压缩判据讨论，窗口预算与折叠阈值"
        elif shape == 1:
            text = f"turn {turnIndex} item {i}: The context window budget decides whether folding triggers."
        else:
            text = (
                '{"role": "assistant", "tool": "file_read", "turn": %d, "item": %d,'
                ' "bytes": 4096, "ok": true}' % (turnIndex, i)
            )
        rows.append((f"turn{turnIndex}_{i}", text))
    return rows


def _foreignRows(dbPath):
    """从独立连接读行数（跨连接可见性判据，不走台账实例）。"""
    conn = sqlite3.connect(dbPath)
    try:
        return conn.execute("SELECT COUNT(*) FROM evicted_chunks").fetchone()[0]
    finally:
        conn.close()


def _archiveTurn(pool, turnIndex, size=ROUND_SIZE):
    for turn_id, text in _turnContents(turnIndex, size):
        pool.add_context(
            ContextInput(
                source=ContextSource.CONVERSATION,
                content=text,
                metadata={"turn_id": turn_id},
            )
        )


class TestConnectionIsResident:
    """常驻连接：写入口不再每次 connect/close。"""

    def test_record_reuses_resident_connection(self, tmp_path, monkeypatch):
        realConnect = ledgerModule.sqlite3.connect
        opens = []

        def countingConnect(*args, **kwargs):
            opens.append(1)
            return realConnect(*args, **kwargs)

        monkeypatch.setattr(ledgerModule.sqlite3, "connect", countingConnect)
        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u1", agent_id="a1")
        opensAfterInit = len(opens)

        for turn_id, text in _turnContents(1):
            ledger.record(content=text, turn_id=turn_id, session_id="s1")

        assert opensAfterInit == 1, f"构造期应只开一次连接，实际 {opensAfterInit} 次"
        assert len(opens) == opensAfterInit, (
            f"record() 仍在每次新建连接（{len(opens) - opensAfterInit} 次）——"
            "写放大的一半开销就在 connect/close 上"
        )

    def test_close_releases_connection(self, tmp_path):
        ledger = EvictionLedgerDB(db_path=tmp_path / "l.db", user_id="u1", agent_id="a1")
        ledger.record(content="关闭前写入", session_id="s1")
        ledger.close()
        ledger.close()  # 幂等
        with pytest.raises(sqlite3.ProgrammingError):
            ledger.record(content="关闭后写入", session_id="s1")


class TestBatchIsOneTransaction:
    """一次归档调用 = 一个事务（D8）。"""

    def test_batch_defers_commit_until_scope_end(self, tmp_path):
        dbPath = tmp_path / "batch.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")

        ledger.beginBatch()
        try:
            for turn_id, text in _turnContents(1):
                ledger.record(content=text, turn_id=turn_id, session_id="s1")
            assert _foreignRows(dbPath) == 0, "批内已可见——不是同一事务（说明每条都提交了）"
            ledger.commitBatch()
        finally:
            ledger.close()

        assert _foreignRows(dbPath) == ROUND_SIZE, "提交后另一连接读不到本批内容"

    def test_failed_item_rolls_back_whole_batch(self, tmp_path):
        dbPath = tmp_path / "rollback.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")

        ledger.beginBatch()
        for turn_id, text in _turnContents(1, size=5):
            ledger.record(content=text, turn_id=turn_id, session_id="s1")
        with pytest.raises(sqlite3.IntegrityError):
            # content NOT NULL：整批必须回滚，不得出现"半批已提交"
            ledger.record(content=None, turn_id="turn1_bad", session_id="s1")
        with pytest.raises(sqlite3.IntegrityError):
            ledger.commitBatch()
        ledger.close()

        assert _foreignRows(dbPath) == 0, "批内失败没有整批回滚（出现半批提交）"

    def test_reads_are_allowed_inside_batch(self, tmp_path):
        """批内可读（本项目自己的批内读来自回收/统计等路径，不得死锁）。"""
        dbPath = tmp_path / "readinbatch.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
        ledger.beginBatch()
        try:
            ledger.record(content="批内写入（尚未提交）", session_id="s1")
            # 同一连接读得到自己的未提交写（sqlite 语义），此处只要不死锁即可；
            # "批外看不见"由 test_batch_defers_commit_until_scope_end 的独立连接断言。
            assert ledger.count() == 1
            assert _foreignRows(dbPath) == 0, "批外连接读到了未提交的写入"
        finally:
            ledger.commitBatch()
            assert ledger.count() == 1
            ledger.close()

    def test_concurrent_writers_do_not_interleave_transactions(self, tmp_path):
        """并发写：批间互不交错（`busy_timeout` + 实例锁），总行数正确。"""
        import threading

        dbPath = tmp_path / "concurrent.db"
        ledgers = [
            EvictionLedgerDB(db_path=dbPath, user_id=f"u{i}", agent_id="a1") for i in range(3)
        ]
        errors = []

        def worker(index, ledger):
            try:
                for turn in range(5):
                    ledger.beginBatch()
                    for item in range(4):
                        ledger.record(
                            content=f"u{index}-turn{turn}-item{item}", session_id="s1"
                        )
                    ledger.commitBatch()
            except Exception as exc:  # noqa: BLE001 - 记录后由主线程断言
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i, l)) for i, l in enumerate(ledgers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for ledger in ledgers:
            ledger.close()

        assert not errors, f"并发写报错：{errors}"
        assert _foreignRows(dbPath) == 3 * 5 * 4

    def test_records_outside_batch_still_commit_immediately(self, tmp_path):
        """非批量路径语义不回归：单条写完即可被另一连接读到（D1 的 A1 依赖它）。"""
        dbPath = tmp_path / "single.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
        ledger.record(content="单条写入", session_id="s1")
        assert _foreignRows(dbPath) == 1
        ledger.close()


class TestPoolArchiveBatch:
    """池侧事务边界：批内计数一次结算，失败整批计入失败并点名。"""

    def _pool(self, dbPath, **kwargs):
        return ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
            ledger_db=EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1"),
            **kwargs,
        )

    def test_batch_counts_once_and_commits(self, tmp_path):
        dbPath = tmp_path / "poolbatch.db"
        pool = self._pool(dbPath)
        with pool.archiveBatch():
            _archiveTurn(pool, 1)
            assert pool.get_retention_stats()["ledger_persistence"]["written"] == 0, (
                "批未结束就记 written——批不是原子的"
            )
        stats = pool.get_retention_stats()["ledger_persistence"]
        assert stats["written"] == ROUND_SIZE
        assert stats["failed"] == 0
        assert stats["batches"] == 1
        assert _foreignRows(dbPath) == ROUND_SIZE

    def test_batch_failure_counts_whole_batch_and_names_reason(self, tmp_path, caplog):
        import logging

        class _FailingBatchLedger(EvictionLedgerDB):
            def record(self, **kwargs):
                if kwargs.get("turn_id") == "turn1_1":
                    raise sqlite3.IntegrityError("NOT NULL constraint failed: evicted_chunks.content")
                return super().record(**kwargs)

        dbPath = tmp_path / "poolfail.db"
        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
            ledger_db=_FailingBatchLedger(db_path=dbPath, user_id="u1", agent_id="a1"),
        )
        with caplog.at_level(logging.WARNING, logger="neurova.context_pool"):
            with pool.archiveBatch():
                _archiveTurn(pool, 1)

        stats = pool.get_retention_stats()["ledger_persistence"]
        assert stats["written"] == 0, "整批回滚后仍报 written>0（谎报已持久化）"
        assert stats["failed"] == ROUND_SIZE, "失败批只计了一条（应整批计入）"
        assert stats["batches"] == 1
        assert "IntegrityError" in (stats["last_error"] or "")
        assert _foreignRows(dbPath) == 0, "失败批留下了已提交的行"
        warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("归档" in m and "IntegrityError" in m for m in warnings), (
            f"整批失败未以警告形态点名原因：{warnings}"
        )

    def test_memory_archive_unaffected_by_batch_failure(self, tmp_path):
        class _FailingBatchLedger(EvictionLedgerDB):
            def record(self, **kwargs):
                raise sqlite3.OperationalError("disk I/O error")

        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0,
            ledger_db=_FailingBatchLedger(
                db_path=tmp_path / "poolfail2.db", user_id="u1", agent_id="a1"
            ),
        )
        with pool.archiveBatch():
            _archiveTurn(pool, 1, size=3)

        assert pool.resident_count() == 3, "写失败阻断了内存归档（教义：归档主流程不可被打断）"

    def test_without_ledger_batch_is_noop(self):
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0)
        with pool.archiveBatch():
            _archiveTurn(pool, 1, size=2)
        assert pool.resident_count() == 2
        assert pool.get_retention_stats()["ledger_persistence"]["enabled"] is False


class TestRoundHasOneTransactionBoundary:
    """A2 的**结构面**：一轮归档 = 常驻连接 + 一个事务。

    这条才是与机器速度无关的判据：连接新建次数与 BEGIN/COMMIT 次数是步骤集合的
    性质（24 行写穿要么 24 次连接 + 24 次事务，要么 0 次 + 1 次），不随负载摆动。
    同契约的倍数读数（`TestWriteAmplification`）另存，两者互为表里。
    """

    def test_round_uses_one_connection_and_one_transaction(self, tmp_path, monkeypatch):
        counts = {"connect": 0, "BEGIN": 0, "COMMIT": 0}
        realConnect = ledgerModule.sqlite3.connect

        def countingConnect(*args, **kwargs):
            counts["connect"] += 1
            conn = realConnect(*args, **kwargs)

            def onStatement(sql):
                statement = sql.strip()
                if statement in counts:
                    counts[statement] += 1

            conn.set_trace_callback(onStatement)
            return conn

        monkeypatch.setattr(ledgerModule.sqlite3, "connect", countingConnect)
        dbPath = tmp_path / "boundary.db"
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
        ledger.beginBatch()
        for i in range(300):
            ledger.record(
                content=f"存量第{i}行：上下文压缩与窗口预算", turn_id=f"seed{i}", session_id="s1"
            )
        ledger.commitBatch()
        pool = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0, ledger_db=ledger
        )
        try:
            with pool.archiveBatch():  # 预热一轮：时序读数不该把首次冷加载算进来
                _archiveTurn(pool, 1)
            for name in counts:
                counts[name] = 0
            with pool.archiveBatch():
                _archiveTurn(pool, 2)
        finally:
            ledger.close()

        assert counts["connect"] == 0, (
            f"一轮归档内新建了 {counts['connect']} 个连接——写放大的一半就在 connect/close 上"
        )
        assert counts["BEGIN"] == 1, f"一轮归档开了 {counts['BEGIN']} 个事务（应共用一个）"
        assert counts["COMMIT"] == 1, f"一轮归档提交了 {counts['COMMIT']} 次（应只提交一次）"
        assert _foreignRows(dbPath) >= ROUND_SIZE, "本轮提交后跨连接读不到内容"


class TestWriteAmplification:
    """A2：24 条/轮的归档耗时 ≤ 现状形状的 1/3（同机同存量规模 A/B，各 3 轮取中位）。

    两侧都必须**先预热再计时**：批量形状的首次归档会懒加载 token 估算器（tiktoken
    `o200k_base`，实测 ~250 ms 一次性成本），把它算进分子会让读数变成"现状形状的
    1.2 倍"——那不是本契约的读数，而是冷启动的读数。本用例只量稳态的一轮写穿成本。
    """

    def _seed(self, dbPath, rows):
        ledger = EvictionLedgerDB(db_path=dbPath, user_id="u1", agent_id="a1")
        ledger.beginBatch()
        for i in range(rows):
            ledger.record(
                content=f"存量第{i}行：上下文压缩与窗口预算", turn_id=f"seed{i}", session_id="s1"
            )
        ledger.commitBatch()
        ledger.close()

    def _legacyRound(self, dbPath, turnIndex, tag):
        started = time.perf_counter()
        for turn_id, text in _turnContents(turnIndex):
            conn = sqlite3.connect(dbPath, timeout=30)
            try:
                cur = conn.execute(
                    "INSERT INTO evicted_chunks"
                    " (user_id, agent_id, session_id, turn_id, source, content, metadata,"
                    "  evicted_at, content_digest, created_at, chat_scope)"
                    " VALUES ('u1','a1','s1',?, 'conversation', ?, NULL, '2026-09-01T00:00:00', ?,"
                    "  '2026-09-01T00:00:00', 'direct')",
                    (turn_id, text, f"legacy-{tag}-{turn_id}"),
                )
                conn.execute(
                    "INSERT INTO evicted_fts(rowid, content) VALUES (?, ?)", (cur.lastrowid, text)
                )
                conn.commit()
            finally:
                conn.close()
        return time.perf_counter() - started

    def test_batch_round_is_far_below_per_row_shape(self, tmp_path):
        seedRows = 2000
        rounds = 3

        # 现状形状：每行独立 connect + commit + close（与改前 record() 同形）
        legacyPath = tmp_path / "legacy_shape.db"
        self._seed(legacyPath, seedRows)
        self._legacyRound(legacyPath, 0, "warmup")  # 预热
        legacy = [self._legacyRound(legacyPath, turn, "cold") for turn in range(1, rounds + 1)]

        # 批量形状：常驻连接 + 一次事务（本批实现）
        batchPath = tmp_path / "batch_shape.db"
        ledger = EvictionLedgerDB(db_path=batchPath, user_id="u1", agent_id="a1")
        batch = []
        try:
            ledger.beginBatch()
            for i in range(seedRows):
                ledger.record(
                    content=f"存量第{i}行：上下文压缩与窗口预算", turn_id=f"seed{i}", session_id="s1"
                )
            ledger.commitBatch()
            pool = ContextPool(
                user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0, ledger_db=ledger
            )
            with pool.archiveBatch():  # 预热：首次归档会懒加载 token 估算器
                _archiveTurn(pool, 0)
            for turn in range(1, rounds + 1):
                started = time.perf_counter()
                with pool.archiveBatch():
                    _archiveTurn(pool, turn)
                batch.append(time.perf_counter() - started)
        finally:
            ledger.close()

        legacySeconds = statistics.median(legacy)
        batchSeconds = statistics.median(batch)
        assert batchSeconds <= legacySeconds / 3, (
            f"批量形状 {batchSeconds * 1000:.2f} ms/轮 > 现状形状 {legacySeconds * 1000:.2f} ms/轮 的 1/3"
            f"（A2 未达标；现状逐轮 {[round(x * 1000, 2) for x in legacy]} ms，"
            f"批量逐轮 {[round(x * 1000, 2) for x in batch]} ms）"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
