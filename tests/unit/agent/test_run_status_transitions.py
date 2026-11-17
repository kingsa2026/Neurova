# -*- coding: utf-8 -*-
"""S3 run 生命周期迁移表 + 状态事件归档 单元测试。

覆盖（方案 §S3）：
- RUN_STATUS_TRANSITIONS 迁移表：覆盖全部现役状态、终态无出边；
- transitionRun 唯一收口：合法迁移通过且每次落一条 status_changed 事件
  （复用 H-4 账本，因果链接 last_event_id）；非法迁移显式抛
  IllegalRunStatusTransition（不静默、不吞、不改状态）；
- 同态重复赋值幂等：不抛错、不重复落事件；
- 真链路：spawn→completed 的 status_changed 事件序列与迁移表一致；
- 启动收敛增强：进程重启后从事件账本重放 run 末态（replayRunTailStatus）
  与内存漂移校正（reconcileRunFromEvents）——账本是台账的补强，不替代。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from neurova.agent.swarm import (
    RUN_STATUS_TRANSITIONS,
    SUBAGENT_COMPLETED,
    SUBAGENT_FAILED,
    SUBAGENT_IN_REVIEW,
    SUBAGENT_PENDING,
    SUBAGENT_RUNNING,
    SUBAGENT_STATUSES,
    IllegalRunStatusTransition,
    SubAgentRun,
    get_swarm_manager,
    replayRunTailStatus,
    reset_swarm_manager,
    transitionRun,
)
from neurova.agent.swarm_event_log import appendRunEvent, readRunEvents


def make_agent(reply="任务完成报告"):
    agent = MagicMock()
    agent.config.name = "子Agent"
    agent.chat = AsyncMock(return_value={"text": reply})
    return agent


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


class TestTransitionTable:
    def test_table_covers_all_statuses(self):
        assert set(RUN_STATUS_TRANSITIONS) == set(SUBAGENT_STATUSES)

    def test_terminal_states_have_no_outgoing_edges(self):
        assert RUN_STATUS_TRANSITIONS[SUBAGENT_COMPLETED] == frozenset()
        assert RUN_STATUS_TRANSITIONS[SUBAGENT_FAILED] == frozenset()

    def test_pending_only_start_or_fail(self):
        assert RUN_STATUS_TRANSITIONS[SUBAGENT_PENDING] == frozenset(
            {SUBAGENT_RUNNING, SUBAGENT_FAILED}
        )

    def test_running_can_review_complete_or_fail(self):
        assert RUN_STATUS_TRANSITIONS[SUBAGENT_RUNNING] == frozenset(
            {SUBAGENT_IN_REVIEW, SUBAGENT_COMPLETED, SUBAGENT_FAILED}
        )

    def test_in_review_can_return_run_complete_or_fail(self):
        assert RUN_STATUS_TRANSITIONS[SUBAGENT_IN_REVIEW] == frozenset(
            {SUBAGENT_RUNNING, SUBAGENT_COMPLETED, SUBAGENT_FAILED}
        )


class TestTransitionRun:
    def test_legal_chain_running_in_review_completed_logs_events(self):
        run = SubAgentRun(subagent_id="swarm_tr_legal", task="t")
        assert transitionRun(run, SUBAGENT_RUNNING, cause="member_started") == SUBAGENT_RUNNING
        assert transitionRun(run, SUBAGENT_IN_REVIEW, cause="review_phase") == SUBAGENT_IN_REVIEW
        assert transitionRun(run, SUBAGENT_COMPLETED, cause="candidate_merged") == SUBAGENT_COMPLETED
        changed = [e for e in readRunEvents("swarm_tr_legal") if e["type"] == "status_changed"]
        assert [(e["payload"]["from"], e["payload"]["to"]) for e in changed] == [
            (SUBAGENT_PENDING, SUBAGENT_RUNNING),
            (SUBAGENT_RUNNING, SUBAGENT_IN_REVIEW),
            (SUBAGENT_IN_REVIEW, SUBAGENT_COMPLETED),
        ]
        assert changed[0]["payload"]["cause"] == "member_started"
        assert changed[2]["payload"]["cause"] == "candidate_merged"
        # 因果链：status_changed 串在 run 账本链上（后一事指向前一事）
        for prev, cur in zip(changed, changed[1:]):
            assert cur["causation_id"] == prev["event_id"]
        assert run.last_event_id == changed[-1]["event_id"]

    def test_illegal_transition_completed_to_running_raises(self):
        run = SubAgentRun(subagent_id="swarm_tr_illegal", task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_COMPLETED)
        with pytest.raises(IllegalRunStatusTransition):
            transitionRun(run, SUBAGENT_RUNNING, cause="retry")
        assert run.status == SUBAGENT_COMPLETED, "非法迁移不得改变状态"

    def test_illegal_transition_pending_to_completed_raises(self):
        run = SubAgentRun(subagent_id="swarm_tr_skip", task="t")
        with pytest.raises(IllegalRunStatusTransition):
            transitionRun(run, SUBAGENT_COMPLETED)
        assert run.status == SUBAGENT_PENDING

    def test_unknown_status_raises(self):
        run = SubAgentRun(subagent_id="swarm_tr_unknown", task="t")
        with pytest.raises(IllegalRunStatusTransition):
            transitionRun(run, "flying")

    def test_same_status_reassign_is_idempotent_without_event(self):
        run = SubAgentRun(subagent_id="swarm_tr_idem", task="t")
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        before = len([e for e in readRunEvents("swarm_tr_idem") if e["type"] == "status_changed"])
        assert transitionRun(run, SUBAGENT_RUNNING, cause="again") == SUBAGENT_RUNNING
        after = len([e for e in readRunEvents("swarm_tr_idem") if e["type"] == "status_changed"])
        assert after == before, "同态重申不落重复事件"

    @pytest.mark.parametrize("start", [SUBAGENT_PENDING, SUBAGENT_RUNNING, SUBAGENT_IN_REVIEW])
    def test_active_states_can_fail(self, start):
        sid = f"swarm_tr_fail_{start}"
        run = SubAgentRun(subagent_id=sid, task="t")
        if start != SUBAGENT_PENDING:
            transitionRun(run, SUBAGENT_RUNNING)
            if start == SUBAGENT_IN_REVIEW:
                transitionRun(run, SUBAGENT_IN_REVIEW)
        transitionRun(run, SUBAGENT_FAILED, cause="subagent_cancelled")
        assert run.status == SUBAGENT_FAILED


class TestSpawnStatusEvents:
    @pytest.mark.asyncio
    async def test_spawn_emits_status_changed_chain(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(task="子任务内容", agent_id="researcher")
        assert result["status"] == "completed"
        changed = [
            e for e in readRunEvents(result["subagent_id"]) if e["type"] == "status_changed"
        ]
        assert [(e["payload"]["from"], e["payload"]["to"]) for e in changed] == [
            (SUBAGENT_PENDING, SUBAGENT_RUNNING),
            (SUBAGENT_RUNNING, SUBAGENT_COMPLETED),
        ]

    @pytest.mark.asyncio
    async def test_failed_spawn_emits_status_changed_to_failed(self, swarm):
        agent = make_agent()
        agent.chat = AsyncMock(side_effect=RuntimeError("上游 503"))
        with patch("neurova.api.endpoints.get_agent_instance", return_value=agent):
            result = await swarm.spawn(task="会失败", agent_id="researcher")
        assert result["status"] == "failed"
        changed = [
            e for e in readRunEvents(result["subagent_id"]) if e["type"] == "status_changed"
        ]
        assert [(e["payload"]["from"], e["payload"]["to"]) for e in changed] == [
            (SUBAGENT_PENDING, SUBAGENT_RUNNING),
            (SUBAGENT_RUNNING, SUBAGENT_FAILED),
        ]


class TestEventLogReplay:
    """启动收敛增强：进程重启后内存 run 表为空，从账本重放末态做一致性校正。"""

    @pytest.mark.asyncio
    async def test_replay_tail_status_after_restart(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(task="子任务", agent_id="researcher")
        # 模拟重启：新建一个 SwarmManager（内存 run 表为空），从账本重放末态
        reset_swarm_manager()
        fresh = get_swarm_manager()
        assert "error" in fresh.status(result["subagent_id"])
        assert replayRunTailStatus(result["subagent_id"]) == SUBAGENT_COMPLETED

    def test_replay_unknown_run_returns_empty(self):
        assert replayRunTailStatus("swarm_never_existed") == ""

    def test_replay_prefers_latest_event(self):
        appendRunEvent("swarm_tr_replay", "status_changed",
                       {"from": SUBAGENT_PENDING, "to": SUBAGENT_RUNNING, "cause": "t"})
        appendRunEvent("swarm_tr_replay", "terminal", {"status": SUBAGENT_FAILED})
        assert replayRunTailStatus("swarm_tr_replay") == SUBAGENT_FAILED

    @pytest.mark.asyncio
    async def test_reconcile_corrects_drifted_memory_run(self, swarm):
        with patch("neurova.api.endpoints.get_agent_instance", return_value=make_agent()):
            result = await swarm.spawn(task="子任务", agent_id="researcher")
        sid = result["subagent_id"]
        # 人为制造内存漂移：内存态回拨成 running，账本末态仍是 completed
        run = swarm._runs[sid]
        run.status = SUBAGENT_RUNNING
        outcome = swarm.reconcileRunFromEvents(sid)
        assert outcome["corrected"] is True
        assert outcome["from"] == SUBAGENT_RUNNING
        assert outcome["to"] == SUBAGENT_COMPLETED
        assert run.status == SUBAGENT_COMPLETED

    def test_reconcile_unknown_run_reports_not_in_memory(self, swarm):
        outcome = swarm.reconcileRunFromEvents("swarm_never_existed")
        assert outcome["corrected"] is False
        assert outcome["reason"] == "not_in_memory"

    def test_reconcile_consistent_run_reports_noop(self, swarm):
        run = SubAgentRun(subagent_id="swarm_tr_consistent", task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        swarm._runs[run.subagent_id] = run
        appendRunEvent(run.subagent_id, "status_changed",
                       {"from": SUBAGENT_PENDING, "to": SUBAGENT_RUNNING, "cause": "t"})
        outcome = swarm.reconcileRunFromEvents(run.subagent_id)
        assert outcome["corrected"] is False
        assert outcome["reason"] == "consistent"
