# -*- coding: utf-8 -*-
"""批三接线集成测试：B1 投递账本 / B4 排队管理面 / A1 终态质量分级消费。

- B1：pushParentMail 唯一写点同步落投递单（入箱 claimed、失败 dispose），
  父 run 已终态时补投一次（catch-up），无通道时诚实弃投留痕；
- B4：spawn 与 spawned 事件同点入队、开跑出队、cancelQueuedRun 落诚实终态、
  editRunTask 三态分流（requeued/steered/rejected）；
- A1：transitionRun 写入的 terminal_quality 进终态事件与上报信封投影。
"""
import time

import pytest

import neurova.agent.swarm as swarm_module
from neurova.agent.swarm import (
    SUBAGENT_COMPLETED,
    SUBAGENT_FAILED,
    SUBAGENT_PENDING,
    SUBAGENT_RUNNING,
    SubAgentRun,
    get_swarm_manager,
    reset_swarm_manager,
)
from neurova.agent.swarm_support import transitionRun
from neurova.core.steer_queue import get_steer_queue, reset_steer_queue


@pytest.fixture
def swarm():
    reset_swarm_manager()
    from neurova.agent.mailbox import reset_agent_mailbox

    reset_agent_mailbox()
    reset_steer_queue()
    # 单例账本/队列清场（测试隔离；生产为进程级单例）
    ledger = swarm_module._deliveryLedger()
    ledger._tickets.clear()
    ledger._byMessageId.clear()
    swarm_module._runQueue()._entries.clear()
    return get_swarm_manager()


def _run(swarm, sid="run-x", status=SUBAGENT_PENDING, parent="", member_session="",
         origin="chat", session_id="sess-1", depth=1):
    run = SubAgentRun(
        subagent_id=sid, depth=depth, agent_id="agent-a", agent_name="A",
        task="样例任务", origin=origin, session_id=session_id,
        member_session_id=member_session, parent_subagent_id=parent, status=status,
    )
    with swarm._lock:
        swarm._runs[sid] = run
    return run


class TestDeliveryLedgerWiring:
    def test_push_records_and_claims_ticket(self, swarm):
        from neurova.agent.mailbox import get_agent_mailbox

        _run(swarm, "parent-1", status=SUBAGENT_RUNNING)
        child = _run(swarm, "child-1", status=SUBAGENT_COMPLETED, parent="parent-1")
        assert swarm.pushParentMail(child, "子Agent终态", {"kind": "subagent_terminal"}) is True
        tickets = swarm_module._deliveryLedger().snapshot()
        assert len(tickets) == 1
        assert tickets[0]["status"] == "claimed"
        assert tickets[0]["parent_run_id"] == "parent-1"
        assert get_agent_mailbox().pending("sess-1") == 1

    def test_mailbox_ack_mirrors_to_ledger_acknowledged(self, swarm):
        """B1 闭环：邮箱消费侧 ack 后，投递单经 messageId 镜像到 acknowledged。"""
        from neurova.agent.delegated_delivery import getDeliveryLedger
        from neurova.agent.mailbox import get_agent_mailbox

        _run(swarm, "parent-1b", status=SUBAGENT_RUNNING)
        child = _run(swarm, "child-1b", status=SUBAGENT_COMPLETED, parent="parent-1b")
        assert swarm.pushParentMail(child, "子Agent终态", {"kind": "subagent_terminal"}) is True
        ledger = getDeliveryLedger()
        ticket = ledger.snapshot()[0]
        assert ticket["status"] == "claimed"
        mails = get_agent_mailbox().lease("sess-1")
        assert len(mails) == 1
        # 消费侧确认（loops/base.py 排空后的镜像路径）
        assert ledger.acknowledgeByMessageId(mails[0]["messageId"]) is True
        assert ledger.get(ticket["ticket_id"])["status"] == "acknowledged"
        # 幂等：重复确认不炸；未知 id 诚实 False
        assert ledger.acknowledgeByMessageId(mails[0]["messageId"]) is True
        assert ledger.acknowledgeByMessageId("no-such-mid") is False

    def test_top_level_push_has_no_ticket(self, swarm):
        from neurova.agent.mailbox import get_agent_mailbox

        child = _run(swarm, "child-top", status=SUBAGENT_COMPLETED, parent="")
        assert swarm.pushParentMail(child, "子Agent终态", {"kind": "subagent_terminal"}) is True
        assert swarm_module._deliveryLedger().snapshot() == []
        assert get_agent_mailbox().pending("sess-1") == 1

    def test_catchup_when_parent_already_finished(self, swarm):
        from neurova.agent.mailbox import get_agent_mailbox

        _run(swarm, "parent-2", status=SUBAGENT_COMPLETED)
        child = _run(swarm, "child-2", status=SUBAGENT_COMPLETED, parent="parent-2")
        assert swarm.pushParentMail(child, "子Agent终态", {"report": "产出"}) is True
        tickets = swarm_module._deliveryLedger().snapshot()
        assert len(tickets) == 1
        assert tickets[0]["redelivered"] is True, "父已收工：开出即补投一次"
        # 原件 + 补投件都在箱（宁重不丢；消费方按 messageId 判重）
        assert get_agent_mailbox().pending("sess-1") == 2

    def test_catchup_disposes_without_channel(self, swarm):
        ledger = swarm_module._deliveryLedger()
        ledger.record("child-3", "ghost-parent", "子Agent终态", {"r": 1}, "mid-3")
        result = swarm._deliveryCatchUp("ghost-parent")
        assert result == []
        tickets = ledger.snapshot()
        assert tickets[0]["status"] == "disposed"
        assert tickets[0]["disposed_reason"] == "parent_run_finished_no_channel"

    def test_terminal_convergence_triggers_catchup(self, swarm):
        """父 run 终态收口（transitionRun）后，名下未销账投递单被补投。"""
        from neurova.agent.mailbox import get_agent_mailbox

        parent = _run(swarm, "parent-4", status=SUBAGENT_RUNNING)
        ledger = swarm_module._deliveryLedger()
        ledger.record("child-4", "parent-4", "子Agent终态", {"r": 1}, "mid-4")
        transitionRun(parent, SUBAGENT_COMPLETED, cause="candidate_merged")
        parent.finished_at = time.time()
        swarm._deliveryCatchUp("parent-4")
        tickets = ledger.snapshot()
        assert tickets[0]["redelivered"] is True
        assert get_agent_mailbox().pending("sess-1") == 1  # 补投件入箱


