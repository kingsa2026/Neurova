"""ProjectTeam / ProjectTask 模型测试

原版本守卫不存在的 neurova.projects.team_manager（收集 0 项）。
团队/任务的 API 行为由 tests/unit/api/test_projects_teams_tasks_api.py 覆盖，
这里聚焦数据模型本身：序列化往返、缺省值、ID 唯一性（同毫秒不碰撞）。
"""

import sys
from pathlib import Path

import pytest

project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.collaboration.collaboration_isolation import Project, ProjectTask, ProjectTeam


class TestProjectTeam:
    def test_defaults(self):
        team = ProjectTeam()
        assert team.team_id.startswith("team_")
        assert team.name == ""
        assert team.members == {}
        assert team.created_at > 0

    def test_round_trip(self):
        team = ProjectTeam(
            team_id="team-1",
            name="调研组",
            description="收集资料",
            members={"agent_a": {"agent_name": "研究员", "role": "leader"}},
        )

        data = team.to_dict()
        assert data["team_id"] == "team-1"
        assert data["members"]["agent_a"]["role"] == "leader"

        restored = ProjectTeam.from_dict(data)
        assert restored.name == "调研组"
        assert restored.members == team.members

    def test_from_dict_tolerates_missing_fields(self):
        restored = ProjectTeam.from_dict({"name": "仅名称"})
        assert restored.name == "仅名称"
        assert restored.team_id == ""
        assert restored.members == {}

    def test_team_ids_unique_same_millisecond(self):
        """回归：旧实现 team_{ms}_{id(object()):x} 因地址复用会碰撞"""
        teams = [ProjectTeam() for _ in range(50)]
        ids = {t.team_id for t in teams}
        assert len(ids) == 50


class TestProjectTask:
    def test_defaults(self):
        task = ProjectTask()
        assert task.task_id.startswith("task_")
        assert task.status == "active"
        assert task.schedule_config == {}
        assert task.next_run_at is None and task.last_run_at is None

    def test_round_trip(self):
        task = ProjectTask(
            task_id="task-1",
            name="每日简报",
            workflow_id="canvas-1",
            schedule_config={"type": "cron", "cron": "0 9 * * *", "end_date": "2026-09-01T09:31:00"},
            next_run_at=1780000000.0,
            last_run_at=1779000000.0,
            status="paused",
            metadata={"project_id": "p1"},
        )

        data = task.to_dict()
        assert data["workflow_id"] == "canvas-1"
        assert data["schedule_config"]["end_date"] == "2026-09-01T09:31:00"
        assert data["status"] == "paused"

        restored = ProjectTask.from_dict(data)
        assert restored.name == "每日简报"
        assert restored.schedule_config == task.schedule_config
        assert restored.status == "paused"
        assert restored.next_run_at == 1780000000.0
        assert restored.metadata == {"project_id": "p1"}

    def test_task_ids_unique_same_millisecond(self):
        tasks = [ProjectTask() for _ in range(50)]
        ids = {t.task_id for t in tasks}
        assert len(ids) == 50


class TestProjectAggregates:
    def test_project_holds_multiple_teams_and_tasks(self):
        project = Project(project_id="p1", owner_id="u1")
        for i in range(5):
            project.add_team(ProjectTeam(name=f"T{i}"))
            project.add_task(ProjectTask(name=f"K{i}", workflow_id=f"wf{i}"))

        assert len(project.teams) == 5
        assert len(project.tasks) == 5

    def test_project_ids_unique_same_millisecond(self):
        """回归：旧实现 project_{ms} 同毫秒创建互相覆盖（manager 存储丢项目）"""
        projects = [Project() for _ in range(50)]
        ids = {p.project_id for p in projects}
        assert len(ids) == 50
