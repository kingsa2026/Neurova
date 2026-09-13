# -*- coding: utf-8 -*-
"""AgentRun 持久化状态机（Yuxi 对比 P0-1/P0-2）。

契约（docs/Neurova_Yuxi代码级对比_2026-09-13.md §2.1，对位 Yuxi
run/attempt 状态机，按单进程+SQLite 形态裁剪——channel_ingress_queue 同型模式）：
- intake：请求持久化（queued），FIFO 序按自增 id
- claim_next：同 session 至多一个 running——由部分唯一索引在库层强制；
  队头晋升 running（带 owner + 租约），已有活跃 run 时返回 None
- heartbeat/finish：owner 栅栏（陈旧 owner 拒绝，Yuxi _require_lease_owner 同语义）
- request_cancel：持久取消意图（cancel_requested 列），执行侧可轮询
- reconcile_at_startup：崩溃遗留 running → failed(process_died)、
  queued → cancelled(server_restart)——重启不丢 run 事实、不留幽灵行
- abandon：未晋升的等待方离开时置 cancelled(client_abandoned)
"""
import sqlite3
import time

import pytest

from neurova.core.agent_run_store import AgentRunStore


@pytest.fixture()
def store(tmp_path):
    s = AgentRunStore(tmp_path / "runs.db", lease_seconds=2.0)
    yield s
    s.close()


# ── intake / claim / FIFO ──────────────────────────────────────────

def test_intake_creates_queued_row(store):
    run_id = store.intake(session_id="s1", user_id="u1", agent_id="a1", message="hello")
    row = store.get(run_id)
    assert row["status"] == "queued"
    assert row["session_id"] == "s1"
    assert row["message_digest"].startswith("hello")


def test_claim_next_promotes_fifo_head(store):
    r1 = store.intake("s1", "u", "a", "first")
    r2 = store.intake("s1", "u", "a", "second")
    assert store.claim_next("s1", owner="w1") == r1
    assert store.get(r1)["status"] == "running"
    # 第二个不能被 claim（同 session 单活）
    assert store.claim_next("s1", owner="w2") is None
    assert store.get(r2)["status"] == "queued"


def test_claim_after_finish_promotes_next(store):
    r1 = store.intake("s1", "u", "a", "1")
    r2 = store.intake("s1", "u", "a", "2")
    store.claim_next("s1", "w1")
    assert store.finish(r1, owner="w1", status="completed") is True
    assert store.claim_next("s1", "w1") == r2


def test_sessions_are_independent(store):
    ra = store.intake("sa", "u", "a", "x")
    rb = store.intake("sb", "u", "a", "y")
    assert store.claim_next("sa", "w") == ra
    assert store.claim_next("sb", "w") == rb


def test_running_partial_unique_index_forced_by_db(store):
    """库层强制：绕过 API 直接插两条同 session running 必然 IntegrityError。"""
    store.intake("s1", "u", "a", "1")
    store._conn.execute(
        "INSERT INTO agent_runs (run_id, session_id, status, owner, created_at)"
        " VALUES ('x1','s1','running','w',0)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO agent_runs (run_id, session_id, status, owner, created_at)"
            " VALUES ('x2','s1','running','w',0)"
        )
    store._conn.rollback()


# ── owner 栅栏 / 心跳 ─────────────────────────────────────────────

def test_heartbeat_owner_fence(store):
    r = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", owner="w1")
    assert store.heartbeat(r, owner="w1") is True
    assert store.heartbeat(r, owner="stale-w2") is False


def test_finish_owner_fence(store):
    r = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", owner="w1")
    assert store.finish(r, owner="stale", status="completed") is False
    assert store.get(r)["status"] == "running"
    assert store.finish(r, owner="w1", status="completed") is True
    assert store.get(r)["status"] == "completed"


def test_heartbeat_extends_lease(store):
    r = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", "w1")
    store.heartbeat(r, "w1")
    assert store.get(r)["lease_expires_at"] > time.time()


# ── 取消持久意图 ──────────────────────────────────────────────────

def test_request_cancel_sets_persistent_intent(store):
    r = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", "w1")
    assert store.request_cancel("s1") == r
    assert store.cancel_requested(r) is True
    # 无活跃 run 时返回 None（调用方保持旧语义）
    assert store.request_cancel("s2") is None


# ── 启动/租约收敛 ─────────────────────────────────────────────────

def test_reconcile_at_startup_converges_orphans(store):
    r_run = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", "dead-worker")
    r_queued = store.intake("s2", "u", "a", "2")
    # 模拟"进程死亡"：新 store 实例（新进程）启动收敛
    ids_run = [r["run_id"] for r in store.reconcile_at_startup()]
    assert r_run in ids_run
    assert store.get(r_run)["status"] == "failed"
    assert store.get(r_run)["error_type"] == "process_died"
    assert store.get(r_queued)["status"] == "cancelled"
    assert store.get(r_queued)["error_type"] == "server_restart"


def test_reconcile_stale_lease_only(store):
    r = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", "w1")
    store._conn.execute(
        "UPDATE agent_runs SET lease_expires_at=? WHERE run_id=?", (time.time() - 1, r)
    )
    store._conn.commit()
    converged = store.reconcile_stale()
    assert [c["run_id"] for c in converged] == [r]
    assert store.get(r)["error_type"] == "process_died"
    # 活租约不动
    r2 = store.intake("s2", "u", "a", "2")
    store.claim_next("s2", "w1")
    assert store.reconcile_stale() == []


# ── abandon / 观测 ────────────────────────────────────────────────

def test_abandon_queued(store):
    r = store.intake("s1", "u", "a", "1")
    store.intake("s1", "u", "a", "2")
    store.abandon(r, reason="client_abandoned")
    assert store.get(r)["status"] == "cancelled"
    assert store.get(r)["error_type"] == "client_abandoned"
    # 已晋升的不能 abandon（防竞态：正在跑的不能被等待方误杀）
    store.claim_next("s1", "w1")
    assert store.abandon(store.active_run("s1")["run_id"]) is False


def test_queued_position_and_active_run(store):
    r1 = store.intake("s1", "u", "a", "1")
    r2 = store.intake("s1", "u", "a", "2")
    assert store.queued_position(r1) == 0
    assert store.queued_position(r2) == 1
    assert store.active_run("s1") is None
    store.claim_next("s1", "w1")
    assert store.active_run("s1")["run_id"] == r1
    assert store.queued_position(r2) == 0  # 队列中的相对位次


def test_stats_and_wal(store):
    r = store.intake("s1", "u", "a", "1")
    store.claim_next("s1", "w1")
    store.intake("s1", "u", "a", "2")
    st = store.stats()
    assert st == {"running": 1, "queued": 1, "terminal": 0}
    assert store._conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"


# ── 单例工厂 ──────────────────────────────────────────────────────

def test_singleton_and_reset(tmp_path, monkeypatch):
    from neurova.core import agent_run_store as mod

    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "singleton.db"))
    mod.reset_agent_run_store()
    s1 = mod.get_agent_run_store()
    s2 = mod.get_agent_run_store()
    assert s1 is s2
    mod.reset_agent_run_store()