class TestRunQueueWiring:
    def test_register_and_dequeue_on_start(self, swarm):
        run = _run(swarm, "q-run-1")
        swarm._registerRunQueue(run)
        assert swarm.runQueueSnapshot()[0]["subagent_id"] == "q-run-1"
        assert swarm.runQueueSnapshot()[0]["position"] == 1
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        swarm_module._runQueue().dequeue(run.subagent_id)
        assert swarm.runQueueSnapshot() == []

    def test_cancel_queued_run_lands_honest_terminal(self, swarm):
        run = _run(swarm, "q-run-2")
        swarm._registerRunQueue(run)
        entry = swarm.cancelQueuedRun("q-run-2")
        assert entry["subagent_id"] == "q-run-2"
        assert entry["position_at_cancel"] == 1
        assert run.status == SUBAGENT_FAILED
        assert run.cause == "subagent_cancelled"
        assert "队列管理面取消" in run.error
        assert swarm.runQueueSnapshot() == []

    def test_cancel_queued_run_missing_raises(self, swarm):
        with pytest.raises(KeyError):
            swarm.cancelQueuedRun("no-such-run")

    def test_edit_task_requeued_updates_run(self, swarm):
        run = _run(swarm, "q-run-3")
        swarm._registerRunQueue(run)
        result = swarm.editRunTask("q-run-3", "改后的任务书")
        assert result["mode"] == "requeued"
        assert result["position"] == 1
        assert run.task == "改后的任务书"

    def test_edit_task_steered_via_steer_queue(self, swarm):
        run = _run(swarm, "q-run-4", status=SUBAGENT_RUNNING, member_session="ms-4")
        result = swarm.editRunTask("q-run-4", "运行中补充指令")
        assert result["mode"] == "steered"
        assert get_steer_queue().pending("ms-4") == 1
        assert run.task == "样例任务", "steer 是插话不是改写，原任务书不变"

    def test_edit_task_rejected_when_neither(self, swarm):
        _run(swarm, "q-run-5", status=SUBAGENT_FAILED)
        result = swarm.editRunTask("q-run-5", "无论如何")
        assert result["mode"] == "rejected"
        assert result["reason"]

    def test_queue_priority_reorder(self, swarm):
        for sid in ("q-a", "q-b", "q-c"):
            swarm._registerRunQueue(_run(swarm, sid))
        swarm.setRunQueuePriority("q-c", "urgent")
        order = [e["subagent_id"] for e in swarm.runQueueSnapshot()]
        assert order == ["q-c", "q-a", "q-b"]

    def test_status_projection_carries_queue_position(self, swarm):
        run = _run(swarm, "q-pos-1")
        swarm._registerRunQueue(run)
        assert swarm.status("q-pos-1")["queue_position"] == 1
        swarm.setRunQueuePriority("q-pos-1", "high")
        assert swarm.status("q-pos-1")["queue_position"] == 1
        swarm.cancelQueuedRun("q-pos-1")
        assert swarm.status("q-pos-1")["queue_position"] == 0, "离队后位次归 0"

    def test_status_projection_queue_position_absent_for_unqueued(self, swarm):
        _run(swarm, "q-pos-2", status=SUBAGENT_RUNNING)
        assert swarm.status("q-pos-2")["queue_position"] == 0


