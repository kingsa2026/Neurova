# -*- coding: utf-8 -*-
"""K2 启动接线：swarm 事件账本收敛接启动。

钉住 neurova/agent/swarm.py::reconcileSwarmRunsAtStartup 的生产契约：
- 启动时对「台账仍 running 的 swarm run」（台账启动收敛翻牌留档行）与
  「内存仍活跃的 run」用事件账本末态校正内存 run 状态；
- 账本侧「cancelled」末态在蜂群域落 failed（与 cancelRun 同一口径，
  取消成因记进 cause）；
- 只做状态收敛，不做 run 复活续跑（内存无此 run 不凭账本重建）；
- 校正留痕：status_corrected 事件入 run 账本。
台账级收敛（agent_run_store.reconcile_at_startup）仍是事实源主收口，
本入口只做事件账本侧补强。
"""

import pytest

from neurova.agent.swarm import (
    SUBAGENT_FAILED,
    SUBAGENT_RUNNING,
    SubAgentRun,
    get_swarm_manager,
    reconcileSwarmRunsAtStartup,
    reset_swarm_manager,
    transitionRun,
)
from neurova.agent.swarm_event_log import appendRunEvent, readRunEvents


@pytest.fixture
def swarm():
    reset_swarm_manager()
    yield get_swarm_manager()
    reset_swarm_manager()


@pytest.fixture
def runStore(tmp_path, monkeypatch):
    """台账单例按用例隔离（NEUROVA_RUN_STORE_DB → 用例临时目录）。"""
    from neurova.core import agent_run_store as ars

    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "agent_runs.db"))
    ars.reset_agent_run_store()
    yield ars
    ars.reset_agent_run_store()


def _insertRunningRow(store, subagentId: str) -> None:
    """经台账自有连接插一行 running 子任务（伪造上一进程死亡时的遗留行）。

    列集与 AgentRunStore.intake 的 INSERT 同一集合，避免碰 schema 细节。
    """
    with store._conn:
        store._conn.execute(
            "INSERT INTO agent_runs (run_id, session_id, user_id, agent_id,"
            " subagent_id, parent_session_id, trace_id, project_id, team_id,"
            " message_digest, status, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,'running', strftime('%s','now'))",
            (f"run_{subagentId}", f"sess_{subagentId}", "", "default",
             subagentId, "", "", "", "", "t"),
        )


def _seedLedgerLeftover(runStore, subagentId: str) -> None:
    """先插 running 行、再重建台账单例——让 __init__ 的启动收敛翻牌并留档。"""
    store = runStore.get_agent_run_store()
    _insertRunningRow(store, subagentId)
    runStore.reset_agent_run_store()
    store2 = runStore.get_agent_run_store()
    assert [r["subagent_id"] for r in store2.startupReconcileRowsSnapshot()] == [subagentId]


class TestSwarmStartupReconcile:
    def test_stale_running_run_corrected_to_event_tail(self, swarm, runStore):
        """内存 run 卡 running + 事件账本末态 failed → 收敛后与末态一致。"""
        sid = "swarm_sr_tail_failed"
        run = SubAgentRun(subagent_id=sid, task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        swarm._runs[sid] = run
        appendRunEvent(sid, "status_changed",
                       {"from": "pending", "to": SUBAGENT_RUNNING, "cause": "t"})
        appendRunEvent(sid, "terminal",
                       {"status": SUBAGENT_FAILED, "cause": "execution_failed"})

        outcome = reconcileSwarmRunsAtStartup()

        assert run.status == SUBAGENT_FAILED, "run 状态应与账本末态一致"
        assert outcome["corrected"] == 1
        assert outcome["results"][0]["corrected"] is True

    def test_cancelled_tail_lands_failed(self, swarm, runStore):
        """账本末态 cancelled → 蜂群域落 failed（迁移表无 cancelled，按口径落 failed）。"""
        sid = "swarm_sr_tail_cancelled"
        run = SubAgentRun(subagent_id=sid, task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        swarm._runs[sid] = run
        appendRunEvent(sid, "terminal",
                       {"status": "cancelled", "cause": "subagent_cancelled"})

        reconcileSwarmRunsAtStartup()

        assert run.status == SUBAGENT_FAILED

    def test_ledger_running_row_is_candidate(self, swarm, runStore):
        """台账仍 running 的子任务行（启动收敛翻牌留档）进入校正候选。"""
        sid = "swarm_sr_ledger"
        _seedLedgerLeftover(runStore, sid)

        run = SubAgentRun(subagent_id=sid, task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        swarm._runs[sid] = run
        appendRunEvent(sid, "terminal",
                       {"status": SUBAGENT_FAILED, "cause": "execution_failed"})

        outcome = reconcileSwarmRunsAtStartup()

        assert run.status == SUBAGENT_FAILED
        assert outcome["corrected"] == 1

    def test_no_resurrection_for_run_not_in_memory(self, swarm, runStore):
        """只做状态收敛，不复活续跑：内存无此 run 时不得凭账本重建对象。"""
        sid = "swarm_sr_ghost"
        _seedLedgerLeftover(runStore, sid)
        appendRunEvent(sid, "terminal", {"status": "completed", "cause": ""})

        outcome = reconcileSwarmRunsAtStartup()

        assert sid not in swarm._runs, "不得凭账本复活 run"
        assert outcome["corrected"] == 0

    def test_consistent_run_is_noop(self, swarm, runStore):
        """内存态与账本末态一致 → 不校正、不留校正事件。"""
        sid = "swarm_sr_consistent"
        run = SubAgentRun(subagent_id=sid, task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        swarm._runs[sid] = run
        appendRunEvent(sid, "status_changed",
                       {"from": "pending", "to": SUBAGENT_RUNNING, "cause": "t"})

        outcome = reconcileSwarmRunsAtStartup()

        assert run.status == SUBAGENT_RUNNING
        assert outcome["corrected"] == 0

    def test_correction_leaves_audit_event(self, swarm, runStore):
        """校正留痕：status_corrected 事件入 run 账本（排查可下钻）。"""
        sid = "swarm_sr_audit"
        run = SubAgentRun(subagent_id=sid, task="t")
        transitionRun(run, SUBAGENT_RUNNING)
        swarm._runs[sid] = run
        appendRunEvent(sid, "terminal",
                       {"status": SUBAGENT_FAILED, "cause": "execution_failed"})

        reconcileSwarmRunsAtStartup()

        kinds = [e["type"] for e in readRunEvents(sid)]
        assert "status_corrected" in kinds
