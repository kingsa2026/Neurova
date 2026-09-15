"""P1#12 摄取 span 时间线 + cancel。

契约（§7 #12）：
- record_span 幂等 upsert（(task, stage) 一行）；get_spans 按阶段序返回；
- cancel_task：pending/processing → cancelled（未完结 span 同步标 cancelled）；
  done/dead/不存在 → False 不谎报；
- ack/nack/dead 守卫：cancelled 任务不得被在飞 worker 复活为 done/pending/dead；
- claim 永不取 cancelled；
- span 记录失败不阻断摄取主流程（观测面故障方向）。
"""

import pytest

from neurova.knowledge.ingest_queue import SPAN_STAGES, KnowledgeIngressQueue


@pytest.fixture
def q(tmp_path):
    return KnowledgeIngressQueue(
        db_path=str(tmp_path / "ingress.db"), files_dir=tmp_path / "files"
    )


def _enqueue(q, name="a.md", data=b"# hi\ncontent"):
    return q.enqueue_upload(name, data, agent_id="default", user_id="u1")["task_id"]


class TestSpans:
    def test_upsert_and_order(self, q):
        tid = _enqueue(q)
        q.record_span(tid, "index", "running")
        q.record_span(tid, "parse", "done")
        q.record_span(tid, "index", "done", error=None)
        spans = q.get_spans(tid)
        assert [s["stage"] for s in spans] == ["parse", "index"]
        assert spans[1]["status"] == "done"  # upsert 覆盖，非两行

    def test_span_error_truncated_and_none(self, q):
        tid = _enqueue(q)
        q.record_span(tid, "parse", "failed", error="x" * 900)
        span = q.get_spans(tid)[0]
        assert span["status"] == "failed"
        assert len(span["error"]) <= 500


class TestCancel:
    def test_pending_cancelled_and_not_claimed(self, q):
        tid = _enqueue(q)
        assert q.cancel_task(tid, by="u1") is True
        assert q.get(tid)["status"] == "cancelled"
        assert q.claim("w") is None  # 不再被领取

    def test_inflight_worker_cannot_resurrect(self, q):
        tid = _enqueue(q)
        q.claim("w")  # → processing
        assert q.cancel_task(tid) is True
        q.ack(tid, ["k1"])
        assert q.get(tid)["status"] == "cancelled", "ack 不得复活 cancelled"
        q.nack(tid, "boom")
        assert q.get(tid)["status"] == "cancelled"
        q.dead(tid, "boom")
        assert q.get(tid)["status"] == "cancelled"

    def test_cancel_marks_open_spans(self, q):
        tid = _enqueue(q)
        q.claim("w")
        q.record_span(tid, "parse", "running")
        q.record_span(tid, "index", "pending")
        assert q.cancel_task(tid) is True
        by_stage = {s["stage"]: s["status"] for s in q.get_spans(tid)}
        assert by_stage["parse"] == "cancelled"
        assert by_stage["index"] == "cancelled"

    def test_cancel_terminal_states_noop(self, q):
        tid = _enqueue(q)
        q.claim("w")
        q.ack(tid, ["k1"])
        assert q.cancel_task(tid) is False
        assert q.get(tid)["status"] == "done"
        assert q.cancel_task("kin_missing") is False

    def test_cancelled_counted_in_stats(self, q):
        tid = _enqueue(q)
        q.cancel_task(tid)
        st = q.stats()
        assert st["cancelled"] == 1 and st["pending"] == 0


class TestReconcileIgnoresCancelled:
    def test_startup_reconcile_does_not_resurrect(self, q):
        tid = _enqueue(q)
        q.claim("w")
        q.cancel_task(tid)
        # 模拟"崩溃恢复"语义：reconcile 只归位 processing，cancelled 不动
        ids = q.reconcile_at_startup()
        assert tid not in ids
        assert q.get(tid)["status"] == "cancelled"


def test_stage_names_are_canonical():
    assert SPAN_STAGES == ("parse", "extract", "index")
