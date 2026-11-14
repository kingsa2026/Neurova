# -*- coding: utf-8 -*-
"""P2-7：GET /v1/context/stats 真值判据——聚合 context pool 注册表的真实读数
（`ContextPool.get_retention_stats`），不再恒回全零 stub。

有池：pools/total_contexts 随真实池走；无池：pools=0——"当前确实没有池"的
真值，不是假零。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.context_pool import ContextInput, ContextPool, ContextSource
from neurova.context_pool_registry import get_registry


@pytest.fixture
def client():
    from neurova.api.endpoints import context as context_api

    get_registry().reset()
    application = FastAPI()
    application.include_router(context_api.router, prefix="/v1/context")
    application.dependency_overrides[context_api.get_current_user] = lambda: {
        "user_id": "u1", "username": "u", "role": "admin", "neuser_id": "ne1",
    }
    yield TestClient(application)
    get_registry().reset()


class TestContextStatsRealValues:
    def test_noPoolsIsHonestZero(self, client):
        resp = client.get("/v1/context/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pools"] == 0
        assert data["total_contexts"] == 0
        assert data["archived_total"] == 0

    def test_registeredPoolFeedsRealCounts(self, client):
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        pool.add_context(ContextInput(content="真实条目", source=ContextSource.USER_INPUT))
        get_registry().adopt(pool)
        resp = client.get("/v1/context/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pools"] == 1
        assert data["total_contexts"] >= 1, "常驻条目数必须来自池的真实读数"
        assert data["indexed_entries"] >= 1
