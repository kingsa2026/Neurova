"""
画布 Op 端点测试（TDD 红灯）— Phase 1

端点：
- POST /api/v1/collaboration/canvas/{id}/ops   单 op 应用（agent/前端共用写入口）
- PUT  /api/v1/collaboration/canvas/{id}?base_version=N  全量保存的乐观锁

语义：
- 未知画布 → 404；op 业务错误 → 400；版本冲突 → 409（含 current_version）
- 成功响应 data 含 version，事件广播到 body.session_id（此处用假 broadcaster 验证）
"""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.canvas_store import CanvasStore


def _snapshot(name="测试画布"):
    return {
        "name": name,
        "nodes": [
            {
                "id": "n1",
                "type": "builtin:start",
                "label": "开始",
                "icon": "▶️",
                "position": {"x": 10, "y": 20},
                "inputs": [],
                "outputs": [{"id": "output", "label": "输出"}],
                "config": {},
            }
        ],
        "edges": [],
    }


class TestCanvasOpsEndpoint(unittest.TestCase):
    def setUp(self):
        from neurova.api.endpoints import collaboration_api

        self.module = collaboration_api
        self.tmp = Path(self.enterContext(_tempdir()))
        self.store = CanvasStore(self.tmp)
        self.client = TestClient(FastAPI())
        self.client.app.include_router(
            collaboration_api.router, prefix="/api/v1/collaboration"
        )
        patcher = patch.object(
            collaboration_api, "_get_canvas_store", return_value=self.store
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        # op 端点使用的 service：真 store + 假 broadcaster
        self.broadcasts = []

        async def fake_broadcast(session_id, payload):
            self.broadcasts.append((session_id, payload))

        from neurova.collaboration.canvas_ops import CanvasOpService

        self.service = CanvasOpService(store=self.store, broadcaster=fake_broadcast)
        svc_patcher = patch.object(
            collaboration_api, "_get_canvas_op_service", return_value=self.service
        )
        svc_patcher.start()
        self.addCleanup(svc_patcher.stop)

    def _create_canvas(self):
        resp = self.client.post("/api/v1/collaboration/canvas", json=_snapshot())
        assert resp.status_code == 200, resp.text
        return resp.json()["data"]

    def test_add_node_op(self):
        canvas = self._create_canvas()
        resp = self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={
                "op": "add_node",
                "node_type": "builtin:end",
                "session_id": "sess_api",
                "actor": "agent",
            },
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        data = resp.json()["data"]
        self.assertEqual(data["op"], "add_node")
        self.assertEqual(data["version"], 2)
        self.assertTrue(data["result"]["id"])
        # 事件广播
        self.assertEqual(len(self.broadcasts), 1)
        self.assertEqual(self.broadcasts[0][0], "sess_api")

    def test_connect_op(self):
        canvas = self._create_canvas()
        added = self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "add_node", "node_type": "builtin:end"},
        ).json()["data"]["result"]
        resp = self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "connect", "source_node": "n1", "target_node": added["id"]},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["data"]["op"], "connect")

    def test_unknown_op_400(self):
        canvas = self._create_canvas()
        resp = self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "fly_to_moon"},
        )
        self.assertEqual(resp.status_code, 400)

    def test_unknown_canvas_404(self):
        resp = self.client.post(
            "/api/v1/collaboration/canvas/ghost/ops",
            json={"op": "add_node", "node_type": "builtin:start"},
        )
        self.assertEqual(resp.status_code, 404)

    def test_unknown_node_type_400(self):
        canvas = self._create_canvas()
        resp = self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "add_node", "node_type": "no_such"},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn("no_such", resp.json()["detail"])

    def test_version_conflict_409_with_current_version(self):
        canvas = self._create_canvas()  # v1
        # 先推进一步到 v2
        self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "add_node", "node_type": "builtin:end"},
        )
        resp = self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "add_node", "node_type": "builtin:end", "base_version": 1},
        )
        self.assertEqual(resp.status_code, 409)
        self.assertEqual(resp.json()["detail"]["current_version"], 2)

    def test_put_with_base_version_conflict_409(self):
        canvas = self._create_canvas()  # v1
        self.client.post(
            f"/api/v1/collaboration/canvas/{canvas['id']}/ops",
            json={"op": "add_node", "node_type": "builtin:end"},
        )  # v2
        resp = self.client.put(
            f"/api/v1/collaboration/canvas/{canvas['id']}?base_version=1",
            json=_snapshot("覆盖尝试"),
        )
        self.assertEqual(resp.status_code, 409)
        # 冲突不落盘
        got = self.client.get(f"/api/v1/collaboration/canvas/{canvas['id']}")
        self.assertEqual(got.json()["data"]["version"], 2)

    def test_put_with_matching_base_version_ok(self):
        canvas = self._create_canvas()  # v1
        resp = self.client.put(
            f"/api/v1/collaboration/canvas/{canvas['id']}?base_version=1",
            json=_snapshot("v2"),
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["data"]["version"], 2)

    def test_put_without_base_version_last_write_wins(self):
        """兼容现有前端：不带 base_version 的 PUT 直接覆盖（版本仍递增）"""
        canvas = self._create_canvas()
        resp = self.client.put(
            f"/api/v1/collaboration/canvas/{canvas['id']}", json=_snapshot("旧前端")
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["data"]["version"], 2)

    def test_get_returns_version(self):
        canvas = self._create_canvas()
        got = self.client.get(f"/api/v1/collaboration/canvas/{canvas['id']}")
        self.assertEqual(got.json()["data"]["version"], 1)


import contextlib  # noqa: E402
import tempfile  # noqa: E402


@contextlib.contextmanager
def _tempdir():
    d = tempfile.mkdtemp(prefix="canvas-ops-api-")
    try:
        yield d
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
