# -*- coding: utf-8 -*-
"""S17 F1 消费面：项目协作档案聚合增请求归档摘要（TDD RED→GREEN）。

红灯（方案 S17）：档案聚合能读到归档摘要——
GET /projects/{id}/collaboration 的 data["request_archive"] 出现
次数/token/时延分布/最近错误，且只聚合本项目 run 归属会话的归档
（别的会话不串入，与 S12 "无标 run 不串入档案"同判据）。
"""

import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def dossierEnv(tmp_path, monkeypatch):
    """数据根/台账库整体重定向到临时目录；台账单例逐测试重置。"""
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NEUROVA_RUN_STORE_DB", str(tmp_path / "agent_runs.db"))
    from neurova.core.agent_run_store import reset_agent_run_store

    reset_agent_run_store()
    yield tmp_path
    reset_agent_run_store()


@pytest.fixture
def client(dossierEnv, monkeypatch):
    from neurova.api.endpoints import projects_api
    from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager

    tmp_path = dossierEnv
    manager = CollaborationIsolationManager(data_dir=str(tmp_path / "collab"))
    monkeypatch.setattr(projects_api, "_get_iso_manager", lambda: manager)
    monkeypatch.setattr(projects_api, "_get_scheduler", lambda: MagicMock())

    app = FastAPI()
    app.include_router(projects_api.router, prefix="/api/v1/projects")
    from neurova.api.auth import get_current_user as _gcu

    app.dependency_overrides[_gcu] = lambda: {
        "user_id": "u1", "username": "u1", "role": "admin", "neuser_id": "u1",
    }
    testClient = TestClient(app)

    project = manager.create_project(name="请求归档项目", owner_id="u1")
    testClient.project_id = project.project_id  # type: ignore[attr-defined]
    return testClient


def _seedTaggedRun(projectId, subagentId="swarm_reqarc", memberSessionId="member_reqarc1"):
    """经唯一写点 openSubagentRun 落一条带项目标的台账行。"""
    from neurova.core.agent_run_ledger import openSubagentRun

    return openSubagentRun(
        memberSessionId=memberSessionId,
        subagentId=subagentId,
        parentSessionId="parent_s1",
        userId="u1",
        agentId="member_a",
        task="请求归档聚合任务",
        projectId=projectId,
    )


class TestDossierRequestArchiveSummary:
    def test_dossierExposesRequestArchiveSummary(self, client):
        """档案聚合读到请求归档摘要：次数/token/时延分布/最近错误。"""
        from neurova.core.request_archive import (
            flushRequestArchive,
            recordRequestArchive,
        )
        from neurova.core.turn_context import set_turn_identity

        pid = client.project_id
        assert _seedTaggedRun(pid), "红灯：带项目标的台账行未落库"

        set_turn_identity("任务", session_id="member_reqarc1")
        recordRequestArchive(
            provider="p1", model="m1",
            messages=[{"role": "user", "content": "任务"}],
            usage={"promptTokens": 10, "completionTokens": 4},
            durationMs=800, success=True,
        )
        recordRequestArchive(
            provider="p1", model="m1",
            messages=[{"role": "user", "content": "任务"}, {"role": "assistant", "content": "报告"}],
            usage={"promptTokens": 20, "completionTokens": 6},
            durationMs=2500, success=True,
        )
        recordRequestArchive(
            provider="p1", model="m1",
            messages=[{"role": "user", "content": "重试"}],
            usage={"promptTokens": 0, "completionTokens": 0},
            durationMs=30000, success=False,
            errorKind="rate_limited",
            errorSummary="429 too many requests, retry later",
        )
        flushRequestArchive(timeout=5)

        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert "request_archive" in data, "红灯：档案聚合缺 request_archive 读面"

        summary = data["request_archive"]
        assert summary["requestCount"] == 3, f"红灯：归档次数不符：{summary}"
        assert summary["promptTokens"] == 30
        assert summary["completionTokens"] == 10
        assert summary["failureCount"] == 1
        buckets = summary["latencyMs"]["buckets"]
        assert buckets.get("lt1s") == 1, f"红灯：时延分布缺桶读数：{buckets}"
        assert buckets.get("s1to5") == 1
        assert buckets.get("gt20s") == 1
        assert len(summary["recentErrors"]) == 1
        recent = summary["recentErrors"][0]
        assert recent["errorKind"] == "rate_limited"
        assert recent["model"] == "m1"
        assert data["counts"]["request_archive"] == 3

    def test_otherSessionArchivesDoNotLeakIn(self, client):
        """非本项目 run 归属会话的归档不串入档案（按 session→run→project 读时 join）。"""
        from neurova.core.request_archive import (
            flushRequestArchive,
            recordRequestArchive,
        )
        from neurova.core.turn_context import set_turn_identity

        pid = client.project_id
        assert _seedTaggedRun(pid)

        set_turn_identity("别家的", session_id="member_other1")
        recordRequestArchive(
            provider="p9", model="m9",
            messages=[{"role": "user", "content": "别家的"}],
            usage={"promptTokens": 99, "completionTokens": 99},
            durationMs=100, success=True,
        )
        flushRequestArchive(timeout=5)

        resp = client.get(f"/api/v1/projects/{pid}/collaboration")
        assert resp.status_code == 200
        summary = resp.json()["data"]["request_archive"]
        assert summary["requestCount"] == 0, f"红灯：他会话归档串入项目档案：{summary}"
