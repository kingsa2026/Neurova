# -*- coding: utf-8 -*-
"""A3 命令回执幂等（追平 T3 Code CommandReceipt）。

被测模块：`neurova/core/command_receipt.py`（独立模块，本批不接线 swarm）。

断言全部落在**真实 SQLite 行为**上（临时文件库 + 真连接，无 MagicMock 充当数据库）：
- 首次执行落 accepted 回执；同 ID 重试重放结果、fn 不重跑；
- fn 失败落 rejected 回执并原样上抛，重试抛 PreviouslyRejectedError；
- 跨 thread 复用同 ID 抛 CommandIdConflictError；
- 并发同 ID 恰好一次副作用，另一侧重放或明确冲突；
- running 残留（他方在途/进程死亡）不接管、不重跑；
- ensureReceiptStore 幂等，且防降级语义（SchemaVersionError）不被破坏。
"""
from __future__ import annotations

import json
import sqlite3
import threading

import pytest

from neurova.core.command_receipt import (
    RECEIPT_DB_DOMAIN,
    CommandIdConflictError,
    CommandReceiptError,
    PreviouslyRejectedError,
    ensureReceiptStore,
    executeWithReceipt,
)
from neurova.core.db_migration import SchemaVersionError
from neurova.core.db_migration import latest_version
from neurova.core.db_migration import schema_version


