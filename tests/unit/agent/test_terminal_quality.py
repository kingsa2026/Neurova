# -*- coding: utf-8 -*-
"""A1 终态质量分级 单元测试。

覆盖：
- classifyTerminalQuality 各 (status, cause) 组合 → strong/weak/none 分级；
- transitionRun 迁移到终态时写入 run.terminal_quality；非终态迁移与同态重申不动该字段；
- requiresReviewConfirmation 三态判定（strong→False，weak/none→True）；
- SubAgentRun.to_dict() 带出 terminal_quality；
- 既有迁移行为不回归：校验、事件归档、fail-open 语义逐字保留。
"""

import pytest

from neurova.agent.swarm_support import (
    SUBAGENT_COMPLETED,
    SUBAGENT_FAILED,
    SUBAGENT_IN_REVIEW,
    SUBAGENT_PENDING,
    SUBAGENT_RUNNING,
    IllegalRunStatusTransition,
    SubAgentRun,
    TERMINAL_QUALITY_NONE,
    TERMINAL_QUALITY_STRONG,
    TERMINAL_QUALITY_WEAK,
    classifyTerminalQuality,
    requiresReviewConfirmation,
    transitionRun,
)
from neurova.agent.swarm_event_log import readRunEvents
from neurova.core.agent_run_ledger import (
    SUBAGENT_CAUSE_CANCELLED,
    SUBAGENT_CAUSE_FAILED,
    SUBAGENT_CAUSE_NONE,
    SUBAGENT_CAUSE_TIMEOUT,
)


class TestClassifyTerminalQuality:
    @pytest.mark.parametrize("cause", ["", SUBAGENT_CAUSE_NONE, "candidate_merged"])
    def test_completed_with_normal_cause_is_strong(self, cause):
        # candidate_merged 是 S4 候选合入的主链路完成仪式，属 provider 明确完成
        assert classifyTerminalQuality(SUBAGENT_COMPLETED, cause) == TERMINAL_QUALITY_STRONG

    @pytest.mark.parametrize("cause", [SUBAGENT_CAUSE_TIMEOUT, SUBAGENT_CAUSE_CANCELLED])
    def test_completed_with_timeout_or_cancelled_cause_is_weak(self, cause):
        assert classifyTerminalQuality(SUBAGENT_COMPLETED, cause) == TERMINAL_QUALITY_WEAK

    def test_completed_with_anomalous_cause_is_weak(self):
        # completed 却带失败类成因：完成得可疑，按弱可信处理
        assert classifyTerminalQuality(SUBAGENT_COMPLETED, SUBAGENT_CAUSE_FAILED) == TERMINAL_QUALITY_WEAK

    @pytest.mark.parametrize("cause", [
        SUBAGENT_CAUSE_TIMEOUT,
        SUBAGENT_CAUSE_CANCELLED,
        SUBAGENT_CAUSE_FAILED,
        "worker_crash",
    ])
    def test_failed_with_cause_is_weak(self, cause):
        assert classifyTerminalQuality(SUBAGENT_FAILED, cause) == TERMINAL_QUALITY_WEAK

    def test_failed_without_cause_is_none(self):
        assert classifyTerminalQuality(SUBAGENT_FAILED, "") == TERMINAL_QUALITY_NONE

    @pytest.mark.parametrize("status", [SUBAGENT_PENDING, SUBAGENT_RUNNING, SUBAGENT_IN_REVIEW])
    def test_non_terminal_status_is_none(self, status):
        assert classifyTerminalQuality(status, "") == TERMINAL_QUALITY_NONE
        assert classifyTerminalQuality(status, SUBAGENT_CAUSE_TIMEOUT) == TERMINAL_QUALITY_NONE

    def test_unknown_status_is_none(self):
        assert classifyTerminalQuality("flying", "") == TERMINAL_QUALITY_NONE


