"""资源治理 P2-4：swarm 僵死槽记账回收接线。

_reapStaleRunSlots 只做**记账修复**——回收「租约过期且任务已终态」的
run（模型槽计数 + _runs 表）；仍在跑的任务不动（生命周期由
runtimeBudgetSec 兜底）。TTL=0（缺省）恒不回收。
"""

import threading
from types import SimpleNamespace

from neurova.agent.swarm import SwarmManager


def _manager_with(runs: dict, tasks: dict, model_active: dict):
    mgr = object.__new__(SwarmManager)
    mgr._lock = threading.RLock()
    mgr._runs = runs
    mgr._tasks = tasks
    mgr._model_active = model_active
    return mgr


def _run(slot_model=None, subagent_id="s1"):
    return SimpleNamespace(slot_model=slot_model, subagent_id=subagent_id)


class _DoneTask:
    def done(self):
        return True


class _RunningTask:
    def done(self):
        return False


class TestReapStaleRunSlots:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("NEUROVA_RUN_LEASE_TTL_S", raising=False)
        run = _run(slot_model="m1")
        mgr = _manager_with({"s1": run}, {"s1": _DoneTask()}, {"m1": 1})
        assert mgr._reapStaleRunSlots() == 0
        assert "s1" in mgr._runs

    def test_reclaims_finished_task_with_expired_lease(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RUN_LEASE_TTL_S", "60")
        run = _run(slot_model="m1")
        mgr = _manager_with({"s1": run}, {"s1": _DoneTask()}, {"m1": 1})
        # 直接构造过期租约（expire_at=1.0 在单调钟下必已过期）
        board = mgr._runLeaseBoard()
        board._leases["s1"] = ("s1", 1.0)
        assert mgr._reapStaleRunSlots() == 1
        assert "s1" not in mgr._runs
        assert "m1" not in mgr._model_active
        assert board._leases.get("s1") is None

    def test_running_task_is_not_reclaimed(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RUN_LEASE_TTL_S", "60")
        run = _run(slot_model="m1")
        mgr = _manager_with({"s1": run}, {"s1": _RunningTask()}, {"m1": 1})
        board = mgr._runLeaseBoard()
        board._leases["s1"] = ("s1", 1.0)  # 过期，但任务仍在跑
        assert mgr._reapStaleRunSlots() == 0
        assert "s1" in mgr._runs
        # 过期租约已被回收清空（记账修复因任务仍在跑而跳过，槽计数不动）
        assert board._leases.get("s1") is None
        assert mgr._model_active == {"m1": 1}

    def test_no_lease_no_reclaim(self, monkeypatch):
        monkeypatch.setenv("NEUROVA_RUN_LEASE_TTL_S", "60")
        run = _run(slot_model="m1")
        mgr = _manager_with({"s1": run}, {"s1": _DoneTask()}, {"m1": 1})
        assert mgr._reapStaleRunSlots() == 0
        assert "s1" in mgr._runs

    def test_lease_acquired_on_spawn_path_board(self, monkeypatch):
        # 板子语义：同 owner 重入允许，异主未过期拒绝（spawn 重入/并发派生）
        monkeypatch.setenv("NEUROVA_RUN_LEASE_TTL_S", "60")
        mgr = _manager_with({}, {}, {})
        board = mgr._runLeaseBoard()
        assert board.acquire("s1", "s1", 60) is True
        assert board.acquire("s1", "s2", 60) is False
        assert board.acquire("s1", "s1", 60) is True