def _openConn(dbPath) -> sqlite3.Connection:
    """打开真实 SQLite 连接并应用 command_receipt 迁移（busy_timeout 覆盖并发写竞争）。"""
    conn = sqlite3.connect(str(dbPath), check_same_thread=False, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    ensureReceiptStore(conn)
    return conn


def _receiptRow(conn, commandId: str):
    return conn.execute(
        "SELECT command_id, command_type, thread_id, status, result_json, error "
        "FROM command_receipt WHERE command_id = ?",
        (commandId,),
    ).fetchone()


# ── 首次执行：fn 执行一次，落 accepted 回执 ──


def test_firstExecutionRunsFnOnceAndStoresAcceptedReceipt(tmp_path):
    conn = _openConn(tmp_path / "receipts_first.db")
    calls = []

    def fn():
        calls.append(1)
        return {"ok": True, "detail": "派单完成"}

    result, replayed = executeWithReceipt(
        conn, command_id="cmd-1", command_type="dispatch", thread_id="t1", fn=fn
    )

    assert result == {"ok": True, "detail": "派单完成"}
    assert replayed is False
    assert calls == [1]

    row = _receiptRow(conn, "cmd-1")
    assert row is not None
    assert row[0] == "cmd-1"
    assert row[1] == "dispatch"
    assert row[2] == "t1"
    assert row[3] == "accepted"
    # ensure_ascii=False：中文原文可往返
    assert json.loads(row[4]) == {"ok": True, "detail": "派单完成"}
    assert row[5] is None
    conn.close()


# ── 同 ID 重试：fn 不再执行，重放结果 ──


def test_sameIdRetryReplaysResultWithoutRerunningFn(tmp_path):
    conn = _openConn(tmp_path / "receipts_retry.db")
    calls = []

    def fn():
        calls.append(1)
        return 42

    first = executeWithReceipt(
        conn, command_id="cmd-2", command_type="dispatch", thread_id="t1", fn=fn
    )
    second = executeWithReceipt(
        conn, command_id="cmd-2", command_type="dispatch", thread_id="t1", fn=fn
    )

    assert first == (42, False)
    assert second == (42, True)
    assert len(calls) == 1
    conn.close()


# ── fn 抛异常：rejected 落库 + 原样上抛；重试抛 PreviouslyRejectedError ──


def test_fnFailureStoresRejectedReceiptAndReraises(tmp_path):
    conn = _openConn(tmp_path / "receipts_fail.db")
    calls = []

    def fn():
        calls.append(1)
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        executeWithReceipt(
            conn, command_id="cmd-3", command_type="dispatch", thread_id="t1", fn=fn
        )
    assert len(calls) == 1

    row = _receiptRow(conn, "cmd-3")
    assert row[3] == "rejected"
    assert "boom" in row[5]

    # 同 thread 重试：拒绝也落回执，重试不得重跑 fn，抛 PreviouslyRejectedError（带原 error）
    with pytest.raises(PreviouslyRejectedError, match="boom"):
        executeWithReceipt(
            conn, command_id="cmd-3", command_type="dispatch", thread_id="t1", fn=fn
        )
    assert len(calls) == 1

    # 跨 thread 重试同 ID：先判 thread 冲突
    with pytest.raises(CommandIdConflictError):
        executeWithReceipt(
            conn, command_id="cmd-3", command_type="dispatch", thread_id="t2", fn=fn
        )
    assert len(calls) == 1
    conn.close()


# ── 跨 thread 同 ID：CommandIdConflictError ──


def test_crossThreadSameIdRaisesConflict(tmp_path):
    conn = _openConn(tmp_path / "receipts_conflict.db")
    calls = []

    def fn():
        calls.append(1)
        return {"v": 1}

    result, replayed = executeWithReceipt(
        conn, command_id="cmd-4", command_type="dispatch", thread_id="t1", fn=fn
    )
    assert (result, replayed) == ({"v": 1}, False)

    with pytest.raises(CommandIdConflictError):
        executeWithReceipt(
            conn, command_id="cmd-4", command_type="dispatch", thread_id="t2", fn=fn
        )
    assert len(calls) == 1
    conn.close()


# ── 并发同 ID：恰好一次 fn 生效，另一侧重放或明确冲突 ──


def test_concurrentSameIdExecutesFnExactlyOnce(tmp_path):
    dbPath = tmp_path / "receipts_concurrent.db"
    startBarrier = threading.Barrier(2)
    outcomes = {}
    calls = []
    callsLock = threading.Lock()

    def fn():
        with callsLock:
            calls.append(1)
        return {"side": "effect"}

    def worker(tag: int) -> None:
        conn = sqlite3.connect(str(dbPath), check_same_thread=False, timeout=30.0)
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            ensureReceiptStore(conn)
            startBarrier.wait(timeout=10)
            try:
                result, replayed = executeWithReceipt(
                    conn,
                    command_id="cmd-conc",
                    command_type="dispatch",
                    thread_id="t1",
                    fn=fn,
                )
                outcomes[tag] = ("ok", replayed, result)
            except CommandReceiptError as exc:
                outcomes[tag] = ("error", type(exc).__name__, str(exc))
        finally:
            conn.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    # 恰好一次副作用
    assert len(calls) == 1, f"fn 应恰好执行一次，实际 {len(calls)} 次；outcomes={outcomes}"
    # 两个 worker 都有结论
    assert len(outcomes) == 2
    # 恰好一次"首次执行"成功（replayed=False）；另一侧要么重放、要么明确冲突错误
    freshRuns = [o for o in outcomes.values() if o[0] == "ok" and o[1] is False]
    replays = [o for o in outcomes.values() if o[0] == "ok" and o[1] is True]
    errors = [o for o in outcomes.values() if o[0] == "error"]
    assert len(freshRuns) == 1, f"应恰好一次首次执行，outcomes={outcomes}"
    assert len(replays) + len(errors) == 1, f"另一侧应重放或冲突，outcomes={outcomes}"
    for o in replays:
        assert o[2] == {"side": "effect"}
    for o in errors:
        assert o[1] in ("CommandReceiptError", "CommandIdConflictError")

    # 库中恰一条 accepted 回执
    checkConn = sqlite3.connect(str(dbPath))
    try:
        rows = checkConn.execute(
            "SELECT status FROM command_receipt WHERE command_id = 'cmd-conc'"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "accepted"
    finally:
        checkConn.close()


# ── running 残留：不接管、不重跑 ──


def test_runningResidueBlocksExecutionWithoutRerunningFn(tmp_path):
    conn = _openConn(tmp_path / "receipts_running.db")
    calls = []

    def fn():
        calls.append(1)
        return {"never": True}

    # 手工插一条 running 残留（他方在途 / 进程死亡留下的行）
    conn.execute(
        "INSERT INTO command_receipt "
        "(command_id, command_type, thread_id, status, result_json, error, created_at) "
        "VALUES (?, ?, ?, 'running', NULL, NULL, ?)",
        ("cmd-run", "dispatch", "t1", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()

    # 同 thread：视为在途/残留冲突，fn 不执行
    with pytest.raises(CommandReceiptError, match="in flight"):
        executeWithReceipt(
            conn, command_id="cmd-run", command_type="dispatch", thread_id="t1", fn=fn
        )
    assert calls == []

    # 跨 thread：先判 thread 冲突
    with pytest.raises(CommandIdConflictError):
        executeWithReceipt(
            conn, command_id="cmd-run", command_type="dispatch", thread_id="t2", fn=fn
        )
    assert calls == []

    # 残留行原样保留（未被接管改写）
    row = _receiptRow(conn, "cmd-run")
    assert row[3] == "running"
    conn.close()


# ── ensureReceiptStore 幂等 + 防降级语义 ──


def test_ensureReceiptStoreIsIdempotent(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "receipts_ensure.db"))
    ensureReceiptStore(conn)
    ensureReceiptStore(conn)  # 第二次不炸

    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert "command_receipt" in tables
    assert latest_version(RECEIPT_DB_DOMAIN) == 1
    assert schema_version(conn) == 1
    conn.close()


def test_ensureReceiptStoreRejectsDowngradedDatabase(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "receipts_downgrade.db"))
    # 库版本高于本域已注册最大版本：防降级语义必须保持（拒绝打开继续跑）
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    with pytest.raises(SchemaVersionError):
        ensureReceiptStore(conn)
    conn.close()
