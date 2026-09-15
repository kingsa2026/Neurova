# -*- coding: utf-8 -*-
"""B2 双向编辑接线（后端契约，TDD 先红后绿）。

契约：
- GET /collaboration/canvas/{id}?source=definition → 把 WorkflowDefinition
  经 definition_to_canvas 编译为画布快照返回（id=定义 id、metadata 保留
  workflow_id 溯源、version=当前版本号、viewport 携带）。属主/admin/项目成员
  可读，非属主 404 同构；public 定义他人可读。
- 不带 source 参数不回退定义（画布库语义不变，只提升不下降）。
- PUT /neurflow/workflows/{id}/definition 扩展：
  * 可选 name/description 字段（编辑器改名/描述回写）
  * base_version 乐观锁：过期 → 409（detail 含 current_version）
  * 局部更新语义保持：未提供 nodes/edges 时不动；variables/tags/status 永不被抹
"""
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.collaboration.canvas_store import CanvasStore
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
    WorkflowVariable,
)


def _wf(wid="wf_b2", owner="alice"):
    return WorkflowDefinition(
        id=wid, name="定义B2", description="d", version="1.0.0",
        nodes=[
            WorkflowNode(id="start", type="builtin:start",
                         position={"x": 11, "y": 22}, config={"message": "hi"}),
            WorkflowNode(id="end", type="builtin:end",
                         position={"x": 33, "y": 44}, config={"reply": ""}),
        ],
        edges=[WorkflowEdge(id="e1", source="start", target="end", source_handle="out")],
        variables=[WorkflowVariable(name="v1", type="string", default_value="keep")],
        tags=["keep-me"], category="test", author="alice",
        created_at=time.time(), updated_at=time.time(), status=WorkflowStatus.PUBLISHED,
        user_id=owner, metadata={"viewport": {"x": 5, "y": 6, "zoom": 0.8}},
    )


@pytest.fixture()
def env(tmp_path):
    from neurova.api.endpoints import collaboration_api, neurflow_api
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    storage = NeurflowStorage(db_path=str(tmp_path / "b2.db"))
    store = CanvasStore(tmp_path / "canvas")
    storage.save_workflow(_wf(), user_id="alice")

    app = FastAPI()
    app.include_router(collaboration_api.router, prefix="/api/v1/collaboration")
    app.include_router(neurflow_api.router, prefix="/api/v1/neurflow")
    user = {"user_id": "alice", "role": "user"}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_or_default] = lambda: user

    orig_collab_get = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    p = patch.object(collaboration_api, "_get_canvas_store", return_value=store)
    p.start()
    p2 = patch.object(collaboration_api, "_requester_project_ids", return_value=set())
    p2.start()
    yield app, storage, store
    p.stop()
    p2.stop()
    neurflow_api._get_storage = orig_collab_get


def login(app, uid, role="user"):
    u = {"user_id": uid, "role": role}
    app.dependency_overrides[get_current_user] = lambda: u
    app.dependency_overrides[get_current_user_or_default] = lambda: u


class TestDefinitionAsCanvasLoad:
    def test_load_definition_snapshot_shape(self, env):
        app, storage, _ = env
        client = TestClient(app)
        resp = client.get("/api/v1/collaboration/canvas/wf_b2?source=definition")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["id"] == "wf_b2"
        assert data["name"] == "定义B2"
        assert data["nodes"][0]["position"] == {"x": 11, "y": 22}
        assert data["edges"][0]["source"]["nodeId"] == "start"
        assert data["edges"][0]["source"]["portId"] == "out"
        assert data["metadata"]["workflow_id"] == "wf_b2"
        assert data["metadata"]["source"] == "workflow"
        assert data["viewport"] == {"x": 5, "y": 6, "zoom": 0.8}
        assert isinstance(data["version"], int)

    def test_non_owner_denied(self, env):
        app, _, _ = env
        login(app, "bob")
        client = TestClient(app)
        assert client.get("/api/v1/collaboration/canvas/wf_b2?source=definition").status_code == 404

    def test_public_readable_by_others(self, env):
        app, storage, _ = env
        wf = storage.get_workflow("wf_b2")
        wf.public = True
        storage.save_workflow(wf)
        login(app, "bob")
        client = TestClient(app)
        assert client.get("/api/v1/collaboration/canvas/wf_b2?source=definition").status_code == 200

    def test_no_source_param_does_not_consult_definitions(self, env):
        app, _, _ = env
        client = TestClient(app)
        # 画布库无此 id，且不带 source → 404（旧语义不回退）
        assert client.get("/api/v1/collaboration/canvas/wf_b2").status_code == 404


