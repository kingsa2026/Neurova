"""
NeurFlow P2 Step 3 — publish 端点重构测试（工作流→Agent 闭环）

契约：POST /neurflow/workflows/{id}/publish
- 成功：workflow 状态 PUBLISHED + 生成 AgentManifest + agents 表记录
  - 响应含 agent（agent_id=wf_agent_{wf_id}，source_type=workflow）
  - storage.get_agent 可查到，metadata.workflow_id 回填
- 幂等：二次 publish 更新同一 agent 记录（不重复创建）
- 编译失败（无 start 节点）→ 400，状态不落 PUBLISHED

TDD：先红后绿。tmp DB 隔离。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowNode,
    WorkflowEdge,
    WorkflowStatus,
)


def _make_workflow(workflow_id="wf_pub", with_start=True):
    nodes = []
    if with_start:
        nodes.append(WorkflowNode(
            id="start", type="builtin:start",
            position={"x": 0, "y": 0}, config={"message": ""},
        ))
    nodes.append(WorkflowNode(
        id="end", type="builtin:end", position={"x": 100, "y": 0}, config={"reply": ""},
    ))
    return WorkflowDefinition(
        id=workflow_id,
        name="发布测试",
        description="",
        version="1.0.0",
        nodes=nodes,
        edges=[WorkflowEdge(id="e1", source="start", target="end")] if with_start else [],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.DRAFT,
    )


@pytest.fixture
def env(tmp_path):
    from neurova.api.endpoints import neurflow_api

    storage = neurflow_api.NeurflowStorage(db_path=str(tmp_path / "pub.db"))
    orig = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    storage.save_workflow(_make_workflow())
    storage.save_workflow(_make_workflow("wf_nostart", with_start=False))

    app = FastAPI()
    app.include_router(neurflow_api.router)
    # 审计修复：publish 端点已挂严格鉴权——测试显式注入认证身份
    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "tuser", "username": "tuser", "role": "admin", "neuser_id": "tuser",
    }
    yield {"client": TestClient(app), "storage": storage}
    neurflow_api._get_storage = orig


class TestPublishCreatesAgent:
    def test_publish_returns_agent_manifest(self, env):
        r = env["client"].post("/workflows/wf_pub/publish")
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert data["workflow"]["status"] == "published"
        agent = data.get("agent")
        assert agent is not None
        assert agent["agent_id"] == "wf_agent_wf_pub"
        assert agent["metadata"]["source_type"] == "workflow"
        assert agent["metadata"]["workflow_id"] == "wf_pub"

    def test_publish_persists_agent_record(self, env):
        env["client"].post("/workflows/wf_pub/publish")
        info = env["storage"].get_agent("wf_agent_wf_pub")
        assert info is not None
        assert info.metadata.get("source_type") == "workflow"
        assert "workflow" in info.capabilities

    def test_publish_is_idempotent(self, env):
        env["client"].post("/workflows/wf_pub/publish")
        env["client"].post("/workflows/wf_pub/publish")
        # 仅一条记录（save_agent upsert 语义）
        from neurova.agent.workflow_agent import list_workflow_agents

        all_agents = env["storage"].list_agents()
        wf_agents = list_workflow_agents(all_agents)
        assert len([a for a in wf_agents if a.agent_id == "wf_agent_wf_pub"]) == 1

    def test_publish_without_start_rejected(self, env):
        r = env["client"].post("/workflows/wf_nostart/publish")
        assert r.status_code in (400, 422)
        # 状态不落 PUBLISHED
        wf = env["storage"].get_workflow("wf_nostart")
        assert wf.status != WorkflowStatus.PUBLISHED