# -*- coding: utf-8 -*-
"""空间视图数据面（升级计划 MapLibre 前置）：可见 geo 条目的列表读面。

MapLibre 打点需要"当前用户可见、带坐标"的条目清单——search 端点要求查询词，
不适合"全部有坐标的条目"这一问法。`GET /knowledge/geo` 复用 visible_items
的可见性与 A6 空间过滤（radius/bbox），无坐标条目天然不出现。
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neurova.api import auth as knowledge_auth
from neurova.api.endpoints import knowledge as knowledge_module
from neurova.knowledge.repository import KnowledgeRepository

T1_USER = {"user_id": "u1", "username": "a", "role": "admin",
           "tenant_id": "t1", "neuser_id": "1"}
T2_USER = {"user_id": "u2", "username": "b", "role": "admin",
           "tenant_id": "t2", "neuser_id": "2"}
PREFIX = "/v1/knowledge"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    repo = KnowledgeRepository(str(tmp_path / "kb"))

    def _add(title, geo, tenant="t1", owner="u1"):
        repo.create_knowledge(
            "agent", title, "内容 " + title, owner_user_id=owner,
            tenant_id=tenant, visibility="public", geo=geo)
    _add("上海", {"lat": 31.2304, "lon": 121.4737})
    _add("北京", {"lat": 39.9042, "lon": 116.4074})
    _add("无坐标", None)
    _add("租户二广州", {"lat": 23.1291, "lon": 113.2644},
         tenant="t2", owner="u2")
    monkeypatch.setattr(
        "neurova.api.endpoints.knowledge_core.get_repository", lambda: repo)
    app = FastAPI()
    app.include_router(knowledge_module.router, prefix=PREFIX)
    app.dependency_overrides[
        knowledge_auth.get_current_user_or_service] = lambda: dict(T1_USER)
    return TestClient(app)


class TestGeoListEndpoint:
    def testListsVisibleGeoEntriesOnly(self, client):
        resp = client.get(PREFIX + "/geo")

        assert resp.status_code == 200, resp.text
        items = resp.json()["data"]["items"]
        titles = {i["title"] for i in items}
        assert titles == {"上海", "北京"}
        shanghai = next(i for i in items if i["title"] == "上海")
        assert shanghai["geo"] == {"lat": 31.2304, "lon": 121.4737}

    def testBboxFilter(self, client):
        resp = client.get(PREFIX + "/geo", params={
            "min_lat": 30.0, "min_lon": 120.0, "max_lat": 32.0, "max_lon": 123.0})

        assert resp.status_code == 200, resp.text
        assert {i["title"] for i in resp.json()["data"]["items"]} == {"上海"}

    def testRadiusFilter(self, client):
        resp = client.get(PREFIX + "/geo", params={
            "lat": 39.9, "lon": 116.4, "radius_km": 100})

        assert resp.status_code == 200, resp.text
        assert {i["title"] for i in resp.json()["data"]["items"]} == {"北京"}

    def testDoesNotCrossTenant(self, client):
        client.app.dependency_overrides[
            knowledge_auth.get_current_user_or_service] = lambda: dict(T2_USER)

        resp = client.get(PREFIX + "/geo")

        assert resp.status_code == 200, resp.text
        assert {i["title"] for i in resp.json()["data"]["items"]} == {"租户二广州"}
