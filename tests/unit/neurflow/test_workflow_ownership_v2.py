# -*- coding: utf-8 -*-
"""B1 工作流归属模型 v2（TDD 先红后绿）——docs/04-plans/2026-09-14 设计定稿。

契约：
- WorkflowDefinition 补三列：project_id/agent_id 可空 + origin（默认 manual）
- storage：迁移补列幂等；get_workflow 项目成员可读（project_ids）；
  list/search 支持 view=personal|project|agent + project_id/agent_id 细化
- find_subflow_references：删除前反查 subflow 引用（防悬空）
- HTTP：GET /workflows?view=... 透传；POST 接受三列且 project_id 需成员；
  duplicate/instantiate 落 origin=template；delete 有引用 → 400
- 语义不破：既有 P0-1 属主隔离行为不回退（personal 视图不含项目/agent 行）
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from neurova.api.auth import get_current_user, get_current_user_or_default
from neurova.collaboration.neurflow.models import (
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowNode,
    WorkflowStatus,
)


def _wf(wid="wf_1", owner="ua", project_id=None, agent_id=None, origin="manual",
        public=False, nodes=None):
    return WorkflowDefinition(
        id=wid, name=f"流-{wid}", description="", version="1.0.0",
        nodes=nodes or [
            WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={}),
            WorkflowNode(id="end", type="builtin:end", position={"x": 1, "y": 0}, config={}),
        ],
        edges=[WorkflowEdge(id="e1", source="start", target="end")],
        variables=[], tags=[], category="test", author=owner,
        created_at=0, updated_at=0, status=WorkflowStatus.DRAFT,
        public=public, user_id=owner,
        project_id=project_id, agent_id=agent_id, origin=origin,
    )


@pytest.fixture()
def storage(tmp_path):
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    return NeurflowStorage(db_path=str(tmp_path / "own2.db"))


class TestModelColumns:
    def test_defaults(self):
        wf = _wf()
        assert wf.project_id is None and wf.agent_id is None and wf.origin == "manual"

    def test_to_from_dict_roundtrip(self):
        wf = _wf(project_id="p1", agent_id="a1", origin="nl_chat")
        back = WorkflowDefinition.from_dict(wf.to_dict())
        assert back.project_id == "p1" and back.agent_id == "a1" and back.origin == "nl_chat"

    def test_from_dict_without_new_keys_ok(self):
        d = _wf().to_dict()
        d.pop("project_id"); d.pop("agent_id"); d.pop("origin")
        back = WorkflowDefinition.from_dict(d)
        assert back.project_id is None and back.origin == "manual"


class TestStorageOwnership:
    def test_save_get_roundtrip_new_columns(self, storage):
        storage.save_workflow(_wf(project_id="p1", agent_id="a1", origin="nl_chat"), user_id="ua")
        got = storage.get_workflow("wf_1")
        assert got.project_id == "p1" and got.agent_id == "a1" and got.origin == "nl_chat"

    def test_project_member_can_read_non_owner(self, storage):
        storage.save_workflow(_wf(project_id="p1"), user_id="ua")
        assert storage.get_workflow("wf_1", requester_id="bob", project_ids={"p1"}) is not None
        assert storage.get_workflow("wf_1", requester_id="bob") is None

    def test_member_cannot_write(self, storage):
        storage.save_workflow(_wf(project_id="p1"), user_id="ua")
        assert storage.delete_workflow("wf_1", requester_id="bob", project_ids={"p1"}) is False

    def test_list_views(self, storage):
        storage.save_workflow(_wf("wf_personal", owner="ua"), user_id="ua")
        storage.save_workflow(_wf("wf_project", owner="ua", project_id="p1"), user_id="ua")
        storage.save_workflow(_wf("wf_agent", owner="ua", agent_id="a1"), user_id="ua")
        ids = lambda **kw: {w.id for w in storage.list_workflows(requester_id="ua", **kw)}
        assert ids(view="personal") == {"wf_personal"}
        assert ids(view="project") == {"wf_project"}
        assert ids(view="agent") == {"wf_agent"}
        assert ids(view="project", project_id="p1") == {"wf_project"}
        assert ids(view="project", project_id="other") == set()
        assert ids(view="agent", agent_id="a1") == {"wf_agent"}
        assert ids() == {"wf_personal", "wf_project", "wf_agent"}

    def test_list_project_view_includes_others_member_rows(self, storage):
        storage.save_workflow(_wf("wf_a", owner="alice", project_id="p1"), user_id="alice")
        storage.save_workflow(_wf("wf_b", owner="alice"), user_id="alice")
        rows = {w.id for w in storage.list_workflows(
            requester_id="bob", project_ids={"p1"}, view="project")}
        assert rows == {"wf_a"}

    def test_search_respects_project_visibility(self, storage):
        storage.save_workflow(_wf("wf_project", owner="ua", project_id="p1"), user_id="ua")
        assert [w.id for w in storage.search_workflows("流", requester_id="bob", project_ids={"p1"})] == ["wf_project"]
        assert storage.search_workflows("流", requester_id="bob") == []

    def test_legacy_db_migration_adds_columns(self, tmp_path):
        """旧 schema（无新列）文件可继续打开并懒迁移。"""
        import sqlite3

        db = str(tmp_path / "legacy.db")
        conn = sqlite3.connect(db)
        conn.executescript(
            """
            CREATE TABLE workflows (id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT,
                version TEXT, nodes_json TEXT, edges_json TEXT, variables_json TEXT,
                tags_json TEXT, category TEXT, author TEXT, created_at REAL, updated_at REAL,
                status TEXT, template INTEGER, public INTEGER, metadata_json TEXT, user_id TEXT);
            INSERT INTO workflows (id,name,version,nodes_json,edges_json,variables_json,tags_json,
                status,user_id) VALUES ('wf_old','旧流','1.0.0','[]','[]','[]','[]','draft','ua');
            """
        )
        conn.commit()
        conn.close()
        from neurova.collaboration.neurflow.storage import NeurflowStorage

        s = NeurflowStorage(db_path=db)
        got = s.get_workflow("wf_old")
        assert got.user_id == "ua" and got.project_id is None and got.origin == "manual"

    def test_find_subflow_references(self, storage):
        sub = WorkflowNode(id="sf", type="subflow", position={"x": 0, "y": 0},
                           config={"workflow_id": "wf_target"})
        storage.save_workflow(_wf("wf_holder", owner="ua", nodes=[sub]), user_id="ua")
        storage.save_workflow(_wf("wf_other", owner="ua"), user_id="ua")
        refs = storage.find_subflow_references("wf_target")
        assert "wf_holder" in refs
        assert storage.find_subflow_references("wf_other") == []


def _app_with_storage(storage, user_id="ua", role="user"):
    from neurova.api.endpoints import neurflow_api

    app = FastAPI()
    app.include_router(neurflow_api.router)
    user = {"user_id": user_id, "role": role}
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_current_user_or_default] = lambda: user
    orig = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    TestClient.app = app  # noqa: 仅记录
    return app, orig


class TestApiOwnership:
    @pytest.fixture()
    def env(self, storage):
        from neurova.api.endpoints import neurflow_api

        app, orig = _app_with_storage(storage)
        storage.save_workflow(_wf("wf_p", owner="alice", project_id="p1"), user_id="alice")
        storage.save_workflow(_wf("wf_priv", owner="alice"), user_id="alice")
        storage.save_workflow(_wf("wf_ag", owner="alice", agent_id="a1"), user_id="alice")
        client = TestClient(app)
        with patch.object(neurflow_api, "_requester_project_ids", return_value=set()):
            yield client, storage
        neurflow_api._get_storage = orig

    def _login(self, app, user_id, role="user"):
        user = {"user_id": user_id, "role": role}
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_current_user_or_default] = lambda: user

    def test_list_view_filters_http(self, env, storage):
        client, _ = env
        app = client.app
        self._login(app, "alice")
        names = lambda **params: {w["id"] for w in client.get("/workflows", params=params).json()["workflows"]}
        assert names(view="personal") == {"wf_priv"}
        assert names(view="project") == {"wf_p"}
        assert names(view="agent") == {"wf_ag"}

    def test_project_member_lists_others_project_workflow(self, env):
        from neurova.api.endpoints import neurflow_api

        client, _ = env
        app = client.app
        self._login(app, "bob")
        with patch.object(neurflow_api, "_requester_project_ids", return_value={"p1"}):
            ids = {w["id"] for w in client.get("/workflows", params={"view": "project"}).json()["workflows"]}
        assert ids == {"wf_p"}
        # 非成员不可见
        ids = {w["id"] for w in client.get("/workflows", params={"view": "project"}).json()["workflows"]}
        assert ids == set()

    def test_create_accepts_ownership_and_gates_project(self, env):
        client, storage = env
        app = client.app
        self._login(app, "alice")
        payload = _wf("wf_new").to_dict()
        payload["project_id"] = "p9"
        resp = client.post("/workflows", json=payload)
        assert resp.status_code == 400  # 非成员不得归属

        from neurova.api.endpoints import neurflow_api

        with patch.object(neurflow_api, "_is_project_member", return_value=True):
            resp = client.post("/workflows", json=payload)
        assert resp.status_code == 200
        got = storage.get_workflow("wf_new")
        assert got.project_id == "p9" and got.user_id == "alice" and got.origin == "manual"

    def test_delete_guarded_by_subflow_reference(self, env):
        sub = WorkflowNode(id="sf", type="subflow", position={"x": 0, "y": 0},
                           config={"workflow_id": "wf_p"})
        client, storage = env
        storage.save_workflow(_wf("wf_holder", owner="alice", nodes=[sub]), user_id="alice")
        app = client.app
        self._login(app, "alice")
        resp = client.delete("/workflows/wf_p")
        assert resp.status_code == 400

    def test_duplicate_sets_origin_template(self, env):
        client, storage = env
        app = client.app
        self._login(app, "alice")
        resp = client.post("/workflows/wf_priv/duplicate")
        assert resp.status_code == 200
        dup = resp.json()["workflow"]
        assert dup["id"] != "wf_priv"
        assert storage.get_workflow(dup["id"]).origin == "template"
