# -*- coding: utf-8 -*-
"""B0 画布属主隔离（HTTP 端点契约，TDD 先红后绿）。

契约：
- P1-5 收口后 collaboration router 级挂严格登录门（匿名一律 401）；
  画布 CRUD/run/ops 的身份解析仍走 get_current_user_or_default
  （登录态下未带显式用户语境→default）
- 非属主 GET/PUT/DELETE/run/ops → 404（与不存在同构，防枚举）
- admin 全通；项目成员可读（GET/run），不可写
- 列表 view=personal|project|agent 过滤
- 创建带 project_id 需项目成员（admin 放行），否则 400
- 创建落 user_id=JWT 实名；origin 默认 manual 可透传
"""
import unittest
from pathlib import Path
from tempfile import mkdtemp
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import get_current_user_or_default
from neurova.collaboration.canvas_store import CanvasStore


def _snapshot(name="测试画布"):
    return {
        "name": name,
        "nodes": [{"id": "n1", "type": "builtin:start", "position": {"x": 0, "y": 0}, "config": {}}],
        "edges": [],
    }


class CanvasOwnershipApiBase(unittest.TestCase):
    def setUp(self):
        from neurova.api.endpoints import collaboration_api

        self.module = collaboration_api
        self.tmp = Path(mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.store = CanvasStore(self.tmp)

        self.app = FastAPI()
        self.app.include_router(collaboration_api.router, prefix="/api/v1/collaboration")
        self.client = TestClient(self.app)

        p1 = patch.object(collaboration_api, "_get_canvas_store", return_value=self.store)
        p1.start()
        self.addCleanup(p1.stop)
        # 默认：无项目成员关系
        p2 = patch.object(collaboration_api, "_requester_project_ids", return_value=set())
        p2.start()
        self.addCleanup(p2.stop)

    def login(self, user_id: str, role: str = "user"):
        identity = {
            "user_id": user_id,
            "username": user_id,
            "role": role,
            "neuser_id": user_id,
        }
        # P1-5 收口后 collaboration router 级是严格登录门——与 or_default 同步覆盖，
        # 否则路由级先 401、端点自身的身份解析根本轮不到。
        from neurova.api.auth import get_current_user as _strictGate

        self.app.dependency_overrides[_strictGate] = lambda: dict(identity)
        self.app.dependency_overrides[get_current_user_or_default] = lambda: dict(identity)
        self.addCleanup(self.app.dependency_overrides.clear)

    def create_as(self, user_id, payload=None, role="user"):
        self.login(user_id, role)
        resp = self.client.post("/api/v1/collaboration/canvas", json=payload or _snapshot())
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]["id"]


class TestOwnership(CanvasOwnershipApiBase):
    def test_create_stamps_owner_and_origin(self):
        self.login("alice")
        resp = self.client.post("/api/v1/collaboration/canvas", json=_snapshot())
        data = resp.json()["data"]
        self.assertEqual(data["user_id"], "alice")
        self.assertEqual(data.get("origin"), "manual")

    def test_anonymous_is_rejected_by_router_gate(self):
        """P1-5 收口后：匿名请求被 collaboration router 级登录门拒绝（401），
        不再"默认 default 用户"放行。"""
        resp = self.client.post("/api/v1/collaboration/canvas", json=_snapshot())
        self.assertEqual(resp.status_code, 401)

    def test_non_owner_get_returns_404(self):
        cid = self.create_as("alice")
        self.login("bob")
        self.assertEqual(self.client.get(f"/api/v1/collaboration/canvas/{cid}").status_code, 404)

    def test_owner_get_ok_and_admin_sees_all(self):
        cid = self.create_as("alice")
        self.login("root", "admin")
        self.assertEqual(self.client.get(f"/api/v1/collaboration/canvas/{cid}").status_code, 200)

    def test_non_owner_update_delete_run_404(self):
        cid = self.create_as("alice")
        self.login("bob")
        self.assertEqual(
            self.client.put(f"/api/v1/collaboration/canvas/{cid}", json=_snapshot("改")).status_code, 404
        )
        self.assertEqual(
            self.client.delete(f"/api/v1/collaboration/canvas/{cid}").status_code, 404
        )
        self.assertEqual(
            self.client.post(f"/api/v1/collaboration/canvas/{cid}/run", json={}).status_code, 404
        )
        self.assertEqual(
            self.client.post(
                f"/api/v1/collaboration/canvas/{cid}/ops", json={"op": "remove_node", "node_id": "n1"}
            ).status_code,
            404,
        )

    def test_owner_update_preserves_ownership(self):
        cid = self.create_as("alice")
        self.login("alice")
        resp = self.client.put(
            f"/api/v1/collaboration/canvas/{cid}", json={**_snapshot("改名"), "user_id": "mallory"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["user_id"], "alice")
        self.assertEqual(resp.json()["data"]["name"], "改名")

    def test_project_member_reads_but_cannot_write(self):
        cid = self.create_as("alice")
        self.store.update(cid, {**_snapshot(), "project_id": "p1"})
        with patch.object(self.module, "_requester_project_ids", return_value={"p1"}):
            self.login("bob")
            self.assertEqual(self.client.get(f"/api/v1/collaboration/canvas/{cid}").status_code, 200)
            self.assertEqual(
                self.client.put(f"/api/v1/collaboration/canvas/{cid}", json=_snapshot("劫持")).status_code,
                404,
            )

    def test_list_only_own_and_member_canvases(self):
        self.create_as("alice")
        self.create_as("bob")
        self.login("alice")
        items = self.client.get("/api/v1/collaboration/canvas").json()["data"]
        self.assertEqual({i["user_id"] for i in items}, {"alice"})

    def test_list_view_filters(self):
        self.login("alice")
        with patch.object(self.module, "_is_project_member", return_value=True):
            self.client.post("/api/v1/collaboration/canvas", json=_snapshot("个人"))
            self.client.post("/api/v1/collaboration/canvas", json={**_snapshot("项目"), "project_id": "p1"})
            self.client.post("/api/v1/collaboration/canvas", json={**_snapshot("agent"), "agent_id": "a1"})
        names = lambda **params: {
            i["name"] for i in self.client.get("/api/v1/collaboration/canvas", params=params).json()["data"]
        }
        self.assertEqual(names(view="personal"), {"个人"})
        self.assertEqual(names(view="project", project_id="p1"), {"项目"})
        self.assertEqual(names(view="agent", agent_id="a1"), {"agent"})

    def test_create_in_foreign_project_denied(self):
        self.login("bob")
        resp = self.client.post(
            "/api/v1/collaboration/canvas", json={**_snapshot(), "project_id": "p1"}
        )
        self.assertEqual(resp.status_code, 400)
        # 成员放行
        with patch.object(self.module, "_is_project_member", return_value=True):
            resp = self.client.post(
                "/api/v1/collaboration/canvas", json={**_snapshot(), "project_id": "p1"}
            )
            self.assertEqual(resp.status_code, 200)

    def test_create_project_allowed_for_default_and_admin(self):
        # P1-5 收口后无匿名面：桌面首启的 default 身份改走登录态（router 级登录门）。
        self.login("default")
        resp = self.client.post(
            "/api/v1/collaboration/canvas", json={**_snapshot(), "project_id": "p1"}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["user_id"], "default")
        self.login("root", "admin")
        resp = self.client.post(
            "/api/v1/collaboration/canvas", json={**_snapshot("admin"), "project_id": "p2"}
        )
        self.assertEqual(resp.status_code, 200)


if __name__ == "__main__":
    unittest.main()
