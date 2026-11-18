"""睡眠归纳/碰撞周期端点测试（T2/T3 前端适配批）

GET /api/v1/sleep/{agent_id}/inductions 返回归纳相位的如实计数记录
（最新在前）；门控关闭的周期不入账（无相位运行不假装跑过）。
"""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import create_access_token
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation


def _authHeaders() -> dict:
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": "tester", "username": "tester", "role": "user"})}


class SimpleNamespaceStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class SleepInductionsEndpointTest(unittest.TestCase):
    def setUp(self):
        from neurova.api.endpoints import sleep as sleep_api

        app = FastAPI()
        app.include_router(sleep_api.router, prefix="/api/v1/sleep")
        self.client = TestClient(app)
        self.sleep_api = sleep_api
        self.sc = SleepConsolidation(memory_manager=None, storage=None)
        self.agent = SimpleNamespaceStub(sleep_consolidation=self.sc)

    def test_inductions_empty_without_cycles(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get("/api/v1/sleep/default/inductions", headers=_authHeaders())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_inductions_returns_recorded_cycles_newest_first(self):
        self.sc._induction_logs = [
            {"timestamp": 200.0, "enabled": True, "candidates": 4, "clusters": 2,
             "schemas": 1, "collisions": 1, "core_schemas": 1, "failed": 0,
             "identity_tagged": 2, "intentions": 1},
            {"timestamp": 100.0, "enabled": True, "candidates": 3, "clusters": 1,
             "schemas": 0, "collisions": 0, "core_schemas": 0, "failed": 1,
             "identity_tagged": 0, "intentions": 0},
        ]
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get("/api/v1/sleep/default/inductions", headers=_authHeaders())
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["timestamp"], 200.0)  # 最新在前
        for key in ("candidates", "clusters", "schemas", "collisions",
                    "core_schemas", "failed", "identity_tagged", "intentions"):
            self.assertIn(key, items[0], f"/inductions 响应缺少计数键: {key}")

    def test_inductions_limit_and_offset(self):
        self.sc._induction_logs = [
            {"timestamp": float(t), "enabled": True, "candidates": t, "clusters": 0,
             "schemas": 0, "collisions": 0, "core_schemas": 0, "failed": 0,
             "identity_tagged": 0, "intentions": 0}
            for t in (300.0, 200.0, 100.0)
        ]
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get(
                "/api/v1/sleep/default/inductions",
                params={"limit": 1, "offset": 1}, headers=_authHeaders())
        self.assertEqual(resp.status_code, 200)
        items = resp.json()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["timestamp"], 200.0)

    def test_gate_off_cycle_records_nothing(self):
        """门控关闭时 run_induction_cycle 直通：不记日志（没跑过不假装跑过）。"""
        self.sc.run_induction_cycle()
        self.assertEqual(self.sc.get_induction_logs(), [])


if __name__ == "__main__":
    unittest.main()
