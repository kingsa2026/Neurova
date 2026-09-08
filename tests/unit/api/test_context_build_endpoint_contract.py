# -*- coding: utf-8 -*-
"""2026-09-08 审计修复⑮：/context/build 与 /build/v2 降级分支签名漂移。

端点调 agent.build_context / unified_injector.build_context 时传了真实
签名不存在的参数（session_id/include_memories/include_constitution/
user_input-as-kwarg 等）→ TypeError 500。
修复=按真实签名调用；ContextPool 分支契约保持不变。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _make_client():
    from neurova.api.endpoints import context as ctx_mod
    from neurova.api.auth import get_current_user

    app = FastAPI()
    app.include_router(ctx_mod.router, prefix="/context")
    app.dependency_overrides[get_current_user] = lambda: {"user_id": "u1"}
    return ctx_mod, TestClient(app)


def _fake_agent():
    agent = MagicMock()

    async def real_build_context(user_input, **kwargs):
        # 真实签名（ContextOrchestrator.build_context）：只接受这些 kwargs
        allowed = {
            "tool_memory_result", "auto_execute_result", "tool_decision",
            "experience_items", "relevant_memories", "session_context",
            "crystallized_patterns", "voice_context",
        }
        for k in kwargs:
            assert k in allowed, f"端点传入真实签名不存在的参数: {k}"
        return [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": user_input},
        ]

    agent.build_context = real_build_context
    agent.unified_injector = None  # 强制走 agent.build_context 降级分支
    return agent


class TestBuildEndpointSignatures:
    @pytest.mark.asyncio
    async def test_build_v2_falls_back_without_typeerror(self):
        """ContextPool 不可用 → 降级 agent.build_context，不因签名漂移 500。"""
        ctx_mod, client = _make_client()
        with patch.object(ctx_mod, "_get_context_builder", return_value=None), patch.object(
            ctx_mod, "_get_agent", return_value=_fake_agent()
        ):
            resp = client.post(
                "/context/build/v2",
                json={"agent_id": "default", "user_input": "问题"},
            )
        assert resp.status_code == 200, f"/build/v2 降级分支 500: {resp.text[:200]}"

    @pytest.mark.asyncio
    async def test_build_v1_falls_back_without_typeerror(self):
        ctx_mod, client = _make_client()
        with patch.object(ctx_mod, "_get_context_builder", return_value=None), patch.object(
            ctx_mod, "_get_agent", return_value=_fake_agent()
        ):
            resp = client.post(
                "/context/build",
                json={"agent_id": "default", "user_input": "问题"},
            )
        assert resp.status_code == 200, f"/build 降级分支 500: {resp.text[:200]}"
        body = resp.json()
        assert "问题" in body.get("content", "")
