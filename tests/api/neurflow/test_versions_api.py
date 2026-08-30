"""
NeurFlow 遗留② — 版本 REST API 测试

契约：
- GET  /neurflow/workflows/{id}/versions           版本历史（倒序）
- POST /neurflow/workflows/{id}/versions/{v}/rollback  回滚
- 工作流不存在 → 404；版本不存在 → 404

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


def _make_workflow(workflow_id="wf_ver_api", label="v0"):
    return WorkflowDefinition(
        id=workflow_id,
        name=f"版本API {label}",
        description=f"desc-{label}",
        version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 10, "y": 0}, config={}),
        ],
        edges=[WorkflowEdge(id="e1", source="start", target="end")],
        variables=[], tags=[], category="test", author="t",
        created_at=0, updated_at=0, status=WorkflowStatus.DRAFT,
    )


@pytest.fixture
def client(tmp_path):
    from neurova.api.endpoints import neurflow_api

    storage = neurflow_api.NeurflowStorage(db_path=str(tmp_path / "ver_api.db"))
    orig = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    storage.save_workflow(_make_workflow(label="first"))
    wf2 = _make_workflow(label="second")
    storage.save_workflow(wf2)

    app = FastAPI()
    app.include_router(neurflow_api.router)
    yield TestClient(app), storage
    neurflow_api._get_storage = orig


class TestVersionsApi:
    def test_list_versions_desc(self, client):
        c, _ = client
        r = c.get("/workflows/wf_ver_api/versions")
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert [v["version"] for v in data] == [2, 1]

    def test_list_versions_unknown_workflow_404(self, client):
        c, _ = client
        r = c.get("/workflows/wf_none/versions")
        assert r.status_code == 404

    def test_rollback_restores_and_returns_current(self, client):
        c, storage = client
        r = c.post("/workflows/wf_ver_api/versions/1/rollback")
        assert r.status_code == 200
        data = r.json().get("data", r.json())
        assert data["workflow"]["name"] == "版本API first"
        assert storage.get_workflow("wf_ver_api").name == "版本API first"

    def test_rollback_unknown_version_404(self, client):
        c, _ = client
        r = c.post("/workflows/wf_ver_api/versions/99/rollback")
        assert r.status_code == 404

    def test_rollback_unknown_workflow_404(self, client):
        c, _ = client
        r = c.post("/workflows/wf_none/versions/1/rollback")
        assert r.status_code == 404