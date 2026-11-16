# -*- coding: utf-8 -*-
"""R4→R6 移交悬空：list_projects 属主过滤接线最后一公里（审计 §3.4-2）。

R4 已在 `collaboration_isolation.list_projects` 落地 requester_id 过滤层
（给定即按「成员或公开可见」过滤；不传保持旧口径——仅限系统内部/管理员
已自行鉴权的调用方），但 HTTP 面五处调用点都没传 requester_id——过滤层
是死的，多用户部署下任何登录用户都列全量项目，横向信息泄露未闭环：

- collaboration_api `/templates` `/history` `/sessions` `/stats`（四处
  `manager.list_projects(...)`）；
- projects_api `GET /v1/projects`（`iso.list_projects()`）。

修复判据：普通用户只见自己参与/可见的项目；admin 全量（端点层对 admin
不传 requester_id，保持系统面口径）；路由器级鉴权依赖已在，端点内取
`current_user` 解析 requester。真实隔离语义直接咬合
CollaborationIsolationManager（不 mock 过滤层内部）。
"""
import asyncio
from types import SimpleNamespace

import pytest

import neurova.api.endpoints.collaboration_api as collabApi
import neurova.api.endpoints.projects_api as projectsApi
from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    manager = CollaborationIsolationManager(data_dir=str(tmp_path))
    assert manager.create_project(name="alice-private", owner_id="u1", description="d1")
    assert manager.create_project(name="bob-private", owner_id="u2", description="d2")
    monkeypatch.setattr(collabApi, "get_collaboration_manager", lambda: manager)
    monkeypatch.setattr(projectsApi, "_get_iso_manager", lambda: manager)
    return manager


def _request():
    return SimpleNamespace(state=SimpleNamespace(request_id="r6"))


def _user(uid: str, role: str = "user"):
    return {"user_id": uid, "role": role}


def testCollabHistoryOnlyShowsOwnProjectsForPlainUser(iso):
    resp = asyncio.run(collabApi.get_collaboration_history(
        _request(), limit=50, offset=0, current_user=_user("u1")))
    names = {h["name"] for h in resp["data"]["history"]}
    assert "alice-private" in names
    assert "bob-private" not in names, "普通用户看到了他人私有项目（横向泄露）"


def testCollabSessionsFilterByRequester(iso):
    resp = asyncio.run(collabApi.list_collaboration_sessions(
        _request(), limit=50, offset=0, current_user=_user("u2")))
    names = {s["name"] for s in resp["data"]}
    assert names == {"bob-private"}


def testCollabTemplatesFilterByRequester(iso):
    templates = asyncio.run(collabApi.get_collaboration_templates(
        _request(), limit=20, current_user=_user("u2")))
    names = {t.name for t in templates}
    assert names == {"bob-private"}


def testCollabStatsCountsOnlyVisibleProjects(iso):
    resp = asyncio.run(collabApi.get_collaboration_stats(
        _request(), current_user=_user("u1")))
    assert resp["data"]["projects"] == 1, "统计口径仍按全量计数（泄露项目存在性）"


def testAdminSeesAllProjects(iso):
    resp = asyncio.run(collabApi.get_collaboration_history(
        _request(), limit=50, offset=0, current_user=_user("a1", "admin")))
    names = {h["name"] for h in resp["data"]["history"]}
    assert names == {"alice-private", "bob-private"}


def testProjectsApiListFiltersByRequester(iso):
    projects = asyncio.run(projectsApi.list_projects(None, current_user=_user("u1")))
    names = {p.name for p in projects}
    assert "alice-private" in names
    assert "bob-private" not in names


def testProjectsApiListAdminSeesAll(iso):
    projects = asyncio.run(projectsApi.list_projects(None, current_user=_user("a1", "admin")))
    names = {p.name for p in projects}
    assert names == {"alice-private", "bob-private"}