class TestDefinitionWriteback:
    def test_partial_update_preserves_variables_tags_status(self, env):
        app, storage, _ = env
        client = TestClient(app)
        new_nodes = [
            {"id": "start", "type": "builtin:start", "position": {"x": 1, "y": 2}, "config": {}},
            {"id": "end", "type": "builtin:end", "position": {"x": 3, "y": 4}, "config": {}},
        ]
        resp = client.put(
            "/api/v1/neurflow/workflows/wf_b2/definition",
            json={"nodes": new_nodes},
        )
        assert resp.status_code == 200, resp.text
        got = storage.get_workflow("wf_b2")
        assert got.nodes[0].position == {"x": 1, "y": 2}
        assert [v.name for v in got.variables] == ["v1"]
        assert "keep-me" in got.tags
        assert got.status == WorkflowStatus.PUBLISHED  # 编辑回写不下线

    def test_name_description_writeback(self, env):
        app, storage, _ = env
        client = TestClient(app)
        resp = client.put(
            "/api/v1/neurflow/workflows/wf_b2/definition",
            json={"name": "改名", "description": "新描述"},
        )
        assert resp.status_code == 200
        got = storage.get_workflow("wf_b2")
        assert got.name == "改名" and got.description == "新描述"

    def test_base_version_conflict_409(self, env):
        app, storage, _ = env
        client = TestClient(app)
        current = storage.get_workflow_version_number("wf_b2")
        resp = client.put(
            "/api/v1/neurflow/workflows/wf_b2/definition?base_version=%d" % (current + 5),
            json={"nodes": []},
        )
        assert resp.status_code == 409
        assert resp.json()["detail"]["current_version"] == current

    def test_base_version_match_ok_and_bumps(self, env):
        app, storage, _ = env
        client = TestClient(app)
        current = storage.get_workflow_version_number("wf_b2")
        nodes = [
            {"id": "s", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}},
            {"id": "e", "type": "builtin:end", "position": {"x": 1, "y": 1}, "config": {}},
        ]
        resp = client.put(
            "/api/v1/neurflow/workflows/wf_b2/definition?base_version=%d" % current,
            json={"nodes": nodes},
        )
        assert resp.status_code == 200
        assert storage.get_workflow_version_number("wf_b2") > current

    def test_snapshot_version_matches_load_for_lock(self, env):
        """加载快照携带的 version 可直接作为回写 base_version（前端闭环）。"""
        app, storage, _ = env
        client = TestClient(app)
        data = client.get(
            "/api/v1/collaboration/canvas/wf_b2?source=definition"
        ).json()["data"]
        resp = client.put(
            "/api/v1/neurflow/workflows/wf_b2/definition?base_version=%d" % data["version"],
            json={"name": "闭环改名"},
        )
        assert resp.status_code == 200

    def test_viewport_roundtrip(self, env):
        """视口：定义快照加载带出 → 回写更新（编辑位置后恢复）。"""
        app, storage, _ = env
        client = TestClient(app)
        cur = storage.get_workflow_version_number("wf_b2")
        resp = client.put(
            "/api/v1/neurflow/workflows/wf_b2/definition?base_version=%d" % cur,
            json={"viewport": {"x": 100, "y": 200, "zoom": 0.5}},
        )
        assert resp.status_code == 200
        snap = client.get("/api/v1/collaboration/canvas/wf_b2?source=definition").json()["data"]
        assert snap["viewport"] == {"x": 100.0, "y": 200.0, "zoom": 0.5}
