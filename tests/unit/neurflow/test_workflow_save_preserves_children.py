"""P0-05：工作流更新必须保留触发器与执行审计（真实 SQLite 外键回归）。"""

import sqlite3
from dataclasses import replace

import pytest

from neurova.collaboration.neurflow.models import (
    ExecutionInstance,
    NodeExecutionResult,
    TriggerType,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
    WorkflowTrigger,
    WorkflowVariable,
)
from neurova.collaboration.neurflow.storage import NeurflowStorage


def _workflow() -> WorkflowDefinition:
    return WorkflowDefinition(
        id="wf_p0_05",
        name="原始工作流",
        description="原始描述",
        version="1.0.0",
        nodes=[WorkflowNode(id="start", type="builtin:start", position={"x": 0}, config={})],
        edges=[WorkflowEdge(id="edge", source="start", target="end")],
        variables=[WorkflowVariable(name="topic", type="string", default_value="old")],
        tags=["old"],
        category="old",
        author="old-author",
        created_at=100.0,
        updated_at=200.0,
        status=WorkflowStatus.DRAFT,
        template=False,
        public=False,
        metadata={"revision": 1},
        project_id="project-old",
        agent_id="agent-old",
        origin="manual",
    )


@pytest.fixture
def dbPath(tmp_path):
    return tmp_path / "p0_05.db"


def _rows(dbPath, table):
    with sqlite3.connect(dbPath) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


def _foreignKeyActions(dbPath, table):
    with sqlite3.connect(dbPath) as conn:
        return {
            row[3]: row[6]
            for row in conn.execute(f"PRAGMA foreign_key_list({table})")
            if row[2] == "workflows"
        }


def test_workflowUpdatePreservesTriggersAndExecutionAudit(dbPath):
    storage = NeurflowStorage(str(dbPath))
    try:
        assert storage._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert _foreignKeyActions(dbPath, "workflow_triggers") == {"workflow_id": "CASCADE"}
        assert _foreignKeyActions(dbPath, "executions") == {"workflow_id": "CASCADE"}

        assert storage.save_workflow(_workflow(), user_id="owner") is True
        assert storage.setSafeVersion("wf_p0_05", 1, "baseline", {"source": "test"}) is True
        for trigger in (
            WorkflowTrigger(
                id="trigger_webhook",
                workflow_id="wf_p0_05",
                type=TriggerType.WEBHOOK,
                config={"path": "/hook"},
                secret_hash=NeurflowStorage.hash_trigger_secret("secret"),
                secret_encrypted="encrypted-secret",
                rate_limit_per_minute=12,
            ),
            WorkflowTrigger(
                id="trigger_cron",
                workflow_id="wf_p0_05",
                type=TriggerType.CRON,
                config={"cron": "0 9 * * *"},
            ),
        ):
            assert storage.save_trigger(trigger) is True
        assert storage.save_delivery("trigger_webhook", True, "execution_done", 200, 3.5) > 0

        execution = ExecutionInstance(
            id="execution_done",
            workflow_id="wf_p0_05",
            status=WorkflowStatus.COMPLETED,
            inputs={"topic": "old"},
            outputs={"answer": " audited output "},
            node_results={
                "start": NodeExecutionResult(
                    node_id="start", status="success", output={"ok": True}
                )
            },
            variables={"trace": "keep-me"},
            started_at=210.0,
            finished_at=220.0,
            duration=10.0,
            agent_id="execution-agent",
            user_id="execution-user",
            metadata={"audit": "immutable"},
        )
        assert storage.save_execution(execution) is True
        assert storage.save_execution(
            ExecutionInstance(
                id="execution_failed",
                workflow_id="wf_p0_05",
                status=WorkflowStatus.FAILED,
                inputs={},
                started_at=230.0,
                error="保留失败原因",
                metadata={"audit": "failure"},
            )
        ) is True

        beforeTriggers = _rows(dbPath, "workflow_triggers")
        beforeExecutions = _rows(dbPath, "executions")
        beforeDeliveries = _rows(dbPath, "webhook_deliveries")
        beforeSafeVersion = storage.getSafeVersion("wf_p0_05")
        assert len(beforeTriggers) == 2
        assert len(beforeExecutions) == 2

        updated = replace(
            _workflow(),
            name="更新工作流",
            description="更新描述",
            version="2.0.0",
            nodes=[WorkflowNode(id="new", type="builtin:noop", position={"x": 9}, config={"v": 2})],
            edges=[],
            variables=[WorkflowVariable(name="count", type="number", default_value=2)],
            tags=["new"],
            category="new",
            author="new-author",
            created_at=300.0,
            updated_at=400.0,
            status=WorkflowStatus.PUBLISHED,
            template=True,
            public=True,
            metadata={"revision": 2},
            project_id="project-new",
            agent_id="agent-new",
            origin="nl_chat",
        )
        assert storage.save_workflow(updated) is True
        assert storage.save_workflow(updated) is True  # 同 id 重复保存也不得删除子行
    finally:
        storage.close()

    reopened = NeurflowStorage(str(dbPath))
    try:
        saved = reopened.get_workflow("wf_p0_05")
        assert saved is not None
        assert {**saved.to_dict(), "user_id": saved.user_id} == {
            **updated.to_dict(), "user_id": "owner"
        }
        assert reopened.getSafeVersion("wf_p0_05") == beforeSafeVersion
        assert [v["version"] for v in reopened.list_workflow_versions("wf_p0_05")] == [2, 1]
        assert {
            "workflow_triggers": _rows(dbPath, "workflow_triggers"),
            "executions": _rows(dbPath, "executions"),
            "webhook_deliveries": _rows(dbPath, "webhook_deliveries"),
        } == {
            "workflow_triggers": beforeTriggers,
            "executions": beforeExecutions,
            "webhook_deliveries": beforeDeliveries,
        }
        assert reopened.get_execution("execution_done").metadata == {"audit": "immutable"}
        assert reopened.get_execution("execution_failed").error == "保留失败原因"
        with sqlite3.connect(dbPath) as conn:
            assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        reopened.close()


def test_explicitWorkflowDeleteStillCascades(dbPath):
    storage = NeurflowStorage(str(dbPath))
    try:
        storage.save_workflow(_workflow())
        storage.save_trigger(
            WorkflowTrigger(id="trigger", workflow_id="wf_p0_05", type=TriggerType.MANUAL)
        )
        storage.save_execution(
            ExecutionInstance(
                id="execution", workflow_id="wf_p0_05", status=WorkflowStatus.RUNNING, inputs={}
            )
        )
        assert storage.delete_workflow("wf_p0_05") is True
    finally:
        storage.close()

    assert _rows(dbPath, "workflow_triggers") == []
    assert _rows(dbPath, "executions") == []
    assert _foreignKeyActions(dbPath, "workflow_triggers") == {"workflow_id": "CASCADE"}
    assert _foreignKeyActions(dbPath, "executions") == {"workflow_id": "CASCADE"}
