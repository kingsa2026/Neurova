# -*- coding: utf-8 -*-
"""P2-3 模型能力体检并入 readiness（对照研究 reference_y 报告 §5 P2-3）红灯。

- `knowledgeReadiness` 增可选 `modelProbe` 回调：不给（缺省）= 探针关闭，
  `model_ready` 为 None、`model_probe.state="disabled"`——零网络、零成本，
  现有调用方零漂移；
- 给了回调：ok→"pass"、非 ok→"fail"、回调抛异常→"fail" 且 detail 带原因
  （不吞异常、不假装验过）；
- 端点层：env `NEUROVA_ONTOLOGY_MODEL_PROBE` 默认关；开时用 LLM 客户端面发
  一次最小探针。
"""

from __future__ import annotations

import pytest

from neurova.knowledge.ontology.readiness import knowledgeReadiness


class TestModelProbeCallback:

    def test_disabledByDefault(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            data = knowledgeReadiness(store, "default")
            assert data["model_ready"] is None
            assert data["model_probe"]["state"] == "disabled"
            # 既有两判据不漂移
            assert data["knowledge_ready"] is False
            assert data["data_ready"] is False
        finally:
            store.close()

    def test_probePass(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            data = knowledgeReadiness(store, "default",
                                      modelProbe=lambda: {"ok": True, "detail": "pong"})
            assert data["model_ready"] == "pass"
            assert data["model_probe"]["state"] == "pass"
        finally:
            store.close()

    def test_probeFail(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            data = knowledgeReadiness(store, "default",
                                      modelProbe=lambda: {"ok": False,
                                                          "detail": "unpriced"})
            assert data["model_ready"] == "fail"
            assert data["model_probe"]["detail"] == "unpriced"
        finally:
            store.close()

    def test_probeExceptionIsHonestFailure(self, tmp_path):
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(tmp_path / "kb.db"))
        try:
            def _boom():
                raise RuntimeError("provider offline")
            data = knowledgeReadiness(store, "default", modelProbe=_boom)
            assert data["model_ready"] == "fail"
            assert "provider offline" in str(data["model_probe"].get("detail"))
        finally:
            store.close()


class TestReadinessEndpointWiring:

    def _client(self, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from neurova.api import auth as knowledge_auth
        from neurova.api.endpoints import knowledge_observability
        from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

        store = KnowledgeFactStore(str(self.tmp_path / "kb.db"))
        monkeypatch.setattr(
            "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: store)
        app = FastAPI()
        app.include_router(knowledge_observability.router, prefix="/v1/knowledge")
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = (
            lambda: {"user_id": "9", "username": "admin", "role": "admin",
                     "tenant_id": "default"})
        return TestClient(app), store

    def test_endpointProbeOffByDefault(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        client, store = self._client(monkeypatch)
        try:
            monkeypatch.delenv("NEUROVA_ONTOLOGY_MODEL_PROBE", raising=False)
            resp = client.get("/v1/knowledge/ontology/readiness")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["model_ready"] is None
            assert data["model_probe"]["state"] == "disabled"
        finally:
            store.close()

    def test_endpointProbeOnUsesLlmClients(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        client, store = self._client(monkeypatch)
        try:
            monkeypatch.setenv("NEUROVA_ONTOLOGY_MODEL_PROBE", "1")

            class _Resp:
                content = "pong"

            class _Client:
                async def chat(self, messages):
                    assert messages and messages[0]["role"] == "user"
                    return _Resp()

            monkeypatch.setattr(
                "neurova.api.endpoints.knowledge_common.resolveAgentLlmClients",
                lambda request, prefer_agent_id=None: [_Client()])
            resp = client.get("/v1/knowledge/ontology/readiness")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["model_ready"] == "pass"
            assert data["model_probe"]["state"] == "pass"
        finally:
            store.close()

    def test_endpointProbeOnNoClientsIsFail(self, tmp_path, monkeypatch):
        self.tmp_path = tmp_path
        client, store = self._client(monkeypatch)
        try:
            monkeypatch.setenv("NEUROVA_ONTOLOGY_MODEL_PROBE", "1")
            monkeypatch.setattr(
                "neurova.api.endpoints.knowledge_common.resolveAgentLlmClients",
                lambda request, prefer_agent_id=None: [])
            resp = client.get("/v1/knowledge/ontology/readiness")
            assert resp.status_code == 200
            data = resp.json()["data"]
            assert data["model_ready"] == "fail"
            assert data["model_probe"]["state"] == "fail"
        finally:
            store.close()
