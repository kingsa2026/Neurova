# -*- coding: utf-8 -*-
"""B4 排队 run 管理面 单元测试。

覆盖：
- enqueue 位次（从 1 起）与优先级插队重排；
- setPriority 返回新位次；非法档位经 mailbox.normalizePriority 归一；
- cancelQueued 移出并留痕；队列中不存在显式 KeyError；
- editTask 三态：排队中 requeued / 在跑 steer_fn 注入 steered / 双不可能诚实 rejected；
- snapshot 按优先级降序 + 同级先来先服务的稳定序。
"""

import pytest

from neurova.agent.run_queue import RunQueue


class TestEnqueueAndPosition:
    def test_enqueue_returns_position_from_one(self):
        queue = RunQueue()
        assert queue.enqueue("s1", "任务一") == 1
        assert queue.enqueue("s2", "任务二") == 2

    def test_higher_priority_jumps_ahead(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一")
        queue.enqueue("s2", "任务二")
        assert queue.enqueue("s3", "任务三", priority="urgent") == 1, "urgent 插队到首位"
        assert queue.position("s3") == 1
        assert queue.position("s1") == 2
        assert queue.position("s2") == 3

    def test_position_unknown_is_zero(self):
        assert RunQueue().position("ghost") == 0

    def test_enqueue_requires_id_and_task(self):
        queue = RunQueue()
        with pytest.raises(ValueError):
            queue.enqueue("", "任务")
        with pytest.raises(ValueError):
            queue.enqueue("s1", "   ")

    def test_duplicate_enqueue_rejected(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一")
        with pytest.raises(ValueError):
            queue.enqueue("s1", "同一 run 重复入队")

    def test_enqueue_invalid_priority_normalized_to_normal(self):
        # 复用 mailbox.normalizePriority：非法档位不臆造，一律落 normal
        queue = RunQueue()
        queue.enqueue("s1", "任务一", priority="turbo")
        assert queue.snapshot()[0]["priority"] == "normal"


class TestSetPriority:
    def test_set_priority_returns_new_position(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一")
        queue.enqueue("s2", "任务二")
        queue.enqueue("s3", "任务三")
        assert queue.setPriority("s3", "high") == 1
        assert queue.position("s3") == 1
        assert queue.position("s1") == 2
        assert queue.position("s2") == 3
        # 降回 normal：恢复先来先服务的原序
        assert queue.setPriority("s3", "normal") == 3
        assert queue.position("s1") == 1

    def test_set_priority_invalid_value_falls_back_to_normal(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一", priority="high")
        queue.enqueue("s2", "任务二")
        assert queue.position("s1") == 1, "high 先行"
        # "turbo" 非法 → 归一 normal → 与 s2 同级，按先来先服务 s1 仍在前
        assert queue.setPriority("s1", "turbo") == 1
        assert queue.position("s2") == 2

    def test_set_priority_unknown_run_raises(self):
        with pytest.raises(KeyError):
            RunQueue().setPriority("ghost", "high")


class TestCancelQueued:
    def test_cancel_removes_from_queue_and_returns_trace(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一", priority="high")
        queue.enqueue("s2", "任务二")
        trace = queue.cancelQueued("s1")
        assert trace["subagent_id"] == "s1"
        assert trace["task"] == "任务一"
        assert trace["priority"] == "high"
        assert trace["position_at_cancel"] == 1
        assert "queued_at" in trace
        assert "cancelled_at" in trace
        assert queue.position("s1") == 0
        assert queue.position("s2") == 1, "取消后余队重排"

    def test_cancel_unknown_run_raises_keyerror(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一")
        with pytest.raises(KeyError):
            queue.cancelQueued("ghost")
        queue.cancelQueued("s1")  # 第一次取消成功
        with pytest.raises(KeyError):
            queue.cancelQueued("s1")  # 已取消的再取消也显式报错，不静默


class TestEditTask:
    def test_edit_pending_task_requeues(self):
        queue = RunQueue()
        queue.enqueue("s1", "旧任务书")
        result = queue.editTask("s1", "新任务书")
        assert result["mode"] == "requeued"
        assert result["subagent_id"] == "s1"
        assert queue.snapshot()[0]["task"] == "新任务书"

    def test_edit_queued_takes_precedence_over_steer(self):
        # 还在队列里（未开跑）：即便传了 steer_fn 也走 requeued，不误发注入
        queue = RunQueue()
        queue.enqueue("s1", "旧任务书")
        called = []

        def steer_fn(sid, text):
            called.append((sid, text))
            return True

        result = queue.editTask("s1", "新任务书", steer_fn=steer_fn)
        assert result["mode"] == "requeued"
        assert called == [], "排队中的 run 不应触发 steer 注入"

    def test_edit_running_task_steers_via_callback(self):
        # 不在队列（已开跑）：由调用方注入的 steer_fn 送达
        queue = RunQueue()
        queue.enqueue("s1", "排队任务")
        seen = []

        def steer_fn(sid, text):
            seen.append((sid, text))
            return True

        result = queue.editTask("s_running", "改后的任务书", steer_fn=steer_fn)
        assert result["mode"] == "steered"
        assert result["subagent_id"] == "s_running"
        assert seen == [("s_running", "改后的任务书")]

    def test_edit_task_double_impossible_rejected_without_steer(self):
        queue = RunQueue()
        result = queue.editTask("s_missing", "新任务书")
        assert result["mode"] == "rejected"
        assert result["reason"], "诚实拒绝必须带原因"

    def test_edit_task_rejected_when_steer_fn_returns_false(self):
        queue = RunQueue()
        result = queue.editTask("s_missing", "新任务书", steer_fn=lambda sid, text: False)
        assert result["mode"] == "rejected"
        assert result["reason"]

    def test_edit_task_rejected_when_steer_fn_raises(self):
        queue = RunQueue()

        def boom(sid, text):
            raise RuntimeError("注入通道断了")

        result = queue.editTask("s_missing", "新任务书", steer_fn=boom)
        assert result["mode"] == "rejected"
        assert "注入通道断了" in result["reason"], "注入失败原因随拒绝结果带出"

    def test_edit_task_requires_non_empty_task(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一")
        with pytest.raises(ValueError):
            queue.editTask("s1", "  ")


class TestSnapshot:
    def test_snapshot_priority_desc_then_fifo(self):
        queue = RunQueue()
        queue.enqueue("n1", "任务一")
        queue.enqueue("u1", "紧急任务", priority="urgent")
        queue.enqueue("n2", "任务二")
        queue.enqueue("h1", "高优任务", priority="high")
        snapshot = queue.snapshot()
        assert [e["subagent_id"] for e in snapshot] == ["u1", "h1", "n1", "n2"]
        assert [e["position"] for e in snapshot] == [1, 2, 3, 4]

    def test_snapshot_entries_carry_required_fields(self):
        queue = RunQueue()
        queue.enqueue("s1", "任务一", priority="high")
        entry = queue.snapshot()[0]
        assert set(entry) >= {"position", "subagent_id", "priority", "task", "queued_at"}
        assert entry["priority"] == "high"
        assert entry["task"] == "任务一"

    def test_snapshot_is_stable_across_calls(self):
        queue = RunQueue()
        queue.enqueue("n1", "任务一")
        queue.enqueue("u1", "紧急任务", priority="urgent")
        queue.enqueue("n2", "任务二")
        first = queue.snapshot()
        second = queue.snapshot()
        assert second == first, "重复读取队列序稳定"

    def test_snapshot_empty_queue(self):
        assert RunQueue().snapshot() == []
