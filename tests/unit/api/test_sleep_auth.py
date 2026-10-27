"""sleep 路由鉴权测试（P2-B）

此前 /api/v1/sleep 全部路由无 JWT 鉴权（对比 chat/agent 端点均用
Depends(get_current_user)），任何人可读取睡眠数据、触发睡眠/唤醒。
前端（NeurUI/src/api/index.ts:49）对每个请求附带 Bearer token，严格鉴权安全。
"""

import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.auth import create_access_token
from neurova.cognitive_layers.memory_layer.sleep import SleepConsolidation

from tests.unit.core.test_idle_tracker_phase_loop import FakeMemoryManager, _sample_memories


def _build_client():
    from neurova.api.endpoints import sleep as sleep_api

    app = FastAPI()
    app.include_router(sleep_api.router, prefix="/api/v1/sleep")
    return TestClient(app), sleep_api


#: 凭证**每次取用时现签**：密钥属于"这一轮"，不属于"这个进程"。
#:
#: 原先这里把令牌烘在导入期（`_TOKEN = create_access_token(...)` 提到模块级）。同一条腿
#: （受保护子集是单进程、按清单顺序跑）里任何一个档换了密钥，这枚导入期令牌当场验不过
#: ——形态是 `401`，读起来像鉴权坏了，实际是测试自己在赌"谁先导入"。
#: 生产侧取用口 `auth.currentJwtSecretKey()` 运行时读环境变量，本档只保证令牌晚于它签发。
def _authHeaders() -> dict:
    return {"Authorization": "Bearer " + create_access_token(
        {"sub": "tester", "username": "tester", "role": "user"})}


class SleepAuthTest(unittest.TestCase):
    def setUp(self):
        self.client, self.sleep_api = _build_client()
        self.sc = SleepConsolidation(memory_manager=FakeMemoryManager(_sample_memories()))
        self.agent = SimpleNamespaceStub(sleep_consolidation=self.sc)

    def test_status_requires_auth(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get("/api/v1/sleep/default/status")
        self.assertEqual(resp.status_code, 401, "无 token 应返回 401")

    def test_sleep_start_requires_auth(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.post("/api/v1/sleep/default/sleep")
        self.assertEqual(resp.status_code, 401, "触发睡眠必须鉴权")
        self.assertFalse(self.sc.is_sleeping(), "未鉴权请求不得产生副作用")

    def test_status_with_valid_token(self):
        with patch.object(self.sleep_api, "_get_agent", return_value=self.agent):
            resp = self.client.get("/api/v1/sleep/default/status", headers=_authHeaders())
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["is_sleeping"])


class SimpleNamespaceStub:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


if __name__ == "__main__":
    unittest.main()
