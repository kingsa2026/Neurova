"""
Checkpoint API 测试 — Probe/Retry（借鉴 langflow checkpoints）

契约：
- GET  /executions/{id}/checkpoint：存在→摘要（completed/failed/pending/
  variables/error）；不存在→404
- POST /executions/{id}/retry：从检查点续跑（跳已完成节点）——
  工作流必须存在 DB 中（画布内存型 400 说明）；成功后同一 execution_id
  状态 running 且完成节点保留；checkpoint 更新
TDD：先红后绿。tmp storage 隔离。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
    ExecutionInstance,
)


def _make_workflow(workflow_id="wf_ck"):
    return WorkflowDefinition(
        id=workflow_id,
        name="ck",
        description="",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="llm1", type="builtin:llm", position={"x": 50, "y": 0}, config={"prompt": "hi"}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={}),
        ],
        edges=[
            WorkflowEdge(id="e1", source="start", target="llm1"),
            WorkflowEdge(id="e2", source="llm1", target="end"),
        ],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.PUBLISHED,
    )


@pytest.fixture
def env(tmp_path):
    from neurova.api.endpoints import neurflow_api
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    storage = NeurflowStorage(db_path=str(tmp_path / "ck_api.db"))
    orig = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    storage.save_workflow(_make_workflow())

    # 预置检查点：start 已完成、llm1 失败
    inst = ExecutionInstance(
        id="exec_ck_api_1",
        workflow_id="wf_ck",
        status=WorkflowStatus.FAILED,
        inputs={},
        variables={"user_msg": "hi"},
        error="节点 llm1 失败",
    )
    from neurova.collaboration.neurflow.models import NodeExecutionResult

    inst.node_results["start"] = NodeExecutionResult(
        node_id="start", status="success", output={"ok": True},
        started_at=0, finished_at=1, duration=1,
    )
    inst.node_results["llm1"] = NodeExecutionResult(
        node_id="llm1", status="failed", output=None, error="boom",
        started_at=1, finished_at=2, duration=1,
    )
    storage.save_checkpoint(inst)

    app = FastAPI()
    app.include_router(neurflow_api.router)
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    yield TestClient(app), storage
    neurflow_api._get_storage = orig


class TestProbeApi:
    def test_checkpoint_summary(self, env):
        c, _ = env
        r = c.get("/executions/exec_ck_api_1/checkpoint")
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert data["completed"] == ["start"]
        assert data["failed"] == ["llm1"]
        assert data["pending"] == ["end"]
        assert data["variables"] == {"user_msg": "hi"}
        assert data["error"] == "节点 llm1 失败"

    def test_checkpoint_missing_404(self, env):
        c, _ = env
        assert c.get("/executions/nope/checkpoint").status_code == 404


class TestRetryApi:
    def test_retry_resumes_from_checkpoint(self, env):
        c, storage = env
        # 引擎内 Tracker 无法经 API 直察——用 storage 复查 checkpoint 状态翻转
        r = c.post("/executions/exec_ck_api_1/retry", json={})
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert data["status"] in ("running", "completed")
        # 续跑：start 输出保留（resume 跳已完成）
        ck = storage.get_checkpoint("exec_ck_api_1")
        assert ck.node_results["start"].output == {"ok": True}

    def test_retry_unknown_execution_404(self, env):
        c, _ = env
        assert c.post("/executions/nope/retry", json={}).status_code == 404