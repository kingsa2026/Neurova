# -*- coding: utf-8 -*-
"""A9a 红灯：agent_runs 租户列（§6.4）——迁移/写入/蜂群透传。

覆盖：v6 迁移补 tenant_id 列、intake 落租户、openSubagentRun 透传、
未传路径语义不变（空串）。
"""
import pytest

from neurova.core import agent_run_store as ars
from neurova.core.agent_run_ledger import openSubagentRun


@pytest.fixture
def store(tmp_path):
    store = ars.AgentRunStore(db_path=tmp_path / "runs.db")
    yield store
    store.close()


def test_v6MigrationAddsTenantColumn(store):
    columns = {row[1] for row in store._conn.execute("PRAGMA table_info(agent_runs)")}
    assert "tenant_id" in columns


def test_intakePersistsTenant(store):
    run_id = store.intake("sess-1", user_id="u1", agent_id="a1", message="任务",
                          subagent_id="sub-1", parent_session_id="p-1", tenant_id="t1")
    row = store._conn.execute("SELECT tenant_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    assert row["tenant_id"] == "t1"


def test_intakeWithoutTenantStaysEmpty(store):
    run_id = store.intake("sess-2", user_id="u1", agent_id="a1", message="任务")
    row = store._conn.execute("SELECT tenant_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    assert row["tenant_id"] == ""


def test_openSubagentRunPassesTenantThrough(store, monkeypatch):
    monkeypatch.setattr(ars, "get_agent_run_store", lambda: store)
    monkeypatch.setattr(ars, "run_gate_enabled", lambda: True)
    run_id = openSubagentRun(
        memberSessionId="sess-t1", subagentId="sub-9", parentSessionId="p-9",
        userId="u1", agentId="a1", task="任务", traceId="", projectId="", teamId="team-1",
        tenantId="t9",
    )
    assert run_id
    row = store._conn.execute("SELECT tenant_id FROM agent_runs WHERE run_id=?", (run_id,)).fetchone()
    assert row["tenant_id"] == "t9"
