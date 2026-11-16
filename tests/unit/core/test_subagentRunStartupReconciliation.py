# -*- coding: utf-8 -*-
"""P2-1 子任务 run 状态持久化——启动收敛对蜂群行的钉子。

事实源：`agent_run_store.reconcile_at_startup`（构造期自动跑）。蜂群子任务经
`openSubagentRun → intake/claim_next` 落同一张 `agent_runs` 表，进程崩溃后遗留的
running 行必须在重启时被诚实收敛为 failed(process_died)——不能留幽灵 running。

覆盖：
1. 崩溃遗留：子任务行 running → 重启（新实例构造）→ failed(process_died)；
2. 正常收尾：completed 行重启后保持 completed（收敛不误伤终态）；
3. subagent_id/parent_session_id 列在收敛后仍可溯源。
"""

from pathlib import Path

import pytest

from neurova.core.agent_run_store import AgentRunStore, OWNER_IDENTITY


@pytest.fixture()
def dbPath(tmp_path):
    return tmp_path / "runs.db"


def _seedRunningSubagent(store):
    runId = store.intake("member-1", "u1", "agentX", "子任务A",
                         subagent_id="swarm_abc123", parent_session_id="parent-1")
    claimed = store.claim_next("member-1")
    assert claimed == runId
    return runId


class TestSubagentRunReconciliation:
    def test_crashed_running_row_converged_on_restart(self, dbPath):
        store1 = AgentRunStore(dbPath, lease_seconds=90.0)
        runId = _seedRunningSubagent(store1)
        store1.close()

        # 模拟重启：同一库新实例，构造期触发 reconcile_at_startup
        store2 = AgentRunStore(dbPath, lease_seconds=90.0)
        try:
            row = store2.get(runId)
            assert row is not None
            assert row["status"] == "failed"
            assert row["error_type"] == "process_died"
            assert row["subagent_id"] == "swarm_abc123"
            assert row["parent_session_id"] == "parent-1"
        finally:
            store2.close()

    def test_completed_row_survives_restart(self, dbPath):
        store1 = AgentRunStore(dbPath, lease_seconds=90.0)
        runId = _seedRunningSubagent(store1)
        store1.finish(runId, OWNER_IDENTITY, "completed", "")
        store1.close()

        store2 = AgentRunStore(dbPath, lease_seconds=90.0)
        try:
            row = store2.get(runId)
            assert row["status"] == "completed"
            assert row["error_type"] in ("", None)
        finally:
            store2.close()
