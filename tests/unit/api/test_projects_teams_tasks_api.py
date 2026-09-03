"""项目团队/任务 API 测试（TDD RED→GREEN）

端点（挂载于 /api/v1/projects）：
- POST/GET        /                项目 CRUD（与团队/任务同源：collaboration_isolation.Project）
- GET             /{project_id}/stats
- POST/GET /{project_id}/teams
- POST /{project_id}/teams/{tid}/members
- GET  /{project_id}/teams/{tid}/agents
- POST /{project_id}/tasks            （注册 WorkflowTaskExecutor 定时作业）
- POST /{project_id}/tasks/{tid}/pause|resume

调度复用 agent/scheduler.TaskScheduler；测试中以 MagicMock 注入。
"""

import os
import sys
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


@pytest.fixture
def client(tmp_path, monkeypatch):
    from neurova.api.endpoints import projects_api
    from neurova.collaboration.collaboration_isolation import CollaborationIsolationManager

    manager = CollaborationIsolationManager(data_dir=str(tmp_path / "collab"))
    monkeypatch.setattr(projects_api, "_get_iso_manager", lambda: manager)

    scheduler = MagicMock()
    monkeypatch.setattr(projects_api, "_get_scheduler", lambda: scheduler)

    app = FastAPI()
    app.include_router(projects_api.router, prefix="/api/v1/projects")
    client = TestClient(app)

    project = manager.create_project(name="测试项目", owner_id="u1")
    client.project_id = project.project_id  # type: ignore[attr-defined]
    client.manager = manager  # type: ignore[attr-defined]
    client.scheduler_mock = scheduler  # type: ignore[attr-defined]
    return client


# ----------------------------- 团队 -----------------------------


class TestTeamsApi:
    def test_create_and_list_team(self, client):
        pid = client.project_id
        resp = client.post(f"/api/v1/projects/{pid}/teams", json={"name": "调研组", "description": "收集资料"})
        assert resp.status_code == 200, resp.text
        team = resp.json()["data"]
        assert team["name"] == "调研组"
        assert team["team_id"].startswith("team_")

        resp = client.get(f"/api/v1/projects/{pid}/teams")
        teams = resp.json()["data"]["teams"]
        assert any(t["team_id"] == team["team_id"] for t in teams)

    def test_add_member_and_list_agents(self, client):
        pid = client.project_id
        team = client.post(f"/api/v1/projects/{pid}/teams", json={"name": "T"}).json()["data"]
        tid = team["team_id"]

        resp = client.post(
            f"/api/v1/projects/{pid}/teams/{tid}/members",
            json={"agent_id": "agent_a", "agent_name": "研究员", "role": "leader"},
        )
        assert resp.status_code == 200

        resp = client.get(f"/api/v1/projects/{pid}/teams/{tid}/agents")
        agents = resp.json()["data"]["agents"]
        assert {"agent_id": "agent_a", "agent_name": "研究员", "role": "leader"} in [
            {"agent_id": a["agent_id"], "agent_name": a["agent_name"], "role": a["role"]} for a in agents
        ]

    def test_create_team_project_not_found(self, client):
        resp = client.post("/api/v1/projects/nope/teams", json={"name": "T"})
        assert resp.status_code == 404


# ----------------------------- 任务 -----------------------------


class TestTasksApi:
    def test_create_task_registers_scheduler(self, client):
        pid = client.project_id
        resp = client.post(
            f"/api/v1/projects/{pid}/tasks",
            json={
                "name": "每日简报",
                "workflow_id": "canvas_abc",
                "schedule_config": {"type": "cron", "cron": "0 9 * * *"},
            },
        )
        assert resp.status_code == 200, resp.text
        task = resp.json()["data"]
        assert task["workflow_id"] == "canvas_abc"
        assert task["status"] == "active"

        # 调度器收到 WORKFLOW 类型任务，target 为画布 id，metadata 带项目归属
        client.scheduler_mock.add_task.assert_called_once()
        registered = client.scheduler_mock.add_task.call_args[0][0]
        assert registered.request.workflow_id == "canvas_abc"
        assert registered.request.input.get("project_id") == pid
        assert registered.schedule.cron == "0 9 * * *"
        assert registered.id == task["task_id"]

        # 任务已持久化到项目
        project = client.manager.get_project(pid)
        assert task["task_id"] in project.tasks

    def test_create_task_passes_date_bounds_for_one_shot(self, client):
        """「指定日期时间」一次性任务：start/end 需透传给调度器，避免 cron 每年重复触发。"""
        pid = client.project_id
        resp = client.post(
            f"/api/v1/projects/{pid}/tasks",
            json={
                "name": "发布会提醒",
                "workflow_id": "wf_launch",
                "schedule_config": {
                    "type": "cron",
                    "cron": "30 9 1 9 *",
                    "start_date": "2026-09-01T09:30:00",
                    "end_date": "2026-09-01T09:31:00",
                },
            },
        )
        assert resp.status_code == 200, resp.text
        registered = client.scheduler_mock.add_task.call_args[0][0]
        assert registered.schedule.start_date is not None
        assert registered.schedule.end_date is not None
        assert registered.schedule.start_date.isoformat() == "2026-09-01T09:30:00"
        # 边界也持久化，前端刷新后可还原展示
        stored = resp.json()["data"]["schedule_config"]
        assert stored["end_date"] == "2026-09-01T09:31:00"

    def test_create_task_invalid_date_bounds_400(self, client):
        resp = client.post(
            f"/api/v1/projects/{client.project_id}/tasks",
            json={
                "name": "坏时间",
                "workflow_id": "wf1",
                "schedule_config": {"type": "cron", "cron": "0 9 * * *", "end_date": "not-a-date"},
            },
        )
        assert resp.status_code == 400

    def test_pause_resume_task(self, client):
        pid = client.project_id
        task = client.post(
            f"/api/v1/projects/{pid}/tasks",
            json={"name": "轮询", "workflow_id": "wf1", "schedule_config": {"type": "interval", "interval_seconds": 60}},
        ).json()["data"]
        tid = task["task_id"]

        resp = client.post(f"/api/v1/projects/{pid}/tasks/{tid}/pause")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "paused"
        client.scheduler_mock.disable_task.assert_called_with(tid)

        resp = client.post(f"/api/v1/projects/{pid}/tasks/{tid}/resume")
        assert resp.status_code == 200
        assert resp.json()["data"]["status"] == "active"
        client.scheduler_mock.enable_task.assert_called_with(tid)

    def test_create_task_requires_workflow(self, client):
        resp = client.post(
            f"/api/v1/projects/{client.project_id}/tasks",
            json={"name": "缺工作流", "workflow_id": "", "schedule_config": {"type": "cron", "cron": "* * * * *"}},
        )
        assert resp.status_code == 400

    def test_pause_unknown_task_404(self, client):
        resp = client.post(f"/api/v1/projects/{client.project_id}/tasks/nope/pause")
        assert resp.status_code == 404

    def test_list_tasks(self, client):
        pid = client.project_id
        client.post(
            f"/api/v1/projects/{pid}/tasks",
            json={"name": "T1", "workflow_id": "wf1", "schedule_config": {"type": "cron", "cron": "0 9 * * *"}},
        )
        resp = client.get(f"/api/v1/projects/{pid}/tasks")
        assert resp.status_code == 200
        tasks = resp.json()["data"]["tasks"]
        assert len(tasks) == 1
        assert tasks[0]["name"] == "T1"
        assert tasks[0]["schedule_config"]["cron"] == "0 9 * * *"


