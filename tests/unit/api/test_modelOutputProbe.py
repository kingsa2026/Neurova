# -*- coding: utf-8 -*-
"""模型管理：输出上限探测端点与 /models 持久化字段透出（2026-10-21）。"""

from types import SimpleNamespace

from fastapi.testclient import TestClient

from neurova.api.app import create_app
from neurova.api.endpoints import model as modelMod


class FakeProviderManager:
    def __init__(self):
        self.calls = []

    def get_provider(self, provider_id):
        return object() if provider_id == "amd" else None

    async def probe_model_output_limit(self, provider_id, model_id, candidate=None):
        self.calls.append((provider_id, model_id, candidate))
        return {
            "supported": True,
            "provider_id": provider_id,
            "model_id": model_id,
            "candidate": candidate or 65536,
            "accepted": True,
            "limit": 65536,
            "source": "probed_accepted",
            "detail": "accepted",
        }

    def get_all_models(self):
        return [
            SimpleNamespace(
                id="GLM-5.3-Flash",
                name="GLM-5.3-Flash",
                owned_by="amd",
                capabilities=["text"],
                context_window=262144,
                max_tokens=4096,
                max_output_tokens=65536,
                max_output_tokens_source="probed_accepted",
                max_output_tokens_probed_at="2026-10-21T23:00:00+00:00",
                is_active=False,
                status="available",
                metadata={"connectable": True},
            )
        ]


def _client(monkeypatch, manager):
    monkeypatch.setattr(modelMod, "_get_provider_manager", lambda current_user: manager)
    app = create_app(enable_memory=False, enable_channels=False)
    return TestClient(app)


def testProbeOutputLimitEndpointPersistsThroughManager(monkeypatch):
    manager = FakeProviderManager()
    client = _client(monkeypatch, manager)

    resp = client.post(
        "/api/v1/models/probe-output-limit",
        json={"provider_id": "amd", "model_id": "GLM-5.3-Flash", "candidate": 65536},
    )

    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["limit"] == 65536 and data["accepted"] is True
    assert manager.calls == [("amd", "GLM-5.3-Flash", 65536)]


def testUnknownProviderIs404(monkeypatch):
    manager = FakeProviderManager()
    client = _client(monkeypatch, manager)

    resp = client.post(
        "/api/v1/models/probe-output-limit",
        json={"provider_id": "nope", "model_id": "m"},
    )

    assert resp.status_code == 404


def testModelsListSurfacesPersistedOutputLimit(monkeypatch):
    manager = FakeProviderManager()
    client = _client(monkeypatch, manager)

    resp = client.get("/api/v1/models")

    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["model_id"] == "GLM-5.3-Flash")
    assert row["max_output_tokens"] == 65536
    assert row["max_output_tokens_source"] == "probed_accepted"
    assert row["max_output_tokens_probed_at"]
