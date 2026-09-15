"""P1-4 进化异步作业队列

队列语义（不测 post_chat 行为改道，只测队列本体）：
- enqueue 幂等（同 idempotency_key 不双行）；
- claim 原子（多线程并发领取互不重复）；
- 失败重试阶梯：attempts<max → failed_retryable，否则终态 failed；
- 租约崩溃恢复：running 超时 → recover_stale 重置可再领；
- drain 处理条数上限与 handler 异常隔离。
"""

import threading

import pytest

from neurova.evolution.job_queue import (
    EvolutionJobQueue,
    get_evolution_job_queue,
    reset_evolution_job_queue,
)


@pytest.fixture
def q(tmp_path):
    queue = EvolutionJobQueue(db_path=tmp_path / "jobs.db", max_attempts=2, lease_seconds=3600)
    yield queue
    queue.close()


def test_enqueue_creates_row(q):
    r = q.enqueue("skill_evolution_pass", {"skill_id": "s1"}, idempotency_key="k1")
    assert r["created"] is True and r["deduped"] is False
    assert q.pending_count() == 1


def test_enqueue_idempotent_dedup(q):
    a = q.enqueue("j", {"x": 1}, idempotency_key="same")
    b = q.enqueue("j", {"x": 2}, idempotency_key="same")
    assert a["job_id"] == b["job_id"]
    assert b["created"] is False and b["deduped"] is True
    assert q.pending_count() == 1


def test_claim_returns_payload(q):
    q.enqueue("j", {"tool_sequence": ["a", "b"]}, idempotency_key="p1")
    job = q.claim("w1")
    assert job is not None
    assert job["payload"] == {"tool_sequence": ["a", "b"]}
    assert job["attempts"] == 1
    assert q.pending_count() == 0  # running 不算 pending


def test_claim_none_when_empty(q):
    assert q.claim("w1") is None


def test_concurrent_claim_disjoint(tmp_path):
    """两线程并发领取不得拿到同一作业（BEGIN IMMEDIATE 原子租约）。"""
    queue = EvolutionJobQueue(db_path=tmp_path / "c.db")
    for i in range(10):
        queue.enqueue("j", {"i": i})
    seen = []
    seen_lock = threading.Lock()

    def worker(name):
        for _ in range(20):
            job = queue.claim(name)
            if job is None:
                break
            with seen_lock:
                seen.append(job["id"])

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(seen) == len(set(seen)), "并发领取出现重复作业"
    assert len(seen) == 10
    queue.close()


def test_fail_ladder_then_terminal(q):
    q.enqueue("j", {})
    job = q.claim("w")
    q.fail(job["id"], "boom")  # attempts=1 < max2 → retryable
    assert q.pending_count() == 1
    job2 = q.claim("w")
    q.fail(job2["id"], "boom again")  # attempts=2 == max → failed 终态
    assert q.pending_count() == 0
    assert q.claim("w") is None


def test_recover_stale_releases_expired_lease(tmp_path):
    queue = EvolutionJobQueue(db_path=tmp_path / "s.db", lease_seconds=1)
    queue.enqueue("j", {})
    job = queue.claim("dead-worker")
    # 伪造租约过期
    queue._conn.execute("UPDATE evolution_jobs SET locked_at=? WHERE id=?", (0.0, job["id"]))
    queue._conn.commit()
    assert queue.recover_stale() == 1
    assert queue.pending_count() == 1
    reclaimed = queue.claim("new-worker")
    assert reclaimed["id"] == job["id"]
    queue.close()


def test_drain_counts_and_isolates_handler_errors(q):
    q.enqueue("good", {})
    q.enqueue("bad", {})
    calls = {"n": 0}

    def handler(job):
        calls["n"] += 1
        if job["payload"].get("boom"):
            raise RuntimeError("handler crash")

    # 让第二条注定失败
    q._conn.execute("UPDATE evolution_jobs SET payload_json='{\"boom\":true}' WHERE kind='bad'")
    q._conn.commit()
    processed = q.drain("w", handler, max_jobs=5)
    assert processed == 2
    assert calls["n"] == 2
    # 失败那条回可重试池
    assert q.pending_count() == 1


