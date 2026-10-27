# -*- coding: utf-8 -*-
"""租约过期收敛的运行期接线（2026-10-08 长任务闭环审计 D 批）。

`AgentRunStore` 每次心跳都写 `heartbeat_at` / `lease_expires_at`（store.py:56-57、190-192），
唯一读它们做收敛的是 `reconcile_stale`（store.py:422）——而它**在生产里零调用方**：
只有 `tests/unit/core/test_agent_run_store*.py` 在直接调，以及两处散文把它当现役机制
（`turn_coordinator.py:155`「等待期就会被 reconcile_stale 误杀成 failed」、
`agent_run_ledger.py:153` 同一口径）。于是写了不读：

- 进程活着、某一轮的工作卡死（线程 stall、await 永不返回）→ 这条 run 永远停在
  `running`，前端一直"运行中"，`GET /console/chat/runs` 也读不出它已死；
- 启动收敛 `reconcile_at_startup` 只覆盖"重启过"的那一类（构造时跑一次，store.py:124），
  运行期的租约过期无人认领。

根因是**运行期没有驱动者**，不是 `reconcile_stale` 写错。修在驱动侧：扫描间隔由租约
派生（`lease/3`，下限 5s），且只收敛 `status='running' AND lease_expires_at < now`；
parked 不在谓词里（它是"等人"，`test_agentRunStoreParkedStatus` 已钉住不得被顺手收敛）。

判据（改前逐条实测不成立）：
1. 接线：lifespan 启动与关闭都必须在场（只有 start 没有 stop 会让 TestClient teardown 挂住）；
2. 单轮扫描只咬过期租约：过期 running→failed(process_died)，新鲜 running 不动；
3. parked / queued / 终态一律不碰；
4. 间隔由租约派生且严格小于租约（否则过期租约要等到下一次重启才被读）；
5. 停止后不遗留仍在跑的 task（幂等 start、可重复 stop）。
"""
from __future__ import annotations

import ast
import asyncio
import io
import time
from pathlib import Path

import pytest

from neurova.core import agent_run_store as ars
from tests.ast_scan import parseSource

PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_MODULE = PROJECT_ROOT / "neurova" / "api" / "app.py"


@pytest.fixture()
def store(tmp_path):
    s = ars.AgentRunStore(tmp_path / "runs.db", lease_seconds=2.0)
    yield s
    s.close()


def _seedRunning(store, session_id, owner):
    runId = store.intake(session_id, "u1", "a1", "跑一会")
    assert store.claim_next(session_id, owner=owner) == runId
    return runId


def _lifespanCallNames():
    """app.py 里出现过的 `startStaleSweep` / `stopStaleSweep` 调用点（AST，只认真调用）。"""
    tree = parseSource(io.open(APP_MODULE, encoding="utf-8").read())
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = getattr(fn, "id", None) or getattr(fn, "attr", None)
            if name in {"startStaleSweep", "stopStaleSweep"}:
                found.add(name)
    return found


class TestSweepIsDrivenAtRuntime:
    def test_app_lifespan_starts_and_stops_the_sweep(self):
        """没接线时租约读数永远不变——写了不读就是断点。"""
        called = _lifespanCallNames()
        assert "startStaleSweep" in called, (
            "app.py 未启动租约过期扫描：reconcile_stale 仍是零生产调用方的死码，"
            "进程活着而工作卡死的 run 永不收敛"
        )
        assert "stopStaleSweep" in called, (
            "只 start 不 stop：常驻 task 不收敛会让 TestClient/真进程退出挂住"
        )


class TestSweepOncePredicate:
    def test_expiredLeaseFails_freshLeaseSurvives(self, store):
        dead = _seedRunning(store, "s_dead", "w1")
        alive = _seedRunning(store, "s_alive", "w2")
        # 让 dead 的租约过期：走生产字段，不改判据口径
        with store._lock, store._conn:
            store._conn.execute(
                "UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?",
                (time.time() - 5.0, dead),
            )

        converged = ars.sweepStaleOnce(store)

        assert [c["run_id"] for c in converged] == [dead], f"收敛对象错：{converged}"
        assert store.get(dead)["status"] == "failed"
        assert store.get(dead)["error_type"] == "process_died"
        assert store.get(alive)["status"] == "running", (
            "新鲜租约被误杀——在跑的正常轮次会被扫描判死"
        )

    def test_parkedAndQueuedAreNotTouched(self, store):
        """parked 的 `lease_expires_at` 被 park 置 0（store.py:274），谓词必须靠 status 拦住它。"""
        parkedId = _seedRunning(store, "s_park", "w1")
        assert store.park(parkedId, owner="w1", parkReason="quota_wait") is True
        queuedId = store.intake("s_q", "u1", "a1", "还在排队")

        converged = ars.sweepStaleOnce(store)

        assert converged == [], f"扫描误伤了 parked/queued：{converged}"
        assert store.get(parkedId)["status"] == ars.PARKED_STATUS
        assert store.get(queuedId)["status"] == "queued"


class TestIntervalDerivation:
    def test_intervalDerivedFromLeaseAndSmallerThanLease(self, store):
        """间隔必须小于租约：否则「过期」到「被读」之间的窗口比租约本身还长。"""
        interval = ars.staleSweepIntervalSeconds(store)
        assert 0 < interval <= max(ars.SWEEP_INTERVAL_MIN_S, store.lease_seconds / 3.0), (
            f"间隔 {interval} 不是从租约 {store.lease_seconds} 派生的（另立一份数字=第二份定义）"
        )
        assert interval < store.lease_seconds * 3, (
            f"间隔 {interval} 相对租约 {store.lease_seconds} 过疏，死租约会长时间悬着"
        )


class TestDriverLifecycle:
    def test_startIsIdempotentAndStopLeavesNoRunningTask(self, store, monkeypatch):
        async def scenario():
            monkeypatch.setattr(ars, "_store", store)
            assert ars.startStaleSweep() is True, "首次启动未起扫描"
            assert ars.startStaleSweep() is False, "重复启动应幂等，不得起两份"
            task = ars._sweepTask
            assert task is not None
            await ars.stopStaleSweep()
            assert task.done(), "停止后仍在跑：真 app 退出会被这条不收敛的 task 拖住"
            assert ars._sweepTask is None
            await ars.stopStaleSweep()  # 可重复调用，关闭序列不因二次停止炸

        asyncio.run(scenario())
