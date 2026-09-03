"""协作画布（Canvas）存储与端点测试。

补齐前端 CanvasDesignerPage 依赖的四个缺口端点：
- POST   /api/v1/collaboration/canvas           创建快照
- GET    /api/v1/collaboration/canvas/{id}      读取
- PUT    /api/v1/collaboration/canvas/{id}      更新
- POST   /api/v1/collaboration/canvas/{id}/run  受理运行（返回 runId）

存储为文件持久化（data/collaboration/canvas/*.json），重启不丢。
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.collaboration.canvas_store import (
    CanvasStore,
    get_canvas_store,
    reset_canvas_store,
)


def _snapshot(name="测试画布"):
    return {
        "name": name,
        "nodes": [
            {
                "id": "n1",
                "type": "builtin:start",
                "label": "检索节点",
                "icon": "search",
                "position": {"x": 10, "y": 20},
                "inputs": [{"id": "in1", "label": "query"}],
                "outputs": [{"id": "out1", "label": "docs"}],
                "config": {"top_k": 3},
            }
        ],
        "edges": [{"id": "e1", "x1": 1, "y1": 2, "x2": 3, "y2": 4}],
    }


class TestCanvasStore(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(_tempdir()))
        self.store = CanvasStore(self.tmp)

    def test_create_assigns_id_and_persists(self):
        snap = self.store.create(_snapshot())
        self.assertTrue(snap["id"])
        self.assertIn("created_at", snap)
        # 落盘验证：文件存在且内容可解析
        files = list((self.tmp / "canvases").glob("*.json"))
        self.assertEqual(len(files), 1)
        data = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(data["id"], snap["id"])

    def test_get_roundtrip(self):
        created = self.store.create(_snapshot())
        loaded = self.store.get(created["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["name"], "测试画布")
        self.assertEqual(loaded["nodes"][0]["id"], "n1")

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.store.get("ghost"))

    def test_project_id_persisted_and_listed(self):
        """画布可归属项目：project_id 持久化并在列表摘要中返回（B3 项目脚手架）"""
        snap = _snapshot()
        snap["project_id"] = "project_x1"
        created = self.store.create(snap)
        self.assertEqual(self.store.get(created["id"])["project_id"], "project_x1")

        summaries = self.store.list()
        match = next(s for s in summaries if s["id"] == created["id"])
        self.assertEqual(match["project_id"], "project_x1")

    def test_list_summary_without_project_id_ok(self):
        """旧画布无 project_id 时列表摘要兼容（键缺失即可，不报错）"""
        created = self.store.create(_snapshot())
        summaries = self.store.list()
        match = next(s for s in summaries if s["id"] == created["id"])
        self.assertIsNone(match.get("project_id"))

    def test_update_modifies_and_bumps_updated_at(self):
        created = self.store.create(_snapshot())
        payload = _snapshot("改名后的画布")
        updated = self.store.update(created["id"], payload)
        self.assertIsNotNone(updated)
        self.assertEqual(updated["name"], "改名后的画布")
        self.assertEqual(updated["id"], created["id"])
        self.assertGreaterEqual(updated["updated_at"], created["created_at"])
        # 更新已持久化
        reloaded = self.store.get(created["id"])
        self.assertEqual(reloaded["name"], "改名后的画布")

    def test_update_missing_returns_none(self):
        self.assertIsNone(self.store.update("ghost", _snapshot()))

    def test_delete_removes_file_and_returns_flag(self):
        created = self.store.create(_snapshot())
        self.assertTrue(self.store.delete(created["id"]))
        self.assertIsNone(self.store.get(created["id"]))
        self.assertFalse(self.store.delete(created["id"]))  # 重复删除返回 False
        self.assertFalse(self.store.delete("ghost"))

    def test_survives_store_recreation(self):
        """重启模拟：新建 store 实例仍能读到旧数据。"""
        created = self.store.create(_snapshot())
        again = CanvasStore(self.tmp)
        self.assertEqual(again.get(created["id"])["id"], created["id"])

    def test_list_returns_summaries_newest_first(self):
        first = self.store.create(_snapshot("画布A"))
        second = self.store.create(_snapshot("画布B"))
        # 触发 updated_at 前进
        import time as _time

        _time.sleep(0.01)
        self.store.update(first["id"], _snapshot("画布A改"))
        items = self.store.list()
        self.assertEqual(len(items), 2)
        self.assertEqual({i["id"] for i in items}, {first["id"], second["id"]})
        # 摘要字段：不含完整节点数据，但含统计
        item = next(i for i in items if i["id"] == first["id"])
        self.assertEqual(item["name"], "画布A改")
        self.assertEqual(item["node_count"], 1)
        self.assertIn("updated_at", item)
        self.assertNotIn("nodes", item)
        # 最近更新排最前
        self.assertEqual(items[0]["id"], first["id"])

    def test_list_empty_and_corrupt_skipped(self):
        self.assertEqual(self.store.list(), [])
        self.store.create(_snapshot())
        (self.tmp / "canvases" / "broken.json").write_text("{corrupt", encoding="utf-8")
        items = self.store.list()
        self.assertEqual(len(items), 1)

    def test_corrupt_file_skipped_not_crash(self):
        self.store.create(_snapshot())
        # 写入一个损坏文件
        (self.tmp / "canvases" / "broken.json").write_text("{corrupt", encoding="utf-8")
        again = CanvasStore(self.tmp)  # 加载时跳过损坏文件
        self.assertIsNone(again.get("broken"))


class TestCanvasSingleton(unittest.TestCase):
    def setUp(self):
        reset_canvas_store()

    def tearDown(self):
        reset_canvas_store()

    def test_singleton_identity_and_reset(self):
        first = get_canvas_store()
        self.assertIs(first, get_canvas_store())
        reset_canvas_store()
        self.assertIsNot(first, get_canvas_store())


# ── 端点 ────────────────────────────────────────────────────────


class CanvasEndpointBase(unittest.TestCase):
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

    def test_full_crud_and_run_flow(self):
        # 创建
        resp = self.client.post("/api/v1/collaboration/canvas", json=_snapshot())
        self.assertEqual(resp.status_code, 200, resp.text)
        body = resp.json()["data"]
        canvas_id = body["id"]
        self.assertEqual(body["name"], "测试画布")

        # 读取
        got = self.client.get(f"/api/v1/collaboration/canvas/{canvas_id}")
        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.json()["data"]["nodes"][0]["id"], "n1")

        # 更新
        upd = self.client.put(
            f"/api/v1/collaboration/canvas/{canvas_id}", json=_snapshot("v2")
        )
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(upd.json()["data"]["name"], "v2")

        # 运行：runId 即 neurflow 执行实例 id，可通过 runs 轮询端点查询
        run = self.client.post(f"/api/v1/collaboration/canvas/{canvas_id}/run")
        self.assertEqual(run.status_code, 200)
        run_id = run.json()["data"]["runId"]
        self.assertTrue(run_id)
        poll = self.client.get(
            f"/api/v1/collaboration/canvas/{canvas_id}/runs/{run_id}"
        )
        self.assertEqual(poll.status_code, 200, poll.text)
        self.assertIn(poll.json()["data"]["status"], {"running", "succeeded", "failed", "completed"})

    def test_get_missing_404(self):
        resp = self.client.get("/api/v1/collaboration/canvas/ghost")
        self.assertEqual(resp.status_code, 404)

    def test_list_canvases(self):
        """GET /canvas 返回画布摘要列表（前端"我的画布"入口）。"""
        empty = self.client.get("/api/v1/collaboration/canvas")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["data"], [])

        created = self.client.post(
            "/api/v1/collaboration/canvas", json=_snapshot("列表画布")
        ).json()["data"]
        items = self.client.get("/api/v1/collaboration/canvas").json()["data"]
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["id"], created["id"])
        self.assertEqual(items[0]["name"], "列表画布")
        self.assertNotIn("nodes", items[0])

    def test_put_missing_404(self):
        resp = self.client.put(
            "/api/v1/collaboration/canvas/ghost", json=_snapshot()
        )
        self.assertEqual(resp.status_code, 404)

    def test_run_missing_404(self):
        resp = self.client.post("/api/v1/collaboration/canvas/ghost/run")
        self.assertEqual(resp.status_code, 404)

    def test_run_unknown_node_type_400(self):
        """画布含未注册节点类型时明确 400，不静默假执行。"""
        created = self.client.post(
            "/api/v1/collaboration/canvas", json=_snapshot()
        ).json()["data"]
        bad = _snapshot("坏类型")
        bad["nodes"][0]["type"] = "no_such_type"
        bad_id = self.client.post(
            "/api/v1/collaboration/canvas", json=bad
        ).json()["data"]["id"]
        resp = self.client.post(f"/api/v1/collaboration/canvas/{bad_id}/run")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("no_such_type", resp.json()["detail"])
        assert created  # 创建路径本身成功

    def test_delete_canvas(self):
        created = self.client.post(
            "/api/v1/collaboration/canvas", json=_snapshot()
        ).json()["data"]
        resp = self.client.delete(f"/api/v1/collaboration/canvas/{created['id']}")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            self.client.get(f"/api/v1/collaboration/canvas/{created['id']}").status_code,
            404,
        )
        # 再次删除 → 404
        again = self.client.delete(f"/api/v1/collaboration/canvas/{created['id']}")
        self.assertEqual(again.status_code, 404)

    def test_comfyui_import_as_canvas(self):
        """ComfyUI 工作流导入直接落为画布（工作流=画布工作流）。"""
        comfy_json = {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
            "2": {"class_type": "VAEDecode", "inputs": {"samples": ["1", 0]}},
        }
        resp = self.client.post(
            "/api/v1/collaboration/comfyui/import-canvas",
            json={"name": "SDXL 文生图", "workflow": comfy_json},
        )
        self.assertEqual(resp.status_code, 200, resp.text)
        canvas = resp.json()["data"]
        self.assertEqual(canvas["name"], "SDXL 文生图")
        self.assertEqual(len(canvas["nodes"]), 2)
        self.assertEqual(canvas["nodes"][0]["type"], "comfyui:CheckpointLoaderSimple")
        # 连接被转换为逻辑边并落盘可读取
        self.assertEqual(len(canvas["edges"]), 1)
        self.assertEqual(canvas["edges"][0]["source"]["nodeId"], "1")
        got = self.client.get(f"/api/v1/collaboration/canvas/{canvas['id']}")
        self.assertEqual(got.status_code, 200)

    def test_comfyui_import_missing_class_type_400(self):
        resp = self.client.post(
            "/api/v1/collaboration/comfyui/import-canvas",
            json={"name": "坏", "workflow": {"1": {"inputs": {}}}},
        )
        self.assertEqual(resp.status_code, 400)


import contextlib  # noqa: E402
import tempfile  # noqa: E402


@contextlib.contextmanager
def _tempdir():
    d = tempfile.mkdtemp(prefix="canvas-test-")
    try:
        yield d
    finally:
        import shutil

        shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
