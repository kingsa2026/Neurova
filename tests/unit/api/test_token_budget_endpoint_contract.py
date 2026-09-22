# -*- coding: utf-8 -*-
"""B6-2：`/context/token-budget` 必须读写**真实存在的**预算对象（P2-2）。

红灯依据（改前实证）：

- `GET /context/token-budget` 恒返回硬编码 `16000 / 0 / 16000`；
- `PUT /context/token-budget` 恒返回成功，而生效路径全仓不存在
  （`git grep "\.unified_injector =" -- neurova/` → 0 命中，
  `hasattr(agent, "unified_injector")` 恒假）→ **写了个寂寞**。

根因不是"少了个赋值"，而是端点挂在一个**从未装配的旁路对象**上：真正
决定 prompt 规模的预算是 `ContextOrchestrator` 的窗口预算
（`_resolve_window_token_budget`：显式覆盖 → 模型元数据）。

契约（修复后）：

1. GET 读数来自真实预算对象（与 `_resolve_window_token_budget` 同源），不是硬编码；
2. PUT 后 GET 反映新值（同一 Agent 实例）；
3. 预算对象取不到时**点名报错**，不得静默返回一个看着正常的数字。
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


def _client():
    from neurova.api.auth import get_current_user
    from neurova.api.endpoints import context as ctx_mod

    app = FastAPI()
    app.include_router(ctx_mod.router, prefix="/context")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    return ctx_mod, TestClient(app)


def _agentWithBudget(base: int = 20000):
    from neurova.context.orchestrator import ContextOrchestrator

    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-budget"
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.user_id = "u-budget"
    agent.agent_id = "a-budget"
    agent.memory_manager = MagicMock()
    agent.question_queue_manager = None

    orch = ContextOrchestrator(agent, use_pool=True)
    orch._window_token_budget = base
    agent.context_orchestrator = orch
    return agent, orch


class TestReadsRealBudget:
    def test_get_returns_effective_budget_not_hardcoded(self):
        """读数必须是真实预算对象的值（不是 16000 硬编码）。"""
        agent, orch = _agentWithBudget(24000)
        ctx_mod, client = _client()
        with patch.object(ctx_mod, "_get_agent", return_value=agent):
            resp = client.get("/context/token-budget", params={"agent_id": "a-budget"})
        assert resp.status_code == 200, resp.text[:300]
        data = resp.json()["data"]
        assert data["max_tokens"] == orch._resolve_window_token_budget() == 24000, (
            f"GET 读数 {data} 与真实预算对象不一致（仍是硬编码？）"
        )

    def test_get_reports_silence_when_budget_object_missing(self):
        """取不到预算对象时点名报错，不得静默回一个正常数字。"""
        agent = MagicMock()
        agent.context_orchestrator = None
        ctx_mod, client = _client()
        with patch.object(ctx_mod, "_get_agent", return_value=agent):
            resp = client.get("/context/token-budget", params={"agent_id": "a-none"})
        assert resp.status_code >= 400, (
            f"预算对象缺失却返回 {resp.status_code} —— 静默假读数：{resp.text[:200]}"
        )


class TestWriteThenRead:
    def test_put_then_get_reflects_new_value(self):
        """PUT 必须真的改变生效值（改前恒成功且零效果）。"""
        agent, orch = _agentWithBudget(20000)
        ctx_mod, client = _client()
        with patch.object(ctx_mod, "_get_agent", return_value=agent):
            put = client.put(
                "/context/token-budget",
                params={"agent_id": "a-budget", "max_tokens": 32000},
            )
            assert put.status_code == 200, put.text[:300]
            got = client.get("/context/token-budget", params={"agent_id": "a-budget"})
        assert got.json()["data"]["max_tokens"] == 32000, (
            f"PUT 后 GET 未反映新值（假闸口）：{got.json()}"
        )
        assert orch._resolve_window_token_budget() == 32000, (
            "写入没落到真实预算对象上——端点仍在写旁路属性"
        )

    def test_put_reports_silence_when_budget_object_missing(self):
        agent = MagicMock()
        agent.context_orchestrator = None
        ctx_mod, client = _client()
        with patch.object(ctx_mod, "_get_agent", return_value=agent):
            resp = client.put(
                "/context/token-budget",
                params={"agent_id": "a-none", "max_tokens": 32000},
            )
        assert resp.status_code >= 400, (
            f"预算对象缺失却谎报保存成功：{resp.status_code} {resp.text[:200]}"
        )


class TestBudgetBasics:
    def test_available_is_max_minus_used(self):
        agent, orch = _agentWithBudget(20000)
        budget = orch.get_token_budget()
        assert budget["available_tokens"] == budget["max_tokens"] - budget["used_tokens"]
        assert budget["max_tokens"] == 20000
