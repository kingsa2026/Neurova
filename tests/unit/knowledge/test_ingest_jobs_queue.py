# -*- coding: utf-8 -*-
"""入站作业队列：幂等、lease 回收、重试退避、dead 与积压读数。"""
from __future__ import annotations

import time

import pytest

from neurova.knowledge.ingest_jobs import KnowledgeIngestQueue


@pytest.fixture()
def queue(tmp_path):
    q = KnowledgeIngestQueue(str(tmp_path / "jobs.db"))
    yield q
    q.close()


def testEnqueueIsIdempotentByDedupeKey(queue):
    first, created1 = queue.enqueue("wecom:c:m1", {"a": 1})
    second, created2 = queue.enqueue("wecom:c:m1", {"a": 2})

    assert first == second
    assert created1 is True and created2 is False
    assert queue.stats()["pending"] == 1


def testClaimAckMarksDone(queue):
    jobId, _ = queue.enqueue("k1", {"x": 1})
    job = queue.claim()
    assert job["job_id"] == jobId and job["attempts"] == 1

    queue.ack(jobId, {"status": "accepted", "knowledge_id": "k-1"})

    assert queue.job(jobId)["status"] == "done"
    assert queue.stats()["done"] == 1


def testNackRetriesThenDead(queue):
    jobId, _ = queue.enqueue("k1", {}, maxAttempts=2)

    first = queue.claim()
    assert first["attempts"] == 1
    queue.nack(jobId, "transient", retryable=True)
    assert queue.job(jobId)["status"] == "pending"

    # 退避到期前拿不到；等过退避后再领第二次，随即触顶 dead
    time.sleep(2.1)
    second = queue.claim()
    assert second["attempts"] == 2
    assert queue.nack(jobId, "still bad", retryable=True) == "dead"
    assert queue.stats()["dead"] == 1
    assert queue.stats()["last_dead_error"] == "still bad"


def testStaleRunningIsReclaimed(queue):
    jobId, _ = queue.enqueue("k1", {})
    queue.claim(leaseSeconds=0.01)
    time.sleep(0.05)

    reclaimed = queue.claim(leaseSeconds=60)

    assert reclaimed["job_id"] == jobId
    assert reclaimed["attempts"] == 2


def testSpecificJobClaimDoesNotJumpQueue(queue):
    oldId, _ = queue.enqueue("old", {})
    newId, _ = queue.enqueue("new", {})

    claimed = queue.claim(jobId=newId)

    assert claimed["job_id"] == newId
    assert queue.job(oldId)["status"] == "pending"


def testStatsShowsOldestPending(queue):
    queue.enqueue("k1", {})

    stats = queue.stats()

    assert stats["pending"] == 1
    assert stats["oldest_pending_age_seconds"] is not None
    assert "backlog" not in stats  # 队列读数不冒充持久队列之外的东西
