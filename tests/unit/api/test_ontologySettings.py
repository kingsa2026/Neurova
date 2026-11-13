# -*- coding: utf-8 -*-
"""Ontology 设置卡（specs/2026-11-12 §14 扩展）：facts 重抽开关进设置面。

- GET /ontology/settings（登录可读）：extract_on_update 现值＋来源（env/setting/default）
- PUT /ontology/settings（管理员）：写 app_settings advanced.ontology_extract_on_update
- extract_after_update 门控次序：env 显式值最优先 → 设置面 → 默认 off
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api import deps as knowledge_deps
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

ADMIN = {"user_id": "9", "username": "admin", "role": "admin",
         "tenant_id": "default", "agent_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer",
          "tenant_id": "default", "agent_id": "default"}
PREFIX = "/api/v1/knowledge"


@pytest.fixture
def fact_store(tmp_path, monkeypatch):
    from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore

    s = KnowledgeFactStore(str(tmp_path / "facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s)
    yield s
    s.close()


@pytest.fixture
def client(fact_store, tmp_path, monkeypatch):
    # 设置文件隔离：指向 tmp_path，不污染生产 app_settings.json
    monkeypatch.setattr(
        "neurova.core.app_settings._settings_path",
        lambda path=None: tmp_path / "app_settings.json")
    from neurova.api.endpoints import knowledge_core

    app = FastAPI()
    app.include_router(knowledge_core.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(ADMIN)
    app.dependency_overrides[
        knowledge_deps.strictIdentityGate] = lambda: dict(ADMIN)
    return TestClient(app)


class TestOntologySettings:
    def test_getDefaults(self, client):
        r = client.get(f"{PREFIX}/ontology/settings")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["extract_on_update"] is False, "默认 off＝旧行为"
        assert data["source"] in ("default", "setting", "env")

    def test_putRequiresAdmin(self, client):
        client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(VIEWER)
        client.app.dependency_overrides[
            knowledge_deps.strictIdentityGate] = lambda: dict(VIEWER)
        r = client.put(f"{PREFIX}/ontology/settings",
                       json={"extract_on_update": True})
        assert r.status_code == 403

    def test_putThenGateFollowsSetting(self, client, monkeypatch):
        monkeypatch.delenv("NEUROVA_KB_EXTRACT_ON_UPDATE", raising=False)
        r = client.put(f"{PREFIX}/ontology/settings",
                       json={"extract_on_update": True})
        assert r.status_code == 200
        assert r.json()["data"]["extract_on_update"] is True
        # 门控跟随设置：无 env 时设置开启 → 不再 skipped_disabled
        from neurova.api.endpoints.knowledge_common import extract_after_update
        state = extract_after_update(
            {"knowledge_id": "k1", "title": "t", "content": "c"},
            None, "default")
        assert state != "skipped_disabled", "设置开启后门控应放行"
        # 读数面回显
        r2 = client.get(f"{PREFIX}/ontology/settings")
        assert r2.json()["data"]["extract_on_update"] is True

    def test_envExplicitOverridesSetting(self, client, monkeypatch):
        client.put(f"{PREFIX}/ontology/settings",
                   json={"extract_on_update": True})
        monkeypatch.setenv("NEUROVA_KB_EXTRACT_ON_UPDATE", "0")
        from neurova.api.endpoints.knowledge_common import extract_after_update
        state = extract_after_update(
            {"knowledge_id": "k1", "title": "t", "content": "c"},
            None, "default")
        assert state == "skipped_disabled", "env 显式关最优先（运维逃生门）"
