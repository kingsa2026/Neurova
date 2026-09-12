"""LLM 429 重试设置（max_retries / interval / wait_cap / max_switches）契约测试。

锁定（2026-09-11 设置页"模型"tab 对齐）：
1. GET/PUT /api/v1/governance/llm-retry（admin）读写 JSON 持久化设置；
2. 越界值被 FastAPI 校验拒绝；
3. get_effective_llm_retry_settings 优先级：env 显式 > 持久化 > 内置默认 + 夹紧；
4. MultiModelLLMClient._get_429_retry_config 消费生效值（非仅 env）。
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api.endpoints import governance as gov_module
from neurova.security import llm_retry_settings as retry_mod


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("NEUROVA_LLM_RETRY_SETTINGS", str(tmp_path / "llm_retry.json"))
    for key in ("NEUROVA_LLM_429_MAX_RETRIES", "NEUROVA_LLM_429_RETRY_INTERVAL",
                "NEUROVA_LLM_429_WAIT_CAP", "NEUROVA_LLM_MAX_SWITCHES"):
        monkeypatch.delenv(key, raising=False)

    from neurova.api.deps import get_current_user

    app = FastAPI()
    app.include_router(gov_module.router, prefix="/api/v1/governance")
    app.dependency_overrides[get_current_user] = lambda: {
        "user_id": "admin1", "role": "admin",
    }
    return TestClient(app)


class TestLlmRetryEndpoints:
    def test_get_defaults(self, client):
        resp = client.get("/api/v1/governance/llm-retry")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data == {"max_retries": 10, "interval": 10.0, "wait_cap": 120.0, "max_switches": 5}

    def test_put_then_get_roundtrip(self, client):
        resp = client.put(
            "/api/v1/governance/llm-retry",
            json={"max_retries": 6, "interval": 15, "wait_cap": 90, "max_switches": 3},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["max_retries"] == 6
        assert data["interval"] == 15.0
        assert data["wait_cap"] == 90.0
        assert data["max_switches"] == 3
        # 持久化：重读同一文件
        assert client.get("/api/v1/governance/llm-retry").json()["data"]["max_retries"] == 6

    def test_put_rejects_out_of_range(self, client):
        resp = client.put("/api/v1/governance/llm-retry", json={"max_retries": 999})
        assert resp.status_code == 422
        resp = client.put("/api/v1/governance/llm-retry", json={"interval": 0.2})
        assert resp.status_code == 422
        resp = client.put("/api/v1/governance/llm-retry", json={"max_switches": 0})
        assert resp.status_code == 422

    def test_put_empty_body_rejected(self, client):
        resp = client.put("/api/v1/governance/llm-retry", json={})
        assert resp.status_code == 422


class TestEffectiveSettings:
    def test_priority_env_over_persisted(self, client, monkeypatch):
        client.put("/api/v1/governance/llm-retry", json={"max_retries": 6})
        monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "3")
        assert retry_mod.get_effective_llm_retry_settings()["max_retries"] == 3

    def test_persisted_used_without_env(self, client):
        client.put("/api/v1/governance/llm-retry", json={"interval": 20})
        eff = retry_mod.get_effective_llm_retry_settings()
        assert eff["interval"] == 20.0
        assert eff["max_retries"] == 10  # 未设置的键保持默认

    def test_clamped_to_range(self, monkeypatch, tmp_path):
        monkeypatch.setenv("NEUROVA_LLM_RETRY_SETTINGS", str(tmp_path / "c.json"))
        assert retry_mod.save_llm_retry_settings({"max_retries": 10000})
        assert retry_mod.get_effective_llm_retry_settings()["max_retries"] == 50


class TestMmcConsumesEffective:
    def test_get_429_retry_config_reads_persisted(self, client):
        from neurova.llm.multi_model_client import _get_429_retry_config

        client.put("/api/v1/governance/llm-retry", json={"max_retries": 4, "interval": 12})
        cfg = _get_429_retry_config()
        assert cfg["max_retries"] == 4
        assert cfg["interval"] == 12.0

    def test_env_still_wins_for_mmc(self, client, monkeypatch):
        from neurova.llm.multi_model_client import _get_429_retry_config

        client.put("/api/v1/governance/llm-retry", json={"max_retries": 4})
        monkeypatch.setenv("NEUROVA_LLM_429_MAX_RETRIES", "7")
        assert _get_429_retry_config()["max_retries"] == 7


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
