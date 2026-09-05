# -*- coding: utf-8 -*-
"""P0-1 工作流鉴权与属主隔离（Langflow 对比 P0-1，TDD 先红后绿）。

契约：
- HTTP 面 14 个裸奔端点挂严格鉴权（get_current_user），匿名 → 401
- workflows 表补 user_id 列 + 存量回填 'default'（幂等）
- 属主语义（storage 层单点判定，deny→404 防 UUID 枚举）：
  * owner / admin → 全操作
  * 其他登录用户：public=1 可读可执行；private 读写全 404
- 存量迁移：无主行回填 user_id='default'
- deny 与不存在同构（响应体不泄露存在性）

系统内部入口（cron 派发 / webhook 匿名 HMAC / workflow_agent chat 桥）
走 storage.get_workflow(workflow_id) 不带 requester —— 不受限，属主
语义只约束 HTTP 面。
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


def _make_workflow(workflow_id="wf_own", owner="ua", public=False):
    nodes = [
        WorkflowNode(id="start", type="builtin:start", position={"x": 0, "y": 0}, config={"message": ""}),
        WorkflowNode(id="end", type="builtin:end", position={"x": 100, "y": 0}, config={"reply": ""}),
    ]
    return WorkflowDefinition(
        id=workflow_id,
        name=f"流-{workflow_id}",
        description="",
        version="1.0.0",
        nodes=nodes,
        edges=[WorkflowEdge(id="e1", source="start", target="end")],
        variables=[], tags=[], category="test", author=owner,
        created_at=0, updated_at=0, status=WorkflowStatus.DRAFT,
        public=public,
    )


@pytest.fixture()
def env(tmp_path):
    from neurova.api.endpoints import neurflow_api
    from neurova.collaboration.neurflow.storage import NeurflowStorage

    storage = NeurflowStorage(db_path=str(tmp_path / "own.db"))
    orig = neurflow_api._get_storage
    neurflow_api._get_storage = lambda: storage
    storage.save_workflow(_make_workflow("wf_a", owner="ua", public=False), user_id="ua")
    storage.save_workflow(_make_workflow("wf_pub", owner="ua", public=True), user_id="ua")

    app = FastAPI()
    app.include_router(neurflow_api.router)

    from neurova.api.auth import get_current_user

    overrides = {}

    def _set(user):
        if user is None:
            # 匿名：移除 override → 走真实 get_current_user → 401
            app.dependency_overrides.pop(get_current_user, None)
        else:
            app.dependency_overrides[get_current_user] = lambda: user

    yield {"client": TestClient(app), "storage": storage, "set_user": _set,
           "app": app, "auth_dep": get_current_user}
    neurflow_api._get_storage = orig
    app.dependency_overrides.clear()


def _as(env, user_id, role="user"):
    if user_id is None:
        env["set_user"](None)  # 匿名
    else:
        env["set_user"]({"user_id": user_id, "username": user_id,
                         "role": role, "neuser_id": user_id})


class TestAnonymousRejected:
    """匿名（无凭据）访问工作流面 → 401。"""

    def test_anonymous_list_401(self, env):
        _as(env, None)
        r = env["client"].get("/workflows")
        assert r.status_code == 401, r.text

    def test_anonymous_get_401(self, env):
        _as(env, None)
        assert env["client"].get("/workflows/wf_a").status_code == 401

    def test_anonymous_create_401(self, env):
        _as(env, None)
        r = env["client"].post("/workflows", json={"id": "wf_x", "name": "x"})
        assert r.status_code == 401

    def test_anonymous_search_401(self, env):
        _as(env, None)
        assert env["client"].get("/workflows/search/流").status_code == 401


class TestOwnership:
    """属主语义：B 访问 A 的私有流 → 404（与不存在同构）。"""

    def test_owner_full_chain(self, env):
        _as(env, "ua")
        c = env["client"]
        assert c.get("/workflows/wf_a").status_code == 200
        # PUT 是整定义替换（from_dict 必填 id/nodes）——拉现值改名回写
        current = c.get("/workflows/wf_a").json()["workflow"]
        current["name"] = "改名"
        assert c.put("/workflows/wf_a", json=current).status_code == 200
        current["name"] = "流-wf_a"
        c.put("/workflows/wf_a", json=current)
        assert c.get("/workflows/wf_a/definition").status_code == 200
        assert c.get("/workflows/wf_a/versions").status_code == 200

    def test_nonowner_private_read_404(self, env):
        _as(env, "ub")
        r = env["client"].get("/workflows/wf_a")
        assert r.status_code == 404
        # 与不存在同构（防枚举）
        r_missing = env["client"].get("/workflows/wf_missing")
        assert r_missing.status_code == 404
        assert r.json() == r_missing.json()

    def test_nonowner_write_delete_404(self, env):
        _as(env, "ub")
        c = env["client"]
        assert c.put("/workflows/wf_a", json={"name": "劫持"}).status_code == 404
        assert c.delete("/workflows/wf_a").status_code == 404
        assert c.post("/workflows/wf_a/duplicate").status_code == 404
        assert c.put("/workflows/wf_a/definition", json={"nodes": []}).status_code == 404
        assert c.put("/workflows/wf_a/viewport", json={"x": 1}).status_code == 404

    def test_nonowner_cannot_see_in_list(self, env):
        _as(env, "ub")
        r = env["client"].get("/workflows")
        ids = [w["id"] for w in r.json()["workflows"]]
        assert "wf_a" not in ids
        assert "wf_pub" in ids  # public 可见

    def test_admin_sees_all(self, env):
        _as(env, "root", role="admin")
        r = env["client"].get("/workflows")
        ids = [w["id"] for w in r.json()["workflows"]]
        assert "wf_a" in ids and "wf_pub" in ids
        # admin 可改删他人工作流（整定义替换：拉现值改名回写）
        current = env["client"].get("/workflows/wf_a").json()["workflow"]
        current["name"] = "管理员改"
        assert env["client"].put("/workflows/wf_a", json=current).status_code == 200

    def test_public_readable_not_writable(self, env):
        _as(env, "ub")
        c = env["client"]
        assert c.get("/workflows/wf_pub").status_code == 200
        assert c.put("/workflows/wf_pub", json={"name": "劫持"}).status_code == 404
        assert c.delete("/workflows/wf_pub").status_code == 404

    def test_delete_then_gone_for_owner(self, env):
        _as(env, "ua")
        c = env["client"]
        c.post("/workflows", json={"id": "wf_tmp", "name": "临时"})
        assert c.delete("/workflows/wf_tmp").status_code == 200
        assert c.get("/workflows/wf_tmp").status_code == 404


class TestCreateOwnership:
    """创建：属主=当前用户；不可伪造 user_id。"""

    def test_create_records_owner(self, env):
        _as(env, "uc")
        r = env["client"].post("/workflows", json={"id": "wf_c", "name": "C"})
        assert r.status_code == 200
        row = env["storage"]._conn.execute(
            "SELECT user_id FROM workflows WHERE id='wf_c'"
        ).fetchone()
        assert row["user_id"] == "uc"

    def test_owner_in_list(self, env):
        _as(env, "uc")
        env["client"].post("/workflows", json={"id": "wf_c2", "name": "C2"})
        r = env["client"].get("/workflows")
        ids = [w["id"] for w in r.json()["workflows"]]
        assert "wf_c2" in ids


class TestMigration:
    """存量迁移：无主行回填 user_id='default'（幂等）。"""

    def test_backfill_and_idempotent(self, env):
        storage = env["storage"]
        storage._conn.execute(
            "INSERT INTO workflows (id, name, created_at, updated_at) VALUES ('wf_old','旧',1,1)"
        )
        storage._conn.commit()
        storage._backfill_workflow_user_ids()
        row = storage._conn.execute(
            "SELECT user_id FROM workflows WHERE id='wf_old'"
        ).fetchone()
        assert row["user_id"] == "default"
        # 幂等：再跑一次不变
        storage._backfill_workflow_user_ids()
        row2 = storage._conn.execute(
            "SELECT user_id FROM workflows WHERE id='wf_old'"
        ).fetchone()
        assert row2["user_id"] == "default"

    def test_default_user_sees_backfilled(self, env):
        storage = env["storage"]
        storage._conn.execute(
            "INSERT INTO workflows (id, name, created_at, updated_at) VALUES ('wf_old2','旧2',1,1)"
        )
        storage._conn.commit()
        storage._backfill_workflow_user_ids()
        _as(env, "default")
        r = env["client"].get("/workflows")
        ids = [w["id"] for w in r.json()["workflows"]]
        assert "wf_old2" in ids


class TestSystemInternalPaths:
    """系统内部入口（cron/webhook/workflow_agent）不带 requester —— 不受限。"""

    def test_internal_get_workflow_no_requester(self, env):
        storage = env["storage"]
        # cron 派发/webhook 派发形态：无 requester
        assert storage.get_workflow("wf_a") is not None
        assert storage.get_workflow("wf_pub") is not None

    def test_get_workflow_requester_owner(self, env):
        assert env["storage"].get_workflow("wf_a", requester_id="ua") is not None

    def test_get_workflow_requester_nonowner_404_semantics(self, env):
        assert env["storage"].get_workflow("wf_a", requester_id="ub") is None

    def test_get_workflow_requester_public_readable(self, env):
        assert env["storage"].get_workflow("wf_pub", requester_id="ub") is not None

    def test_get_workflow_admin_sees_private(self, env):
        assert env["storage"].get_workflow("wf_a", requester_id="root", is_admin=True) is not None