# ----------------------------- 项目 CRUD -----------------------------


class TestProjectsCrudApi:
    """项目 CRUD 与团队/任务必须同源（collaboration_isolation）。

    回归背景：旧实现把项目放在内存 dict / 不存在的 ProjectManager，
    团队与任务却查 collaboration_isolation，导致建完项目后 /teams、/tasks 恒 404，
    且重启后项目全部丢失。
    """

    def test_create_project_lands_in_iso_store_and_disk(self, client, tmp_path):
        resp = client.post("/api/v1/projects", json={"name": "新项目", "description": "d1"})
        assert resp.status_code == 200, resp.text
        info = resp.json()
        assert info["name"] == "新项目"
        assert info["owner_id"]
        pid = info["project_id"]

        # 同一存储：manager 能取到，且落盘可恢复
        assert client.manager.get_project(pid) is not None
        persisted = tmp_path / "collab" / "projects" / f"{pid}.json"
        assert persisted.exists(), "项目必须持久化到 collaboration/projects 目录"

    def test_get_project_returns_info_shape(self, client):
        created = client.post("/api/v1/projects", json={"name": "形状"}).json()
        resp = client.get(f"/api/v1/projects/{created['project_id']}")
        assert resp.status_code == 200
        info = resp.json()
        for key in ("project_id", "name", "status", "teams_count", "tasks_count"):
            assert key in info

    def test_list_and_status_filter(self, client):
        client.post("/api/v1/projects", json={"name": "A"})
        client.post("/api/v1/projects", json={"name": "B"})
        names = {p["name"] for p in client.get("/api/v1/projects").json()}
        assert {"A", "B"} <= names

    def test_update_project(self, client):
        pid = client.post("/api/v1/projects", json={"name": "旧名"}).json()["project_id"]
        resp = client.put(f"/api/v1/projects/{pid}", json={"name": "新名", "status": "archived"})
        assert resp.status_code == 200, resp.text
        assert resp.json()["name"] == "新名"
        assert client.manager.get_project(pid).name == "新名"

    def test_delete_project(self, client):
        pid = client.post("/api/v1/projects", json={"name": "待删"}).json()["project_id"]
        assert client.delete(f"/api/v1/projects/{pid}").status_code == 200
        assert client.get(f"/api/v1/projects/{pid}").status_code == 404

    def test_stats_counts_teams_and_tasks(self, client):
        pid = client.post("/api/v1/projects", json={"name": "统计"}).json()["project_id"]
        client.post(f"/api/v1/projects/{pid}/teams", json={"name": "T"})
        client.post(
            f"/api/v1/projects/{pid}/tasks",
            json={"name": "K", "workflow_id": "wf", "schedule_config": {"type": "interval", "interval_seconds": 60}},
        )
        resp = client.get(f"/api/v1/projects/{pid}/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["teams_count"] == 1
        assert stats["tasks_count"] == 1

    def test_create_then_list_teams_no_404(self, client):
        """原始 Bug 回归：通过 API 建项目后立即拉团队/任务不得 404。"""
        pid = client.post("/api/v1/projects", json={"name": "回归"}).json()["project_id"]
        assert client.get(f"/api/v1/projects/{pid}/teams").status_code == 200
        assert client.get(f"/api/v1/projects/{pid}/tasks").status_code == 200
