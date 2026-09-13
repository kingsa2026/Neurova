# -*- coding: utf-8 -*-
"""知识摄取持久队列（Yuxi 对比 P1 #9：Durable Task 化，channel_ingress 同型）。

契约：
- enqueue 幂等（dedupe_key UNIQUE）；claim 租约 + FIFO；max_attempts → dead-letter
- 启动 reconcile：processing 遗留归 pending（崩溃重跑），过期文件 GC 留证
- 端点 sync=true 默认=现行为不降；sync=false 落文件+入队即返 {task_id, queued}
- handler 真跑 _import_file_data（测试注入替身）
"""
import json

import pytest

from neurova.knowledge.ingest_queue import KnowledgeIngressQueue, task_status


@pytest.fixture()
def q(tmp_path):
    queue = KnowledgeIngressQueue(tmp_path / "ingress.db", files_dir=tmp_path / "files", lease_seconds=2.0)
    yield queue
    queue.close()


def test_enqueue_dedupe_idempotent(q):
    t1 = q.enqueue_upload(filename="a.txt", data=b"hello", agent_id="ag", user_id="u1")
    t2 = q.enqueue_upload(filename="a.txt", data=b"hello", agent_id="ag", user_id="u1")
    assert t1["task_id"] == t2["task_id"]
    t3 = q.enqueue_upload(filename="a.txt", data=b"world", agent_id="ag", user_id="u1")
    assert t3["task_id"] != t1["task_id"]  # 内容异=新任务


def test_claim_fifo_with_lease(q):
    a = q.enqueue_upload("a.txt", b"1", "ag", "u")["task_id"]
    b = q.enqueue_upload("b.txt", b"2", "ag", "u")["task_id"]
    assert q.claim("w1")["task_id"] == a
    assert q.claim("w2")["task_id"] == b
    # 租约未过期第三次拿不到
    assert q.claim("w3") is None


def test_lease_expiry_reclaimable(q):
    import time

    tid = q.enqueue_upload("a.txt", b"1", "ag", "u")["task_id"]
    assert q.claim("w1")["task_id"] == tid
    time.sleep(2.1)
    assert q.claim("w2")["task_id"] == tid  # 过期可被接管


def test_dead_letter_after_max_attempts(q):
    tid = q.enqueue_upload("a.txt", b"1", "ag", "u")["task_id"]
    for _ in range(q.max_attempts):
        ev = q.claim("w")
        q.nack(ev["task_id"], "boom")
    assert task_status(q.get(tid)) == "dead"
    assert q.claim("w") is None


def test_ack_records_result(q):
    tid = q.enqueue_upload("a.txt", b"1", "ag", "u")["task_id"]
    ev = q.claim("w")
    q.ack(tid, item_ids=["k1", "k2"])
    row = q.get(tid)
    assert row["status"] == "done"
    assert json.loads(row["result_ids"]) == ["k1", "k2"]


def test_startup_reconcile_resets_processing(q):
    tid = q.enqueue_upload("a.txt", b"1", "ag", "u")["task_id"]
    q.claim("dead-worker")
    # 模拟重启：processing 行归 pending
    converged = q.reconcile_at_startup()
    assert tid in converged
    assert q.get(tid)["status"] == "pending"


def test_stats_and_url_enqueue(q):
    q.enqueue_url(url="https://example.com/x", title_hint="x", agent_id="ag", user_id="u")
    st = q.stats()
    assert st["pending"] == 1
    row = q.list_recent()[0]
    assert row["source"] == "url" and row["url"] == "https://example.com/x"
