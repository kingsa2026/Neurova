"""GET /v1/context/composition 端点测试。

覆盖：
- 无实测记录 → 404（不伪造数据）
- composition.measure_composition 落快照后 → 200 全字段契约
- agent_id 查询参数隔离
- 鉴权：匿名请求被拒

约定：最小 FastAPI 应用只挂载 context 路由 + dependency_overrides mock
认证（与 test_context_pool_settings_api.py 同一约定，避免 create_app
lifespan 加载全量 Agent 挂起）。
"""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_p0_fixes_0123456789")

from neurova.api.endpoints import context as context_endpoint
from neurova.context.composition import measure_composition, reset_composition

MOCK_USER = {"user_id": "test_user", "username": "testuser", "role": "user"}


@pytest.fixture(autouse=True)
def _isolate_composition():
    reset_composition()
    yield
    reset_composition()


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(context_endpoint.router, prefix="/v1/context")

    from neurova.api.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: MOCK_USER

    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _measure_default():
    measure_composition(
        "default",
        [
            {"role": "system", "content": "系统提示" * 30},
            {"role": "user", "content": "你好"},
        ],
        [
            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "搜索",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            }
        ],
        context_window=128000,
    )


class TestCompositionEndpoint:
    def test_404_when_never_measured(self, client):
        resp = client.get("/v1/context/composition")
        assert resp.status_code == 404

    def test_200_after_measurement(self, client):
        _measure_default()
        resp = client.get("/v1/context/composition")
        assert resp.status_code == 200
        data = resp.json()
        # 契约字段（前端悬停面板消费面）
        assert data["agent_id"] == "default"
        assert data["total_tokens"] > 0
        assert data["context_window"] == 128000
        assert set(data["messages"]["buckets"].keys()) == {"system", "user", "assistant", "tool", "other"}
        assert data["tools"]["system"]["count"] == 1
        assert "cache_hit_rate" in data and "cache_source" in data

    def test_agent_scoped_query(self, client):
        measure_composition("agentK", [{"role": "user", "content": "只给K"}], None)
        resp = client.get("/v1/context/composition", params={"agent_id": "agentK"})
        assert resp.status_code == 200
        assert resp.json()["agent_id"] == "agentK"
        # 未实测的 agent 仍 404
        resp2 = client.get("/v1/context/composition", params={"agent_id": "other"})
        assert resp2.status_code == 404

    def test_requires_auth(self):
        from neurova.api.auth import get_current_user

        app = FastAPI()
        app.include_router(context_endpoint.router, prefix="/v1/context")
        with TestClient(app) as c:
            resp = c.get("/v1/context/composition")
            assert resp.status_code in (401, 403)
