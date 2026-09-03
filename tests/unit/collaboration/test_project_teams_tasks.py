"""项目脚手架：ProjectTeam / ProjectTask 数据模型测试（TDD RED→GREEN）

项目 = 顶级分类。团队聚合 Agent 成员，任务绑定工作流定时执行。
"""

import pytest

from neurova.collaboration.collaboration_isolation import Project, ProjectTask, ProjectTeam


# ----------------------------- ProjectTeam -----------------------------


def test_project_team_defaults_and_roundtrip():
    team = ProjectTeam(name="调研组", description="负责资料收集")
    assert team.team_id.startswith("team_")
    assert team.members == {}

    team.members["agent_a"] = {"agent_name": "研究员", "role": "leader"}
    data = team.to_dict()
    restored = ProjectTeam.from_dict(data)
    assert restored.name == "调研组"
    assert restored.members["agent_a"]["role"] == "leader"


def test_project_team_from_dict_partial():
    team = ProjectTeam.from_dict({"name": "x"})
    assert team.description == ""
    assert team.created_at > 0


# ----------------------------- ProjectTask -----------------------------


def test_project_task_defaults_and_roundtrip():
    task = ProjectTask(
        name="每日简报",
        workflow_id="canvas_abc123",
        schedule_config={"type": "cron", "cron": "0 9 * * *"},
    )
    assert task.task_id.startswith("task_")
    assert task.status == "active"
    assert task.schedule_config["type"] == "cron"

    data = task.to_dict()
    assert data["workflow_id"] == "canvas_abc123"
    restored = ProjectTask.from_dict(data)
    assert restored.name == "每日简报"
    assert restored.schedule_config["cron"] == "0 9 * * *"


def test_project_task_interval_schedule():
    task = ProjectTask(
        name="轮询",
        workflow_id="wf1",
        schedule_config={"type": "interval", "interval_seconds": 300},
    )
    assert ProjectTask.from_dict(task.to_dict()).schedule_config["interval_seconds"] == 300


# ----------------------------- Project 集成 -----------------------------


def test_project_has_teams_and_tasks_dicts():
    project = Project(name="P")
    assert project.teams == {}
    assert project.tasks == {}


def test_project_add_remove_team():
    project = Project(name="P")
    team = ProjectTeam(name="T")
    project.add_team(team)
    assert project.teams[team.team_id] is team
    assert project.get_team(team.team_id) is team
    assert project.remove_team(team.team_id) is True
    assert project.remove_team(team.team_id) is False


def test_project_add_remove_task():
    project = Project(name="P")
    task = ProjectTask(name="T", workflow_id="wf1", schedule_config={"type": "cron", "cron": "* * * * *"})
    project.add_task(task)
    assert project.tasks[task.task_id] is task
    assert project.get_task(task.task_id) is task
    assert project.remove_task(task.task_id) is True


def test_project_to_dict_includes_teams_tasks():
    import time

    project = Project(name="P")
    team = ProjectTeam(name="T")
    task = ProjectTask(
        name="K",
        workflow_id="wf1",
        schedule_config={"type": "interval", "interval_seconds": 60},
        next_run_at=time.time(),
    )
    project.add_team(team)
    project.add_task(task)

    data = project.to_dict()
    assert team.team_id in data["teams"]
    assert task.task_id in data["tasks"]

    restored = Project.from_dict(data)
    assert restored.teams[team.team_id].name == "T"
    assert restored.tasks[task.task_id].workflow_id == "wf1"