class TestTerminalQualityWiring:
    def test_completed_run_is_strong_and_flows_to_envelope(self, swarm):
        run = _run(swarm, "tq-1", status=SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_COMPLETED, cause="candidate_merged")
        assert run.terminal_quality == "strong"
        envelope = swarm._uplinkEnvelope(run)
        assert envelope["terminal_quality"] == "strong"

    def test_timeout_failed_run_is_weak(self, swarm):
        run = _run(swarm, "tq-2", status=SUBAGENT_RUNNING)
        run.cause = "subagent_timeout"
        transitionRun(run, SUBAGENT_FAILED, cause="subagent_timeout")
        assert run.terminal_quality == "weak"
        assert swarm._uplinkEnvelope(run)["terminal_quality"] == "weak"

    def test_status_projection_carries_quality(self, swarm):
        run = _run(swarm, "tq-3", status=SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_FAILED, cause="subagent_timeout")
        assert swarm.status("tq-3")["terminal_quality"] == "weak"


class TestRealPathWiring:
    """真 spawn→终态链路的接线覆盖（变异检验暴露的路径盲区补强）：

    - spawn 与 spawned 事件同点同步入队；
    - _run_member 开跑（member_started）即出队；
    - _execute finally 终态出队 + 名下子结果投递单补扫。
    """

    @staticmethod
    def _mock_agent():
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent.config.name = "子Agent"
        return agent

    @pytest.mark.asyncio
    async def test_full_lifecycle_queue_and_catchup(self, swarm):
        import asyncio as aio
        from unittest.mock import patch

        from neurova.agent.delegated_delivery import getDeliveryLedger
        from neurova.agent.mailbox import get_agent_mailbox

        started = aio.Event()
        release = aio.Event()

        agent = self._mock_agent()

        async def _chat(*_args, **_kwargs):
            started.set()
            await release.wait()
            return {"text": "任务完成报告"}

        agent.chat = _chat
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="全链路任务", agent_id="researcher",
                                       background=True, session_id="sess-full")
        sid = result["subagent_id"]
        assert any(e["subagent_id"] == sid for e in swarm.runQueueSnapshot()), \
            "spawn 与 spawned 事件同点同步入队"
        # 子结果投递单先落账（目标父 run = 本 run），父终态收口时应被补扫
        ticket = getDeliveryLedger().record(
            "child-full", sid, "子Agent终态", {"report": "子结果"}, "mid-full")
        await aio.wait_for(started.wait(), timeout=5)
        assert swarm.status(sid)["status"] == "running"
        assert all(e["subagent_id"] != sid for e in swarm.runQueueSnapshot()), \
            "member_started 开跑即出队"
        release.set()
        await swarm._tasks[sid]
        assert all(e["subagent_id"] != sid for e in swarm.runQueueSnapshot()), \
            "终态出队（_execute finally）"
        assert getDeliveryLedger().get(ticket["ticket_id"])["redelivered"] is True, \
            "终态补扫应补投名下子结果投递单"
        assert get_agent_mailbox().pending("sess-full") >= 1, "补投件真入箱"
