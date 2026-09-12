"""TaskPage/TeamPage 契约对齐 + 落盘回归（2026-09-12 台账清剿 P5a/P5b）。

根因：
1. tasks/teams 端点依赖不存在的 neurova.projects 包（TaskBoardManager/TeamManager
   import 必抛）→ 恒回退进程内 dict，重启即空（"保存不真实落盘"）；
2. 与前端消费契约四处错位：FE 用 id（BE board_id/team_id）、FE GET
   /tasks/boards/{id}/tasks 后端无 GET 路由（404，页面永远空）、FE 状态词汇
   todo/in-progress/done vs BE "To Do..."、FE 批量加成员 {members:[..]} vs
   BE 单成员 {user_id}、FE PUT /teams/{id} 后端无路由（405）。

修复契约：响应/请求全面对齐 FE（id、status 默认 todo、dueDate 透传、
members string[]），补 GET /boards/{id}/tasks 与 PUT /teams/{id}、
批量加成员端点；落盘 data/tasks_api.json 与 data/teams_api.json。
"""
import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

os.environ.setdefault("NEUROVA_JWT_SECRET_KEY", "test_secret_key_for_tasksteam_012345")

from neurova.api.deps import get_current_user  # noqa: F401  (router deps 用 auth 版，见下)
from neurova.api.auth import get_current_user as auth_u
from neurova.api.endpoints import tasks_api, teams_api

MOCK_USER = {"user_id": "u1", "username": "u1", "role": "admin"}


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_TASKS_PATH", str(tmp_path / "tasks_api.json"))
    monkeypatch.setenv("NEUROVA_TEAMS_PATH", str(tmp_path / "teams_api.json"))
    tasks_api._reboot_load()
    teams_api._reboot_load()

    app = FastAPI()
    app.include_router(tasks_api.router, prefix="/api/v1/tasks")
    app.include_router(teams_api.router, prefix="/api/v1/teams")
    app.dependency_overrides[auth_u] = lambda: dict(MOCK_USER)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


class TestTasksContract:
    def test_board_id_field_and_list(self, api):
        r = api.post("/api/v1/tasks/boards", json={"name": "冲刺板"})
        assert r.status_code == 200, r.text
        board = r.json()
        assert "id" in board and "board_id" not in board, "FE 契约是 id"
        assert board["name"] == "冲刺板"
        boards = api.get("/api/v1/tasks/boards").json()
        assert [b["id"] for b in boards] == [board["id"]]

    def test_create_task_with_duedate_and_todo_status(self, api):
        bid = api.post("/api/v1/tasks/boards", json={"name": "b"}).json()["id"]
        r = api.post(f"/api/v1/tasks/boards/{bid}/tasks", json={
            "title": "写周报", "priority": "high", "dueDate": "2026-09-20", "status": "todo",
        })
        assert r.status_code == 200, r.text
        task = r.json()
        assert task["status"] == "todo" and task["dueDate"] == "2026-09-20"
        assert "id" in task

    def test_list_board_tasks_route_exists(self, api):
        bid = api.post("/api/v1/tasks/boards", json={"name": "b"}).json()["id"]
        api.post(f"/api/v1/tasks/boards/{bid}/tasks", json={"title": "t1"})
        r = api.get(f"/api/v1/tasks/boards/{bid}/tasks")
        assert r.status_code == 200, "FE fetchTasks 打的 GET 路由必须存在"
        assert [t["title"] for t in r.json()] == ["t1"]
        assert r.json()[0]["status"] == "todo"

    def test_move_task(self, api):
        bid = api.post("/api/v1/tasks/boards", json={"name": "b"}).json()["id"]
        tid = api.post(f"/api/v1/tasks/boards/{bid}/tasks", json={"title": "t"}).json()["id"]
        r = api.put(f"/api/v1/tasks/tasks/{tid}/move", json={"status": "done"})
        assert r.status_code == 200 and r.json()["status"] == "done"

    def test_persistence_across_restart(self, api):
        bid = api.post("/api/v1/tasks/boards", json={"name": "持久板"}).json()["id"]
        api.post(f"/api/v1/tasks/boards/{bid}/tasks", json={"title": "t"})
        tasks_api._reboot_load()  # 模拟重启：从盘重载
        boards = api.get("/api/v1/tasks/boards").json()
        assert [b["name"] for b in boards] == ["持久板"]
        assert api.get(f"/api/v1/tasks/boards/{bid}/tasks").json()[0]["title"] == "t"


class TestTeamsContract:
    def test_team_id_and_members_array(self, api):
        r = api.post("/api/v1/teams", json={"name": "平台组", "description": "d"})
        assert r.status_code == 200, r.text
        team = r.json()
        assert "id" in team and team["members"] == []
        rid = api.post(f"/api/v1/teams/{team['id']}/members", json={
            "members": ["alice", "bob"], "prompt": "值班",
        })
        assert rid.status_code == 200, rid.text
        assert set(rid.json()["members"]) == {"alice", "bob"}

    def test_update_team_route(self, api):
        tid = api.post("/api/v1/teams", json={"name": "旧名"}).json()["id"]
        r = api.put(f"/api/v1/teams/{tid}", json={"name": "新名"})
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "新名"

    def test_delete_team(self, api):
        tid = api.post("/api/v1/teams", json={"name": "x"}).json()["id"]
        assert api.delete(f"/api/v1/teams/{tid}").status_code == 200
        assert api.get(f"/api/v1/teams/{tid}").status_code == 404

    def test_persistence_across_restart(self, api):
        tid = api.post("/api/v1/teams", json={"name": "持久队"}).json()["id"]
        api.post(f"/api/v1/teams/{tid}/members", json={"members": ["z"]})
        teams_api._reboot_load()
        got = api.get(f"/api/v1/teams/{tid}").json()
        assert got["name"] == "持久队"
        assert got["members"] == ["z"]
