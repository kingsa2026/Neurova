"""睡眠冲突解决端点测试

遗留问题修复:
1. GET /conflicts 的 response_model (ConflictResolutionItem) 与前端
   MergeConflict 形状 (id/field/local_value/remote_value/resolved/...)
   完全不匹配 —— 字段被 Pydantic 剥掉, 前端冲突列表永远空白。
2. 前端 resolveConflict 调 POST /conflicts/{id}/resolve —— 该路由不存在, 恒 404。
"""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import create_access_token
from neurova.cognitive_layers.memory_layer.sleep import MemoryRecord, SleepConsolidation

_TOKEN = create_access_token({"sub": "tester", "username": "tester", "role": "user"})
_AUTH = {"Authorization": f"Bearer {_TOKEN}"}


class SimpleNamespaceStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _seeded_consolidation() -> SleepConsolidation:
    sc = SleepConsolidation(memory_manager=None, storage=None)
    sc.merge_cluster(
        [
            MemoryRecord(id="m1", content="用户偏好咖啡"),
            MemoryRecord(id="m2", content="用户偏好咖啡和茶"),
        ]
    )
    return sc


class SleepConflictsEndpointTest(unittest.TestCase):
    def setUp(self):
        from neurova.api.endpoints import sleep as sleep_api

        app = FastAPI()
        app.include_router(sleep_api.router, prefix="/api/v1/sleep")
        self.client = TestClient(app)
        self.sleep_api = sleep_api
        self.sc = _seeded_consolidation()
        self.agent = SimpleNamespaceStub(sleep_consolidation=self.sc)

    def test_conflicts_return_frontend_shape(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get("/api/v1/sleep/default/conflicts", headers=_AUTH)
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertEqual(len(items), 1)
        rec = items[0]
        for key in ("id", "agent_id", "field", "local_value", "remote_value", "resolved", "resolution", "created_at"):
            self.assertIn(key, rec, f"/conflicts 响应缺少前端 MergeConflict 所需字段: {key}")
        self.assertEqual(rec["field"], "content")
        self.assertTrue(rec["resolved"])

    def test_resolve_endpoint_updates_record(self):
        conflict_id = self.sc.get_conflict_resolutions()[0]["id"]
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.post(
                f"/api/v1/sleep/default/conflicts/{conflict_id}/resolve",
                json={"resolution": "keep_newest"},
                headers=_AUTH,
            )
        self.assertEqual(resp.status_code, 200)
        rec = self.sc.get_conflict_resolutions()[0]
        self.assertEqual(rec["resolution"], "keep_newest")

    def test_resolve_endpoint_unknown_id_404(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.post(
                "/api/v1/sleep/default/conflicts/nonexistent/resolve",
                json={"resolution": "keep_newest"},
                headers=_AUTH,
            )
        self.assertEqual(resp.status_code, 404)


class SleepSettingsEndpointTest(unittest.TestCase):
    """阶段推进参数经 /settings 端点读写"""

    def setUp(self):
        from neurova.api.endpoints import sleep as sleep_api

        app = FastAPI()
        app.include_router(sleep_api.router, prefix="/api/v1/sleep")
        self.client = TestClient(app)
        self.sleep_api = sleep_api
        self.sc = SleepConsolidation(memory_manager=None, storage=None)
        self.agent = SimpleNamespaceStub(sleep_consolidation=self.sc)

    def test_get_settings_exposes_phase_progression_keys(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get("/api/v1/sleep/default/settings", headers=_AUTH)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        for key in (
            "sleep_mode",
            "temp_threshold_light_sleep",
            "idle_threshold_light_sleep",
            "monitor_interval_seconds",
        ):
            self.assertIn(key, body)

    def test_put_settings_updates_manager(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.put(
                "/api/v1/sleep/default/settings",
                json={"sleep_mode": "time", "temp_threshold_light_sleep": 40.0},
                headers=_AUTH,
            )
        self.assertEqual(resp.status_code, 200)
        s = self.sc.get_settings()
        self.assertEqual(s["sleep_mode"], "time")
        self.assertEqual(s["temp_threshold_light_sleep"], 40.0)


if __name__ == "__main__":
    unittest.main()