class TestTransitionRunWritesQuality:
    def test_completed_transition_writes_strong(self):
        run = SubAgentRun(subagent_id="swarm_tq_completed", task="t")
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        assert run.terminal_quality == "", "非终态迁移不得写 terminal_quality"
        transitionRun(run, SUBAGENT_COMPLETED, cause="")
        assert run.terminal_quality == TERMINAL_QUALITY_STRONG

    def test_failed_timeout_transition_writes_weak(self):
        run = SubAgentRun(subagent_id="swarm_tq_timeout", task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_TIMEOUT)
        assert run.terminal_quality == TERMINAL_QUALITY_WEAK

    def test_failed_without_cause_writes_none(self):
        run = SubAgentRun(subagent_id="swarm_tq_fail_nocause", task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_FAILED, cause="")
        assert run.terminal_quality == TERMINAL_QUALITY_NONE

    def test_pending_direct_fail_writes_quality(self):
        run = SubAgentRun(subagent_id="swarm_tq_pending_fail", task="t")
        transitionRun(run, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_CANCELLED)
        assert run.terminal_quality == TERMINAL_QUALITY_WEAK

    def test_same_status_reassert_keeps_quality_untouched(self):
        run = SubAgentRun(subagent_id="swarm_tq_idem", task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_COMPLETED, cause="")
        # 同态重申（即便换了 cause）不得重算/改写已落定的分级
        assert transitionRun(run, SUBAGENT_COMPLETED, cause=SUBAGENT_CAUSE_TIMEOUT) == SUBAGENT_COMPLETED
        assert run.terminal_quality == TERMINAL_QUALITY_STRONG

    def test_non_terminal_transition_keeps_field_empty(self):
        run = SubAgentRun(subagent_id="swarm_tq_running", task="t")
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        assert run.terminal_quality == ""
        transitionRun(run, SUBAGENT_IN_REVIEW, cause="review_phase")
        assert run.terminal_quality == ""


class TestRequiresReviewConfirmation:
    @staticmethod
    def _run_with_quality(quality: str) -> SubAgentRun:
        run = SubAgentRun(subagent_id=f"swarm_tq_review_{quality or 'empty'}", task="t")
        run.terminal_quality = quality
        return run

    def test_strong_does_not_require_review(self):
        assert requiresReviewConfirmation(self._run_with_quality(TERMINAL_QUALITY_STRONG)) is False

    def test_weak_requires_review(self):
        assert requiresReviewConfirmation(self._run_with_quality(TERMINAL_QUALITY_WEAK)) is True

    def test_none_requires_review(self):
        assert requiresReviewConfirmation(self._run_with_quality(TERMINAL_QUALITY_NONE)) is True


class TestToDictCarriesQuality:
    def test_to_dict_includes_terminal_quality(self):
        run = SubAgentRun(subagent_id="swarm_tq_dict", task="t")
        assert run.to_dict()["terminal_quality"] == ""
        transitionRun(run, SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_COMPLETED, cause="")
        assert run.to_dict()["terminal_quality"] == TERMINAL_QUALITY_STRONG


class TestExistingTransitionBehaviorIntact:
    """A1 只增不改：校验、事件归档、fail-open 语义逐字保留。"""

    def test_terminal_transition_still_archives_status_changed_events(self):
        run = SubAgentRun(subagent_id="swarm_tq_event", task="t")
        transitionRun(run, SUBAGENT_RUNNING, cause="member_started")
        transitionRun(run, SUBAGENT_FAILED, cause=SUBAGENT_CAUSE_CANCELLED)
        changed = [e for e in readRunEvents("swarm_tq_event") if e["type"] == "status_changed"]
        assert [(e["payload"]["from"], e["payload"]["to"]) for e in changed] == [
            (SUBAGENT_PENDING, SUBAGENT_RUNNING),
            (SUBAGENT_RUNNING, SUBAGENT_FAILED),
        ]
        assert changed[-1]["payload"]["cause"] == SUBAGENT_CAUSE_CANCELLED

    def test_illegal_transition_still_raises_and_keeps_quality(self):
        run = SubAgentRun(subagent_id="swarm_tq_illegal", task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        transitionRun(run, SUBAGENT_COMPLETED, cause="")
        with pytest.raises(IllegalRunStatusTransition):
            transitionRun(run, SUBAGENT_RUNNING, cause="retry")
        assert run.status == SUBAGENT_COMPLETED, "非法迁移不得改变状态"
        assert run.terminal_quality == TERMINAL_QUALITY_STRONG, "非法迁移不得改写分级"

    def test_unknown_status_still_raises(self):
        run = SubAgentRun(subagent_id="swarm_tq_unknown", task="t")
        with pytest.raises(IllegalRunStatusTransition):
            transitionRun(run, "flying")
        assert run.terminal_quality == ""
