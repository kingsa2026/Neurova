# -*- coding: utf-8 -*-
"""GIS 元数据（升级计划 A6）：条目可选 geo 与 radius/bbox 过滤。

验收（计划 §5 Batch A6）：
- 条目/chunk 增可选 geo（lat/lon），无坐标条目在任何 geo 过滤下不参与；
- radius/bbox 过滤发生在可见视图内（先于索引/检索），不越租户边界；
- 不过滤时行为逐字不变（无 geo 语料行为不变）。
"""
from __future__ import annotations

import pytest

from neurova.knowledge.repository import KnowledgeRepository

T1_USER = {"user_id": "u1", "username": "a", "role": "admin", "tenant_id": "t1"}
T2_USER = {"user_id": "u2", "username": "b", "role": "admin", "tenant_id": "t2"}


@pytest.fixture()
def repo(tmp_path):
    r = KnowledgeRepository(str(tmp_path / "kb"))

    def _add(title, geo):
        r.create_knowledge(
            "agent", title, "内容 " + title,
            owner_user_id="u1", tenant_id="t1", visibility="public",
            geo=geo)
    _add("上海", {"lat": 31.2304, "lon": 121.4737})
    _add("北京", {"lat": 39.9042, "lon": 116.4074})
    _add("无坐标", None)
    return r


def _titles(items):
    return {item["title"] for item in items}


class TestGeoStorage:
    def testGeoRoundTripsThroughCreate(self, repo):
        items = {i["title"]: i for i in repo.visible_items(T1_USER)}

        assert items["上海"]["geo"] == {"lat": 31.2304, "lon": 121.4737}
        assert items["无坐标"]["geo"] is None

    def testInvalidGeoShapeIsNormalizedToNone(self, repo):
        repo.create_knowledge(
            "agent", "坏坐标", "内容", owner_user_id="u1",
            tenant_id="t1", visibility="public", geo={"lat": "北纬", "lon": None})

        item = [i for i in repo.visible_items(T1_USER) if i["title"] == "坏坐标"][0]
        assert item["geo"] is None


class TestGeoFilters:
    def testRadiusKeepsOnlyNearby(self, repo):
        hits = repo.visible_items(
            T1_USER, geo_radius={"lat": 31.23, "lon": 121.47, "radius_km": 50})

        assert _titles(hits) == {"上海"}

    def testRadiusExcludesEntriesWithoutGeo(self, repo):
        hits = repo.visible_items(
            T1_USER, geo_radius={"lat": 0.0, "lon": 0.0, "radius_km": 20000})

        assert _titles(hits) == {"上海", "北京"}

    def testBboxFilter(self, repo):
        hits = repo.visible_items(
            T1_USER, geo_bbox={"min_lat": 30.0, "min_lon": 120.0,
                               "max_lat": 32.0, "max_lon": 123.0})

        assert _titles(hits) == {"上海"}

    def testNoGeoFilterLeavesBehaviorUnchanged(self, repo):
        assert len(repo.visible_items(T1_USER)) == 3

    def testSearchPathAppliesGeoFilter(self, repo):
        hits = repo.search_visible_items(
            T1_USER, "内容", geo_radius={"lat": 39.9, "lon": 116.4, "radius_km": 80},
            limit=10)

        assert _titles(hits) == {"北京"}

    def testGeoFilterDoesNotCrossTenant(self, tmp_path):
        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge(
            "agent", "租户一上海", "内容", owner_user_id="u1",
            tenant_id="t1", visibility="public", geo={"lat": 31.23, "lon": 121.47})
        repo.create_knowledge(
            "agent", "租户二上海", "内容", owner_user_id="u2",
            tenant_id="t2", visibility="public", geo={"lat": 31.24, "lon": 121.48})

        hits = repo.visible_items(
            T1_USER, geo_radius={"lat": 31.23, "lon": 121.47, "radius_km": 100})

        assert _titles(hits) == {"租户一上海"}


class TestSearchEndpointPassesGeo:
    def testSearchEndpointCarriesGeoFilters(self, tmp_path, monkeypatch):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from neurova.api import auth as knowledge_auth
        from neurova.api.endpoints import knowledge as knowledge_module

        repo = KnowledgeRepository(str(tmp_path / "kb"))
        repo.create_knowledge(
            "agent", "上海", "内容", owner_user_id="u1",
            tenant_id="t1", visibility="public", geo={"lat": 31.23, "lon": 121.47})
        repo.create_knowledge(
            "agent", "北京", "内容", owner_user_id="u1",
            tenant_id="t1", visibility="public", geo={"lat": 39.9, "lon": 116.4})
        monkeypatch.setattr(
            "neurova.api.endpoints.knowledge_core.get_repository", lambda: repo)
        app = FastAPI()
        app.include_router(knowledge_module.router, prefix="/v1/knowledge")
        app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(T1_USER)
        client = TestClient(app)

        resp = client.post("/v1/knowledge/search", json={
            "query": "内容",
            "geo_radius": {"lat": 31.23, "lon": 121.47, "radius_km": 50},
        })

        assert resp.status_code == 200, resp.text
        assert {i["title"] for i in resp.json()} == {"上海"}
