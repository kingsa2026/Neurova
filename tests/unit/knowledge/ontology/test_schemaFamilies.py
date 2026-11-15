# -*- coding: utf-8 -*-
"""同构表副本聚族（P3-2）判据：OLD_/NEW_ 前缀孪生（列集 Jaccard≥0.8）成族；
历史表不参与；不成族的表不硬凑；建议幂等；端点仅管理员。"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.knowledge.enterprise.protocols import SourceSchema
from neurova.knowledge.enterprise.schema_catalog import SchemaCatalogStore
from neurova.knowledge.foundation.knowledge_facts import KnowledgeFactStore
from neurova.knowledge.ontology.schema_families import (
    detectTermFamilies,
    suggestFamilies,
)
from neurova.knowledge.ontology.schema_suggester import SchemaSuggester

ADMIN = {"user_id": "9", "username": "admin", "role": "admin", "tenant_id": "default"}
VIEWER = {"user_id": "5", "username": "viewer", "role": "viewer", "tenant_id": "default"}
PREFIX = "/v1/knowledge"

_ROOM_COLUMNS = [{"name": "id", "type": "INTEGER"},
                 {"name": "name", "type": "TEXT"},
                 {"name": "capacity", "type": "INTEGER"}]


@pytest.fixture
def store(tmp_path, monkeypatch):
    s = KnowledgeFactStore(str(tmp_path / "knowledge_facts.db"))
    monkeypatch.setattr(
        "neurova.knowledge.foundation.get_knowledge_fact_store", lambda: s
    )
    yield s
    s.close()


def _ingest(store):
    cat = SchemaCatalogStore(store)
    cat.ingestSchema("default", "wh", "sql", SourceSchema(
        sourceId="wh", sourceType="sql", tables=[
            {"name": "OLD_ROOMS", "columns": _ROOM_COLUMNS},
            {"name": "NEW_ROOMS", "columns": _ROOM_COLUMNS},
            {"name": "ROOMS_HIST", "columns": _ROOM_COLUMNS},
            {"name": "employees", "columns": [{"name": "id", "type": "INTEGER"},
                                              {"name": "badge", "type": "TEXT"}]},
        ]))
    return cat


class TestDetectTermFamilies:
    def testTwinsGroupAndHistoryExcluded(self, store):
        cat = _ingest(store)
        families = detectTermFamilies(cat, "default", "wh")
        assert len(families) == 1
        family = families[0]
        assert family["base_name"] == "Rooms"
        assert family["members"] == ["NEW_ROOMS", "OLD_ROOMS"]
        assert family["prefixes"] == ["NEW", "OLD"]

    def testUnrelatedTablesDoNotMerge(self, store):
        cat = _ingest(store)
        families = detectTermFamilies(cat, "default", "wh")
        # employees 列集与 ROOMS 无重叠，不进族
        assert all("employees" not in f["members"] for f in families)

    def testSuggestFamiliesIsIdempotent(self, store):
        cat = _ingest(store)
        suggester = SchemaSuggester(store, catalog=cat)
        first = suggestFamilies(suggester, cat, "default", "wh")
        assert first["suggestions_created"] == 1
        second = suggestFamilies(suggester, cat, "default", "wh")
        assert second["suggestions_created"] == 0
        pending = suggester.listSuggestions("default", kind="family")
        assert pending[0]["payload"]["members"] == ["NEW_ROOMS", "OLD_ROOMS"]


class TestFamiliesRest:
    @pytest.fixture
    def client(self, store):
        from neurova.api.endpoints import knowledge_schema_suggester

        _ingest(store)
        app = FastAPI()
        app.include_router(knowledge_schema_suggester.router, prefix=PREFIX)
        app.dependency_overrides[knowledge_auth.get_current_user_or_service] = \
            lambda: dict(ADMIN)
        yield TestClient(app)

    def testDetectAdminOnly(self, client):
        client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(VIEWER)
        resp = client.post(PREFIX + "/ontology/schema-families/detect",
                           json={"source_id": "wh"})
        assert resp.status_code == 403

    def testDetectRoundtrip(self, client):
        resp = client.post(PREFIX + "/ontology/schema-families/detect",
                           json={"source_id": "wh"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["suggestions_created"] == 1
        assert data["families"][0]["base_name"] == "Rooms"