def test_drain_respects_max_jobs(q):
    for _ in range(5):
        q.enqueue("j", {})
    processed = q.drain("w", lambda job: None, max_jobs=2)
    assert processed == 2
    assert q.pending_count() == 3


def test_close_and_reopen_persists(tmp_path):
    q1 = EvolutionJobQueue(db_path=tmp_path / "p.db")
    q1.enqueue("j", {"keep": 1}, idempotency_key="persist")
    q1.close()
    q2 = EvolutionJobQueue(db_path=tmp_path / "p.db")
    assert q2.pending_count() == 1
    job = q2.claim("w")
    assert job["payload"] == {"keep": 1}
    q2.close()


# ── post_chat 双态接线 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_post_chat_queue_off_uses_inline_pass(monkeypatch, tmp_path):
    """默认关：_step_rsi_iteration 直接跑 pass（现状语义），不产生队列作业。"""
    from unittest.mock import MagicMock

    import neurova.skills.skill_service as ss_mod
    from neurova.post_chat_pipeline import PostChatPipeline

    class _NoopService:
        def __init__(self, agent_id, skills_dir=None):
            pass

    monkeypatch.setattr(ss_mod, "SkillService", _NoopService)
    # 默认已开（SettingPage 收口 2026-09-15）——off 态用 env 显式关（运维逃生门）
    monkeypatch.setenv("NEUROVA_EVOLUTION_QUEUE", "0")
    ran = {"pass": 0}

    async def _fake_pass(*a, **k):
        ran["pass"] += 1
        return []

    monkeypatch.setattr("neurova.post_chat_pipeline.run_skill_evolution_pass", _fake_pass)
    agent = MagicMock()
    agent.config.agent_id = "x"
    p = PostChatPipeline(agent)
    await p._step_rsi_iteration()
    assert ran["pass"] >= 1


@pytest.mark.asyncio
async def test_post_chat_queue_on_enqueues_and_drains(monkeypatch, tmp_path):
    """开关开：改道为 enqueue + drain，pass 经 handler 执行一次、队列作业终态 done。"""
    from unittest.mock import MagicMock

    import neurova.skills.skill_service as ss_mod
    from neurova.evolution.job_queue import EvolutionJobQueue
    import neurova.post_chat_pipeline as pc
    from neurova.post_chat_pipeline import PostChatPipeline

    class _NoopService:
        def __init__(self, agent_id, skills_dir=None):
            pass

    monkeypatch.setattr(ss_mod, "SkillService", _NoopService)
    calls = {"pass": 0}

    async def _fake_pass(*a, **k):
        calls["pass"] += 1
        return []

    monkeypatch.setattr(pc, "run_skill_evolution_pass", _fake_pass)
    monkeypatch.setenv("NEUROVA_EVOLUTION_QUEUE", "1")
    q = EvolutionJobQueue(db_path=tmp_path / "pc.db", max_attempts=2, lease_seconds=3600)
    made = {"q": q}

    monkeypatch.setattr(
        "neurova.evolution.job_queue.get_evolution_job_queue", lambda *a, **k: q
    )

    agent = MagicMock()
    agent.config.agent_id = "y"
    p = PostChatPipeline(agent)
    await p._step_rsi_iteration()
    assert q.pending_count() == 0  # 已 drain 干净
    assert calls["pass"] >= 1  # drain handler 跑过 pass
    q.close()


# ── 启动租约恢复（崩溃后不卡 running）────────────────────────


def test_startup_recovery_frees_stale_running(tmp_path, monkeypatch):
    import neurova.evolution.job_queue as jq

    q = EvolutionJobQueue(db_path=tmp_path / "r.db", lease_seconds=1)
    q.enqueue("j", {})
    job = q.claim("crashed")
    q._conn.execute("UPDATE evolution_jobs SET locked_at=? WHERE id=?", (0.0, job["id"]))
    q._conn.commit()
    reset_evolution_job_queue()
    monkeypatch.setattr(jq, "_queue_singleton", q)
    from neurova.evolution.job_queue import get_evolution_job_queue

    get_evolution_job_queue()  # 复用注入的单例
    assert q.recover_stale() == 1
    assert q.pending_count() == 1
    q.close()
