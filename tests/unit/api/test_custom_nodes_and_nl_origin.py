# -*- coding: utf-8 -*-
"""B4+B5 后端契约（TDD 先红后绿）。

B4 对话生成归位：
- POST /collaboration/canvas/from-nl 成功响应 data 携带 origin="nl_chat"
  与 agent_id（前端保存画布时透传归属列）。

B5 自定义节点类型 CRUD（CustomNodeService 暴露）：
- POST /neurflow/nodes/custom {spec} → 201 node；type 冲突 → 409；spec 非法 → 400
- GET /neurflow/nodes/custom → 列表（含 created_by）
- PUT /neurflow/nodes/custom/{type} → 仅 custom 且属主/admin；builtin → 400
- DELETE 同守卫；未知 type → 404
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user


@pytest.fixture()
def app_client(tmp_path):
    from neurova.api.endpoints import neurflow_api
    from neurova.collaboration.neurflow.custom_nodes import CustomNodeService
    from neurova.collaboration.neurflow.node_registry import NodeRegistry
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    storage = NeurflowStorage(db_path=str(tmp_path / "nodes.db"))
    registry = NodeRegistry()
    registry.ensure_builtin()  # builtin 在注册表但不在库——400 守卫分支的真实形态
    service = CustomNodeService(storage=storage, registry=registry)
    orig = neurflow_api._get_custom_node_service
    neurflow_api._get_custom_node_service = lambda: service

    app = FastAPI()
    app.include_router(neurflow_api.router)
    user = {"user_id": "alice", "role": "user"}
    app.dependency_overrides[get_current_user] = lambda: user
    yield TestClient(app), app, service, storage
    neurflow_api._get_custom_node_service = orig


def _login(app, uid, role="user"):
    u = {"user_id": uid, "role": role}
    app.dependency_overrides[get_current_user] = lambda: u


def _spec(type="greet", label="打招呼"):
    return {
        "type": type,
        "label": label,
        "tier": "declarative",
        "executor_body": {"template": "你好 {{name}}"},
        "form_schema": [{"id": "name", "label": "名字", "type": "text"}],
    }


class TestCustomNodeCRUD:
    def test_create_and_get(self, app_client):
        client, _, _, _ = app_client
        resp = client.post("/nodes/custom", json=_spec())
        assert resp.status_code == 201, resp.text
        node = resp.json()["node"]
        assert node["type"] == "custom:greet" and node["source"] == "custom"
        assert node["created_by"] == "alice"

        lst = client.get("/nodes/custom").json()["nodes"]
        assert [n["type"] for n in lst] == ["custom:greet"]

    def test_duplicate_type_409(self, app_client):
        client, *_ = app_client
        assert client.post("/nodes/custom", json=_spec()).status_code == 201
        assert client.post("/nodes/custom", json=_spec()).status_code == 409

    def test_invalid_spec_400(self, app_client):
        client, *_ = app_client
        assert client.post("/nodes/custom", json={"type": "x"}).status_code == 400

    def test_update_owner_only(self, app_client):
        client, app, _, _ = app_client
        client.post("/nodes/custom", json=_spec())
        _login(app, "bob")
        resp = client.put("/nodes/custom/custom:greet", json={"label": "bob改"})
        assert resp.status_code == 404  # 非属主与不存在同构
        _login(app, "alice")
        resp = client.put("/nodes/custom/custom:greet", json={"label": "alice改"})
        assert resp.status_code == 200
        assert resp.json()["node"]["label"] == "alice改"

    def test_builtin_guard(self, app_client):
        client, *_ = app_client
        # builtin 类型不许经此端点改删
        assert client.put("/nodes/custom/builtin:llm", json={"label": "x"}).status_code == 400
        assert client.delete("/nodes/custom/builtin:llm").status_code == 400

    def test_delete(self, app_client):
        client, *_ = app_client
        client.post("/nodes/custom", json=_spec())
        assert client.delete("/nodes/custom/custom:greet").status_code == 200
        assert client.delete("/nodes/custom/custom:greet").status_code == 404
        assert client.get("/nodes/custom").json()["nodes"] == []


class TestCanvasFromNlCarriesOrigin:
    def test_response_has_origin_and_agent(self):
        from unittest.mock import AsyncMock, patch

        from neurova.api.endpoints import collaboration_api

        app = FastAPI()
        app.include_router(collaboration_api.router, prefix="/api/v1/collaboration")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "alice", "role": "user"}
        client = TestClient(app)

        fake = {
            "status": "success",
            "data": {"nodes": [], "edges": [], "name": "n", "description": "d"},
        }
        with patch(
            "neurova.collaboration.neurflow.nl_designer.generate_canvas_from_nl",
            new_callable=AsyncMock, return_value=fake,
        ), patch(
            "neurova.api.endpoints.chat._user_can_access_agent", return_value=True
        ):
            resp = client.post(
                "/api/v1/collaboration/canvas/from-nl",
                json={"prompt": "做一个摘要流程", "agent_id": "a1"},
            )
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["origin"] == "nl_chat"
        assert data["agent_id"] == "a1"
