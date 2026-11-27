import asyncio
import sqlite3
import time

import pytest

from neurova.evolution.job_queue import EvolutionJobQueue


def _row(queue: EvolutionJobQueue, jobId: str):
    return queue._conn.execute(
        "SELECT * FROM evolution_jobs WHERE id=?", (jobId,)
    ).fetchone()


def testV1DatabaseMigratesWithoutLosingJob(tmp_path):
    dbPath = tmp_path / "jobs.db"
    conn = sqlite3.connect(dbPath)
    conn.executescript(
        """
        CREATE TABLE evolution_jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','running','done','failed_retryable','failed')),
            attempts INTEGER NOT NULL DEFAULT 0,
            locked_by TEXT,
            locked_at REAL,
            result_json TEXT,
            error TEXT,
            idempotency_key TEXT UNIQUE,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        );
        PRAGMA user_version=1;
        INSERT INTO evolution_jobs
            (id, kind, payload_json, status, created_at, updated_at)
        VALUES ('legacy-job', 'j', '{"keep": true}', 'pending', 1.0, 1.0);
        """
    )
    conn.commit()
    conn.close()

    queue = EvolutionJobQueue(db_path=dbPath)
    columns = {row[1] for row in queue._conn.execute("PRAGMA table_info(evolution_jobs)")}
    assert "lease_token" in columns
    job = queue.claim("worker")
    assert job["id"] == "legacy-job"
    assert job["payload"] == {"keep": True}
    assert job["lease_token"]
    queue.close()


def testExpiredWorkerCannotCompleteReclaimedJob(tmp_path):
    queue = EvolutionJobQueue(db_path=tmp_path / "jobs.db", lease_seconds=60)
    queue.enqueue("j", {})
    oldJob = queue.claim("old-worker")
    assert oldJob["lease_token"]

    queue._conn.execute(
        "UPDATE evolution_jobs SET locked_at=0 WHERE id=?", (oldJob["id"],)
    )
    queue._conn.commit()
    assert queue.recover_stale() == 1
    newJob = queue.claim("new-worker")
    assert newJob["lease_token"] != oldJob["lease_token"]

    assert queue.complete(oldJob["id"], oldJob["lease_token"], {"writer": "old"}) is False
    row = _row(queue, oldJob["id"])
    assert row["status"] == "running"
    assert row["locked_by"] == "new-worker"
    assert row["result_json"] is None

    assert queue.complete(newJob["id"], newJob["lease_token"], {"writer": "new"}) is True
    assert _row(queue, oldJob["id"])["result_json"] == '{"writer": "new"}'
    queue.close()


def testExpiredWorkerCannotFailReclaimedJob(tmp_path):
    queue = EvolutionJobQueue(
        db_path=tmp_path / "jobs.db", max_attempts=3, lease_seconds=60
    )
    queue.enqueue("j", {})
    oldJob = queue.claim("old-worker")
    queue._conn.execute(
        "UPDATE evolution_jobs SET locked_at=0 WHERE id=?", (oldJob["id"],)
    )
    queue._conn.commit()
    queue.recover_stale()
    newJob = queue.claim("new-worker")

    assert queue.fail(oldJob["id"], oldJob["lease_token"], "old failure") is False
    row = _row(queue, oldJob["id"])
    assert row["status"] == "running"
    assert row["locked_by"] == "new-worker"
    assert row["error"] is None

    assert queue.fail(newJob["id"], newJob["lease_token"], "new failure") is True
    row = _row(queue, oldJob["id"])
    assert row["status"] == "failed_retryable"
    assert row["error"] == "new failure"
    queue.close()


def testRenewLeaseExtendsExpiryAndRejectsStaleToken(tmp_path):
    queue = EvolutionJobQueue(db_path=tmp_path / "jobs.db", lease_seconds=1)
    queue.enqueue("j", {})
    oldJob = queue.claim("old-worker")
    before = _row(queue, oldJob["id"])["locked_at"]

    time.sleep(0.05)
    assert queue.renewLease(oldJob["id"], oldJob["lease_token"]) is True
    assert _row(queue, oldJob["id"])["locked_at"] > before

    queue._conn.execute(
        "UPDATE evolution_jobs SET locked_at=0 WHERE id=?", (oldJob["id"],)
    )
    queue._conn.commit()
    queue.recover_stale()
    newJob = queue.claim("new-worker")

    assert queue.renewLease(oldJob["id"], oldJob["lease_token"]) is False
    assert _row(queue, oldJob["id"])["locked_by"] == "new-worker"
    assert newJob["lease_token"] != oldJob["lease_token"]
    queue.close()


def testDrainHeartbeatKeepsLongJobLeaseAlive(tmp_path):
    dbPath = tmp_path / "jobs.db"
    queue = EvolutionJobQueue(db_path=dbPath, lease_seconds=2)
    observer = EvolutionJobQueue(db_path=dbPath, lease_seconds=2)
    queue.enqueue("j", {})

    def handler(job):
        time.sleep(1.2)
        assert observer.recover_stale() == 0
        time.sleep(1.2)
        assert observer.recover_stale() == 0

    assert queue.drain("worker", handler, max_jobs=1) == 1
    done = queue._conn.execute(
        "SELECT status FROM evolution_jobs WHERE status='done'"
    ).fetchone()
    assert done is not None
    observer.close()
    queue.close()


def testDrainDoesNotWriteResultAfterLeaseLost(tmp_path):
    queue = EvolutionJobQueue(db_path=tmp_path / "jobs.db", lease_seconds=60)
    queue.enqueue("j", {})
    reclaimed = {}

    def handler(job):
        with queue._lock:
            queue._conn.execute(
                "UPDATE evolution_jobs SET locked_at=0 WHERE id=?", (job["id"],)
            )
            queue._conn.commit()
            assert queue.recover_stale() == 1
            reclaimed["job"] = queue.claim("new-worker")

    assert queue.drain("old-worker", handler, max_jobs=1) == 1
    row = _row(queue, reclaimed["job"]["id"])
    assert row["status"] == "running"
    assert row["locked_by"] == "new-worker"
    assert row["result_json"] is None
    queue.close()


@pytest.mark.asyncio
async def testDrainAsyncHeartbeatKeepsLongJobLeaseAlive(tmp_path):
    dbPath = tmp_path / "jobs.db"
    queue = EvolutionJobQueue(db_path=dbPath, lease_seconds=2)
    observer = EvolutionJobQueue(db_path=dbPath, lease_seconds=2)
    queue.enqueue("j", {})

    async def handler(job):
        await asyncio.sleep(1.2)
        assert observer.recover_stale() == 0
        await asyncio.sleep(1.2)
        assert observer.recover_stale() == 0

    assert await queue.drainAsync("worker", handler, max_jobs=1) == 1
    done = queue._conn.execute(
        "SELECT status FROM evolution_jobs WHERE status='done'"
    ).fetchone()
    assert done is not None
    observer.close()
    queue.close()
