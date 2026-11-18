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


class TestContextCompressionSettingsFace:
    """S6/S15 压缩纪律参数读面：设置页压缩参数展示的数据源。

    参数一律从 context_pool / swarm 的具名常量直读（单一事实源），
    冷却运行态从会话时间线重建（与管线同一事实源，不另记账）。
    """

    def test_compressionSettingsFromNamedConstants(self, client):
        from neurova.agent.swarm import SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS
        from neurova.context_pool import (
            COMPACTION_FAILURE_COOLDOWN_STEPS,
            CONTEXT_COMPACT_TRIGGER_RATIO,
        )

        resp = client.get("/v1/context/stats")
        assert resp.status_code == 200
        compression = resp.json()["compression"]
        assert compression["triggerRatio"] == CONTEXT_COMPACT_TRIGGER_RATIO
        assert compression["softTargetTokens"] == SUBAGENT_CONTEXT_SOFT_TARGET_TOKENS
        assert compression["cooldownSteps"] == [int(s) for s in COMPACTION_FAILURE_COOLDOWN_STEPS]

    def test_cooldownOmittedWithoutSessionQuery(self, client):
        resp = client.get("/v1/context/stats")
        assert resp.status_code == 200
        assert resp.json()["cooldown"] is None

    def test_cooldownStateRebuiltFromTimeline(self, client):
        from neurova.context_pool import persistCompactionCooldownEvent
        from neurova.session_manager import get_session_manager

        persistCompactionCooldownEvent(
            get_session_manager(), "a1", "s-cool",
            consecutiveFailures=2, cooldownSeconds=15, reason="threshold",
        )
        resp = client.get(
            "/v1/context/stats", params={"agent_id": "a1", "session_id": "s-cool"}
        )
        assert resp.status_code == 200
        cooldown = resp.json()["cooldown"]
        assert cooldown["cooling"] is True, "刚落冷却事件的会话必须处于冷却中"
        assert cooldown["consecutiveFailures"] == 2
        assert cooldown["remainingSeconds"] > 0

    def test_cooldownClearedAfterCompressionSuccess(self, client):
        from neurova.context_pool import (
            CompressionEvent,
            persistCompactionCooldownEvent,
            persistCompressionEvent,
        )
        from neurova.session_manager import get_session_manager

        sm = get_session_manager()
        persistCompactionCooldownEvent(
            sm, "a1", "s-reset",
            consecutiveFailures=1, cooldownSeconds=30, reason="threshold",
        )
        persistCompressionEvent(
            sm, "a1", "s-reset",
            CompressionEvent(cutoffIndex=1, cutoffMessageId="m1", summaryFingerprint="f1",
                             tokensBefore=100, tokensAfter=50, foldedCount=1,
                             reason="threshold", summary=""),
        )
        resp = client.get(
            "/v1/context/stats", params={"agent_id": "a1", "session_id": "s-reset"}
        )
        assert resp.status_code == 200
        cooldown = resp.json()["cooldown"]
        assert cooldown["cooling"] is False, "压缩成功事件必须复位冷却"
        assert cooldown["consecutiveFailures"] == 0
