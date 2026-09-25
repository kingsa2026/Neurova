# -*- coding: utf-8 -*-
"""B6-3 / B6-4：池的"按身份取池"单一入口（P2-1 与 P2-3 同一根因的两面）。

红灯依据（改前实证）：

- P2-1：`from neurova.context_pool import get_context_pool` 抛 `ImportError`
  ——**符号不存在**。neurflow 的 `exec_context` 因此恒走"未注入"分支；
  其解析函数还把 `ImportError` 吞成 `logger.debug`，故障在日志里都不显眼。
- P2-3：`/context/build` 每次请求 `ContextPool(user_id=..., agent_id=..., session_id=...)`
  新建实例，与 Agent 的池完全隔离——写入即丢；两次端点取到不同对象。

同一根因：仓库里没有"按 (user, agent, session) 身份取池"的单一入口，
于是消费方各造各的池（端点新建、neurflow 拿不到）。

契约（修复后）：

1. `neurova.context_pool.get_context_pool` **存在**，且按身份返回**同一个**池实例；
2. Agent 构造出的池被登记进身份索引（写入侧接线），端点与 neurflow 都能取到它；
3. 该身份下没有存活池时返回 `None`（不新造、不静默返回空壳）；
4. 端点两次请求取到同一池，第一次写入在第二次可见。
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def _clean_registry():
    from neurova.context_pool_registry import ContextPoolRegistry

    ContextPoolRegistry._instance = None
    yield
    ContextPoolRegistry._instance = None


class TestResolveEntryPointExists:
    def test_symbol_is_importable(self):
        """P2-1：符号必须存在——不存在时消费方只能靠 except 静默降级。"""
        from neurova.context_pool import get_context_pool

        assert callable(get_context_pool)

    def test_returns_none_when_no_live_pool(self):
        """身份下无存活池 → None（不新造空壳池糊过判据）。"""
        from neurova.context_pool import get_context_pool

        assert get_context_pool(user_id="u-none", agent_id="a-none", session_id="s-none") is None

    def test_returns_the_registered_pool_by_identity(self):
        """登记进身份索引的池必须按身份取回**同一实例**。"""
        from neurova.context_pool import ContextPool, get_context_pool
        from neurova.context_pool_registry import get_registry

        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1")
        get_registry().adopt(pool)
        fetched = get_context_pool(user_id="u1", agent_id="a1", session_id="s1")
        assert fetched is pool


class TestOrchestratorRegistersItsPool:
    def test_orchestrator_pool_is_discoverable_by_identity(self):
        """写入侧接线：Agent 的池必须能被按身份取回（否则 B6-4 无从收口）。"""
        from neurova.context.orchestrator import ContextOrchestrator
        from neurova.context_pool import get_context_pool

        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.name = "t"
        agent.config.agent_id = "a-reg"
        agent.config.llm_model = "test-model"
        agent.config.enable_auto_tagging = False
        agent.user_id = "u-reg"
        agent.agent_id = "a-reg"
        agent.memory_manager = MagicMock()
        agent.question_queue_manager = None

        orch = ContextOrchestrator(agent, use_pool=True)
        fetched = get_context_pool(user_id="u-reg", agent_id="a-reg", session_id=None)
        assert fetched is orch.context_pool


class TestBuildEndpointUsesIdentityPool:
    def _client(self, agent):
        from neurova.api.auth import get_current_user
        from neurova.api.endpoints import context as ctx_mod

        app = FastAPI()
        app.include_router(ctx_mod.router, prefix="/context")
        app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
        return ctx_mod, TestClient(app)

    def _agent_with_pool(self):
        from neurova.context_pool import ContextPool

        pool = ContextPool(user_id="u1", agent_id="a1", session_id=None)
        agent = MagicMock()
        agent.context_orchestrator = MagicMock()
        agent.context_orchestrator.context_pool = pool
        return agent, pool

    def test_two_requests_share_one_pool_and_second_sees_write(self):
        """P2-3：两次请求必须取到同一池，第一次写入在第二次可见。"""
        agent, pool = self._agent_with_pool()
        ctx_mod, client = self._client(agent)
        with patch.object(ctx_mod, "_get_agent", return_value=agent):
            first = client.post("/context/build", json={"agent_id": "a1", "user_input": "第一轮写入"})
            assert first.status_code == 200, first.text[:300]
            second = client.post("/context/build", json={"agent_id": "a1", "user_input": "第二轮"})
            assert second.status_code == 200, second.text[:300]

        contents = [c.content for c in pool.get_contexts()]
        assert "第一轮写入" in contents, (
            "端点写入没进 Agent 的池（池身份未收口，写入即丢）：" f"{contents}"
        )
