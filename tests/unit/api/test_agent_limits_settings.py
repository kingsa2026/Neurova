"""Agent 运行限制设置（token_budget / max_loop_rounds）— 契约测试（红绿灯 TDD）

锁定：
1. GET/PUT /api/v1/governance/agent-limits（admin）读写持久化设置；
2. 越界值被 FastAPI 校验拒绝（token_budget 1000..1e7，rounds 2..200）；
3. get_effective_limits 环境变量优先 + 夹紧；
4. openai_loop 门控从设置读取（非硬编码 20/100000）。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import governance as gov_module
from neurova.security import agent_limits_settings as limits_mod


@pytest.fixture
def client(monkeypatch, tmp_path):
    settings_file = tmp_path / "agent_limits.json"
    monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(settings_file))

    from neurova.api.deps import get_current_user

    app = FastAPI()
    app.include_router(gov_module.router, prefix="/api/v1/governance")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin1", "role": "admin",
    }
    return TestClient(app)


class TestAgentLimitsEndpoints:
    def test_get_defaults(self, client):
        resp = client.get("/api/v1/governance/agent-limits")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["token_budget"] == 100000
        assert data["max_loop_rounds"] == 20

    def test_put_then_get_roundtrip(self, client):
        resp = client.put(
            "/api/v1/governance/agent-limits",
            json={"token_budget": 250000, "max_loop_rounds": 40},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["token_budget"] == 250000
        assert data["max_loop_rounds"] == 40

        # 持久化验证：新 client 读同一文件
        resp2 = client.get("/api/v1/governance/agent-limits")
        assert resp2.json()["data"]["token_budget"] == 250000

    def test_put_rejects_out_of_range(self, client):
        resp = client.put(
            "/api/v1/governance/agent-limits",
            json={"token_budget": 100},  # < 1000
        )
        assert resp.status_code == 422

    def test_put_empty_body_422(self, client):
        resp = client.put("/api/v1/governance/agent-limits", json={})
        assert resp.status_code == 422


class TestEffectiveLimits:
    def test_env_overrides_settings(self, monkeypatch, tmp_path):
        settings_file = tmp_path / "agent_limits.json"
        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(settings_file))
        limits_mod.save_agent_limits({"token_budget": 250000})

        monkeypatch.setenv("NEUROVA_AGENT_TOKEN_BUDGET", "500000")
        limits = limits_mod.get_effective_limits()
        assert limits["token_budget"] == 500000

    def test_clamps_out_of_range(self, monkeypatch, tmp_path):
        settings_file = tmp_path / "agent_limits.json"
        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(settings_file))
        limits_mod.save_agent_limits({"token_budget": 999_999_999, "max_loop_rounds": 9999})
        monkeypatch.delenv("NEUROVA_AGENT_TOKEN_BUDGET", raising=False)
        monkeypatch.delenv("NEUROVA_AGENT_MAX_LOOP_ROUNDS", raising=False)

        limits = limits_mod.get_effective_limits()
        assert limits["token_budget"] == 10_000_000
        assert limits["max_loop_rounds"] == 200


class TestGateWiring:
    def test_openai_loop_reads_settings(self, monkeypatch, tmp_path):
        """Loop 构造时门控参数来自设置而非硬编码"""
        settings_file = tmp_path / "agent_limits.json"
        monkeypatch.setenv("NEUROVA_AGENT_LIMITS_SETTINGS", str(settings_file))
        limits_mod.save_agent_limits({"max_loop_rounds": 33})

        from neurova.agent.loops.openai_loop import OpenAILoop

        from types import SimpleNamespace

        agent = SimpleNamespace(
            config=types_namespace_config(),
            llm_client=SimpleNamespace(model="gpt-4o"),
        )
        loop = OpenAILoop(agent)
        gates = {type(g).__name__: g for g in loop._gate_runner._gates}
        assert gates["IterationGate"].max_rounds == 33


def types_namespace_config():
    from types import SimpleNamespace

    return SimpleNamespace(
        llm_config=SimpleNamespace(model="gpt-4o"),
        name="T",
    )
