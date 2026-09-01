"""
遗留 B — 画布运行 DRAFT 陷阱测试

问题：canvas_to_workflow 产出的工作流恒 DRAFT（canvas_bridge.py:146），
而 subflow 默认 loader 只加载 PUBLISHED → 画布互相作子流必报
WORKFLOW_NOT_PUBLISHED。

契约：run 端点（collaboration_api.run_canvas_workflow）执行前把
**内存中的 workflow.status 置 PUBLISHED**（不落库——画布仍是草稿，
运行语义=用户在自己的画布上试跑）。
"""
import pytest


@pytest.fixture
def run_env(tmp_path, monkeypatch):
    from neurova.api.endpoints import collaboration_api
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    storage = NeurflowStorage(db_path=str(tmp_path / "draft_run.db"))
    monkeypatch.setattr(collaboration_api, "_get_canvas_store", lambda: _FakeStore(storage))
    return storage


class _FakeStore:
    """get_canvas_store 的最小替身：返回 {'nodes':[...], 'edges':[...]} 快照。"""

    def __init__(self, storage):
        self._storage = storage

    def get(self, canvas_id):
        if canvas_id == "cv_bad":
            return {
                "id": "cv_bad",
                "name": "bad-canvas",
                "nodes": [
                    {"id": "start", "type": "builtin:start", "label": "S",
                     "position": {"x": 0, "y": 0}, "config": {}},
                    {"id": "llm1", "type": "builtin:llm", "label": "LLM1",
                     "position": {"x": 50, "y": 0}, "config": {}},
                    {"id": "end", "type": "builtin:end", "label": "E",
                     "position": {"x": 10, "y": 0}, "config": {}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "llm1"},
                    {"id": "e2", "source": "llm1", "target": "end"},
                ],
            }
        if canvas_id != "cv_1":
            return None
        return {
            "id": "cv_1",
            "name": "draft-canvas",
            "nodes": [
                {"id": "start", "type": "builtin:start", "label": "S",
                 "position": {"x": 0, "y": 0}, "config": {}},
                {"id": "end", "type": "builtin:end", "label": "E",
                 "position": {"x": 10, "y": 0}, "config": {}},
            ],
            "edges": [{"id": "e1", "source": "start", "target": "end"}],
        }


class TestCanvasRunPublishesInMemory:
    def test_canvas_to_workflow_is_draft_by_default(self):
        """基线：canvas_bridge 产出 DRAFT（既有行为锚定）"""
        from neurova.collaboration.canvas_bridge import canvas_to_workflow
        from neurova.collaboration.neurflow.models import WorkflowStatus

        wf = canvas_to_workflow(
            {
                "name": "x",
                "nodes": [
                    {"id": "n1", "type": "builtin:start", "label": "S",
                     "position": {"x": 0, "y": 0}, "config": {}},
                ],
                "edges": [],
            },
            name="x",
        )
        assert wf.status == WorkflowStatus.DRAFT

    @pytest.mark.asyncio
    async def test_run_endpoint_sets_published_in_memory(self, run_env):
        """run 端点：execute 前 workflow.status 内存置 PUBLISHED（不落库）"""
        from neurova.api.endpoints import collaboration_api

        # 捕获 execute 收到的 workflow 状态
        captured = {}

        class _SpyExecutor:
            def create_instance(self, workflow, inputs, user_id=None):
                captured["status_at_create"] = workflow.status
                from neurova.collaboration.neurflow.models import (
                    ExecutionInstance,
                    WorkflowStatus,
                )

                return ExecutionInstance(
                    id="exec_draft_test",
                    workflow_id=workflow.id,
                    status=WorkflowStatus.RUNNING,
                    inputs={},
                )

            async def execute(self, workflow, **kwargs):
                captured["status_at_execute"] = workflow.status
                return kwargs.get("instance")

        import neurova.api.endpoints.collaboration_api as capi
        import neurova.collaboration.neurflow.execution_engine as ee

        # run_canvas_workflow 内部 `from ...execution_engine import get_workflow_executor`
        # 是局部 import——必须 patch 来源模块才拦得到
        orig_get = ee.get_workflow_executor
        ee.get_workflow_executor = lambda: _SpyExecutor()

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(capi.router)
        client = TestClient(app)
        try:
            r = client.post("/canvas/cv_1/run", json={})
        finally:
            ee.get_workflow_executor = orig_get

        assert r.status_code == 200
        assert r.json()["data"]["runId"] == "exec_draft_test"
        # 运行语义：execute 时状态为 PUBLISHED（内存），subflow 可引用
        from neurova.collaboration.neurflow.models import WorkflowStatus

        assert captured["status_at_execute"] == WorkflowStatus.PUBLISHED
        # 不落库：DB 中该 id 无工作流记录
        assert run_env.get_workflow("cv_1-draft-canvas") is None

    @pytest.mark.asyncio
    async def test_run_endpoint_rejects_bad_node_configs(self, run_env):
        """节点配置异常：400 + 字段级清单 + executor 不被调用（停止执行）"""
        from neurova.api.endpoints import collaboration_api
        import neurova.collaboration.neurflow.execution_engine as ee

        called = {"execute": 0}

        class _SpyExecutor:
            def create_instance(self, workflow, inputs, user_id=None):
                from neurova.collaboration.neurflow.models import ExecutionInstance, WorkflowStatus

                return ExecutionInstance(
                    id="exec_should_not_happen",
                    workflow_id=workflow.id,
                    status=WorkflowStatus.RUNNING,
                    inputs={},
                )

            async def execute(self, workflow, **kwargs):
                called["execute"] += 1
                return kwargs.get("instance")

        orig_get = ee.get_workflow_executor
        ee.get_workflow_executor = lambda: _SpyExecutor()

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        app = FastAPI()
        app.include_router(collaboration_api.router)
        client = TestClient(app)
        try:
            r = client.post("/canvas/cv_bad/run", json={})
        finally:
            ee.get_workflow_executor = orig_get

        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["code"] == 1
        assert "停止执行" in detail["message"]
        errors = detail["errors"]
        assert len(errors) == 1
        assert errors[0]["node_id"] == "llm1"
        assert "prompt" in errors[0]["missing"][0]
        assert called["execute"] == 0  # 后台任务未创建=停止执行
