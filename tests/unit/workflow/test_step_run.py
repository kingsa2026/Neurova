"""P1-1 单节点 step-run（TDD — Dify 对标 §4 P1-1）。

契约（后端 DebugSession/断点/variables/mock 均已在位，本件补单节点
试跑入口——Dify「单节点运行」画布 UX 的底座）：
1. 引擎层 executor.step_run(workflow, node_id, upstream_outputs,
   user_id)：只跑指定节点——上下文注入上游输出（mock/真实混合调试），
   返回 {status, output, duration_ms, error?}
2. 不支持的节点类型（无执行器/未知类型）→ 明确错误信封
3. API 层 POST /workflows/{id}/step-run：body {node_id, inputs?,
   upstream_outputs?}；工作流 404；节点不存在 404
"""

import pytest


class TestEngineStepRun:
    @pytest.fixture
    def wf(self):
        import time as _time

        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )

        return WorkflowDefinition(
            id="wf_step", name="t", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0},
                             config={"fields": []}),
                WorkflowNode(id="llm", type="builtin:llm", position={"x": 100, "y": 0},
                             config={"prompt": "hi"}, mock_output={"text": "mock 答案"}),
                WorkflowNode(id="e", type="builtin:end", position={"x": 200, "y": 0}, config={}),
            ],
            edges=[
                WorkflowEdge(id="e1", source="s", target="llm"),
                WorkflowEdge(id="e2", source="llm", target="e"),
            ],
            variables=[], tags=[], category="g", author="t",
            created_at=_time.time(), updated_at=_time.time(),
            status=WorkflowStatus.DRAFT,
        )

    @pytest.mark.asyncio
    async def test_step_run_mock_node(self, wf):
        """单节点试跑：mock_output 优先（与全量 run 的 mock 语义一致）"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor

        out = await WorkflowExecutor().step_run(wf, "llm", {})
        assert out["status"] == "success"
        assert out["output"] == {"text": "mock 答案"}
        assert out["duration_ms"] >= 0

    @pytest.mark.asyncio
    async def test_step_run_unknown_node(self, wf):
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor

        out = await WorkflowExecutor().step_run(wf, "ghost_node", {})
        assert out["status"] == "failed"
        assert "ghost_node" in (out.get("error") or "")

    @pytest.mark.asyncio
    async def test_step_run_unknown_type(self, wf):
        """无执行器的节点类型 → 明确错误信封（不静默 output=None）"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor
        from neurova.collaboration.neurflow.models import WorkflowNode

        wf.nodes.append(WorkflowNode(id="weird", type="builtin:no_such_type",
                                     position={"x": 0, "y": 0}, config={}))
        out = await WorkflowExecutor().step_run(wf, "weird", {})
        assert out["status"] == "failed"
        assert "no_such_type" in (out.get("error") or "")

    @pytest.mark.asyncio
    async def test_step_run_injects_upstream_outputs(self, wf):
        """上游输出注入上下文（画布变量检查面板的数据基础）"""
        from neurova.collaboration.neurflow.execution_engine import WorkflowExecutor

        out = await WorkflowExecutor().step_run(
            wf, "llm", {"s": {"output": {"greeting": "hello"}}}
        )
        assert out["status"] == "success"
        assert out.get("variables", {}).get("greeting") == "hello"


class TestStepRunEndpoint:
    @pytest.fixture
    def client(self, tmp_path, monkeypatch):
        import time as _time

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api import auth as _auth  # noqa: F401
        from neurova.api.endpoints import neurflow_api
        from neurova.collaboration.neurflow.models import (
            WorkflowDefinition, WorkflowNode, WorkflowEdge, WorkflowStatus,
        )
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        storage = NeurflowStorage(str(tmp_path / "nf.db"))
        wf = WorkflowDefinition(
            id="wf_ep", name="t", description="", version="1.0.0",
            nodes=[
                WorkflowNode(id="s", type="builtin:start", position={"x": 0, "y": 0},
                             config={"fields": []}, mock_output={"seed": 1}),
            ],
            edges=[],
            variables=[], tags=[], category="g", author="t",
            created_at=_time.time(), updated_at=_time.time(),
            status=WorkflowStatus.DRAFT,
        )
        storage.save_workflow(wf)
        monkeypatch.setattr(neurflow_api, "_get_storage", lambda: storage)

        app = FastAPI()
        app.include_router(neurflow_api.router, prefix="/api/v1/neurflow")
        app.dependency_overrides[neurflow_api.get_current_user_or_default] = lambda: {"user_id": "u1"}
        return TestClient(app)

    def test_endpoint_roundtrip(self, client):
        resp = client.post("/api/v1/neurflow/workflows/wf_ep/step-run",
                           json={"node_id": "s", "upstream_outputs": {}})
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["status"] == "success"
        assert data["output"] == {"seed": 1}

    def test_endpoint_unknown_node_404(self, client):
        resp = client.post("/api/v1/neurflow/workflows/wf_ep/step-run",
                           json={"node_id": "ghost", "upstream_outputs": {}})
        assert resp.status_code == 404

    def test_endpoint_unknown_workflow_404(self, client):
        resp = client.post("/api/v1/neurflow/workflows/ghost/step-run",
                           json={"node_id": "s", "upstream_outputs": {}})
        assert resp.status_code == 404
