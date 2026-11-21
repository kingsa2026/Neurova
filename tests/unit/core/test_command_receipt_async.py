# -*- coding: utf-8 -*-
"""A3 接线：executeWithReceiptAsync 异步命令幂等（swarm async 写路径用）。"""
import asyncio
import sqlite3

import pytest

from neurova.core.command_receipt import (
    CommandIdConflictError,
    CommandReceiptError,
    PreviouslyRejectedError,
    ensureReceiptStore,
    executeWithReceiptAsync,
)


def _conn(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "receipts.db"), check_same_thread=False)
    ensureReceiptStore(conn)
    return conn


@pytest.mark.asyncio
async def test_async_first_run_executes_and_accepts(tmp_path):
    conn = _conn(tmp_path)
    calls = []

    async def fn():
        calls.append(1)
        return {"ok": True, "n": len(calls)}

    result, replayed = await executeWithReceiptAsync(
        conn, command_id="cmd-1", command_type="dispatch_team",
        thread_id="sess-1", afn=fn,
    )
    assert result == {"ok": True, "n": 1}
    assert replayed is False
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_async_retry_replays_without_side_effect(tmp_path):
    conn = _conn(tmp_path)
    calls = []

    async def fn():
        calls.append(1)
        return {"spawned": ["run-1"]}

    first, replayed1 = await executeWithReceiptAsync(
        conn, command_id="cmd-1", command_type="dispatch_team",
        thread_id="sess-1", afn=fn,
    )
    second, replayed2 = await executeWithReceiptAsync(
        conn, command_id="cmd-1", command_type="dispatch_team",
        thread_id="sess-1", afn=fn,
    )
    assert replayed1 is False and replayed2 is True
    assert first == second
    assert len(calls) == 1, "同 command_id 重试不得重跑副作用"


@pytest.mark.asyncio
async def test_async_concurrent_same_id_single_effect(tmp_path):
    conn = _conn(tmp_path)
    calls = []
    gate = asyncio.Event()

    async def fn():
        # 让出事件循环，制造第二个协程在首者未落账时重入的竞态
        await gate.wait()
        calls.append(1)
        return {"spawned": True}

    async def runner():
        return await executeWithReceiptAsync(
            conn, command_id="cmd-x", command_type="dispatch_team",
            thread_id="sess-1", afn=fn,
        )

    task1 = asyncio.create_task(runner())
    await asyncio.sleep(0)
    task2 = asyncio.create_task(runner())
    await asyncio.sleep(0)
    gate.set()
    results = await asyncio.gather(task1, task2, return_exceptions=True)
    outcomes = []
    for r in results:
        if isinstance(r, Exception):
            assert isinstance(r, CommandReceiptError), f"并发竞争只允许回执错误: {r!r}"
            outcomes.append("conflict")
        else:
            outcomes.append("executed")
    assert outcomes.count("executed") == 1, f"恰好一次执行: {outcomes}"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_async_failure_rejects_and_blocks_retry(tmp_path):
    conn = _conn(tmp_path)

    async def bad():
        raise ValueError("boom")

    with pytest.raises(ValueError):
        await executeWithReceiptAsync(
            conn, command_id="cmd-bad", command_type="update_subagent",
            thread_id="sess-1", afn=bad,
        )
    with pytest.raises(PreviouslyRejectedError):
        await executeWithReceiptAsync(
            conn, command_id="cmd-bad", command_type="update_subagent",
            thread_id="sess-1", afn=bad,
        )


@pytest.mark.asyncio
async def test_async_cross_thread_same_id_conflict(tmp_path):
    conn = _conn(tmp_path)

    async def fn():
        return 1

    await executeWithReceiptAsync(
        conn, command_id="cmd-c", command_type="cancel_run",
        thread_id="sess-1", afn=fn,
    )
    with pytest.raises(CommandIdConflictError):
        await executeWithReceiptAsync(
            conn, command_id="cmd-c", command_type="cancel_run",
            thread_id="sess-2", afn=fn,
        )
