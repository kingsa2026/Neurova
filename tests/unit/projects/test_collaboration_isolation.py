"""collaboration_isolation 模型与管理器测试（对齐当前 API 契约）

契约要点（与实现同步维护）：
- Project.owner_id；members 为 Dict[user_id, ProjectMember]
- ProjectMember.invited_by（非 added_by）；joined_at 为 float 时间戳
- 权限判定收敛到 MemberRole + ProjectMember.can_edit()/can_view()
- Manager(data_dir)；__init__ 内部完成目录初始化与项目加载
- 文件/工作流注册制存储在 project.files / project.workflows（不再扫描目录）
"""

import sys
from pathlib import Path

import pytest

# 添加项目路径
project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from neurova.collaboration.collaboration_isolation import (
    CollaborationIsolationManager,
    Project,
    ProjectFile,
    ProjectStatus,
    ProjectTask,
    ProjectTeam,
    ProjectVisibility,
    ProjectWorkflow,
    MemberRole,
    ProjectMember,
)


# ----------------------------- ProjectMember -----------------------------


class TestProjectMember:
    def test_create_member(self):
        member = ProjectMember(user_id="user-1", role=MemberRole.OWNER, invited_by="user-1")

        assert member.user_id == "user-1"
        assert member.role == MemberRole.OWNER
        assert member.invited_by == "user-1"
        assert member.joined_at > 0  # float 时间戳

    def test_to_dict(self):
        member = ProjectMember(user_id="user-1", role=MemberRole.EDITOR, invited_by="user-0")

        data = member.to_dict()

        assert data["user_id"] == "user-1"
        assert data["role"] == "editor"
        assert data["invited_by"] == "user-0"
        assert "permissions" in data

    def test_from_dict(self):
        member = ProjectMember.from_dict(
            {
                "user_id": "user-1",
                "role": "viewer",
                "joined_at": 1700000000.0,
                "invited_by": "user-2",
            }
        )

        assert member.user_id == "user-1"
        assert member.role == MemberRole.VIEWER
        assert member.invited_by == "user-2"
        assert member.joined_at == 1700000000.0

    def test_role_capabilities(self):
        owner = ProjectMember(user_id="a", role=MemberRole.OWNER)
        admin = ProjectMember(user_id="b", role=MemberRole.ADMIN)
        editor = ProjectMember(user_id="c", role=MemberRole.EDITOR)
        viewer = ProjectMember(user_id="d", role=MemberRole.VIEWER)
        guest = ProjectMember(user_id="e", role=MemberRole.GUEST)

        assert owner.can_edit() and admin.can_edit() and editor.can_edit()
        assert not viewer.can_edit() and not guest.can_edit()
        # owner/admin 拥有一切权限；其他角色看显式 permissions
        assert owner.has_permission("anything") and admin.has_permission("anything")
        assert not viewer.has_permission("anything")
        custom = ProjectMember(user_id="f", role=MemberRole.VIEWER, permissions={"export": True})
        assert custom.has_permission("export") and not custom.has_permission("delete")
        # guest 不可查看，其余可查看
        assert all(m.can_view() for m in (owner, admin, editor, viewer))
        assert not guest.can_view()


# ----------------------------- Project -----------------------------


class TestProject:
    def _make_project(self) -> Project:
        project = Project(project_id="proj-1", name="测试项目", description="测试描述", owner_id="user-1")
        return project

    def test_create_project_defaults(self):
        project = self._make_project()

        assert project.project_id == "proj-1"
        assert project.owner_id == "user-1"
        assert project.status == ProjectStatus.ACTIVE
        assert project.visibility == ProjectVisibility.PRIVATE

    def test_member_management(self):
        project = self._make_project()

        # 手动加入所有者成员
        project.add_member("user-1", MemberRole.OWNER)
        assert project.is_member("user-1")
        assert not project.is_member("user-2")
        assert project.get_member("user-1").role == MemberRole.OWNER

        project.add_member("user-2", MemberRole.EDITOR, invited_by="user-1")
        assert project.get_member("user-2").invited_by == "user-1"

        # 所有者角色不可变更、所有者不可被移除
        assert project.update_member_role("user-1", MemberRole.EDITOR) is False
        assert project.remove_member("user-1") is False
        # 普通成员可变更/移除
        assert project.update_member_role("user-2", MemberRole.VIEWER) is True
        assert project.remove_member("user-2") is True
        assert not project.is_member("user-2")

    def test_to_from_dict_round_trip(self):
        project = self._make_project()
        project.add_member("user-1", MemberRole.OWNER)
        project.add_member("user-2", MemberRole.EDITOR, invited_by="user-1")
        project.teams["team-1"] = ProjectTeam(team_id="team-1", name="调研组", members={"agent_a": {"agent_name": "A", "role": "leader"}})
        project.tasks["task-1"] = ProjectTask(
            task_id="task-1",
            name="每日简报",
            workflow_id="canvas-1",
            schedule_config={"type": "cron", "cron": "0 9 * * *"},
        )

        data = project.to_dict()
        assert data["owner_id"] == "user-1"
        assert set(data["members"]) == {"user-1", "user-2"}
        assert data["teams"]["team-1"]["name"] == "调研组"
        assert data["tasks"]["task-1"]["workflow_id"] == "canvas-1"

        restored = Project.from_dict(data)
        assert restored.owner_id == "user-1"
        assert restored.get_member("user-2").role == MemberRole.EDITOR
        assert restored.get_team("team-1").members["agent_a"]["role"] == "leader"
        assert restored.get_task("task-1").schedule_config["cron"] == "0 9 * * *"

    def test_lifecycle_transitions(self):
        project = self._make_project()

        project.archive()
        assert project.status == ProjectStatus.ARCHIVED and project.archived_at is not None

        project.restore()
        assert project.status == ProjectStatus.ACTIVE and project.archived_at is None

        project.delete()
        assert project.status == ProjectStatus.DELETED and project.deleted_at is not None

    def test_team_task_file_workflow_accessors(self):
        project = self._make_project()

        team = ProjectTeam(team_id="t1", name="T")
        task = ProjectTask(task_id="k1", name="K", workflow_id="w1")
        file_obj = ProjectFile(file_id="f1", name="a.txt")
        workflow = ProjectWorkflow(workflow_id="wf1", name="W")

        project.add_team(team)
        project.add_task(task)
        project.add_file(file_obj)
        project.add_workflow(workflow)

        assert project.get_team("t1") is team
        assert project.get_task("k1") is task
        assert project.get_file("f1") is file_obj
        assert project.get_workflow("wf1") is workflow

        assert project.remove_team("t1") and project.get_team("t1") is None
        assert project.remove_task("k1") and project.get_task("k1") is None
        assert project.remove_file("f1") and project.get_file("f1") is None
        assert project.remove_workflow("wf1") and project.get_workflow("wf1") is None
        # 重复移除返回 False
        assert project.remove_team("t1") is False


# ----------------------------- Manager -----------------------------


class TestCollaborationIsolationManager:
    @pytest.fixture
    def manager(self, tmp_path):
        """__init__ 内部完成目录初始化与项目加载"""
        return CollaborationIsolationManager(data_dir=str(tmp_path))

    def test_init_dirs(self, manager, tmp_path):
        for sub in ("projects", "files", "workflows", "backups"):
            assert (tmp_path / sub).exists()

    def test_create_project(self, manager, tmp_path):
        project = manager.create_project(name="测试项目", description="测试描述", owner_id="user-1")

        assert project is not None
        assert project.owner_id == "user-1"
        assert project.status == ProjectStatus.ACTIVE
        # 所有者自动成为成员
        assert project.get_member("user-1").role == MemberRole.OWNER
        # 落盘持久化
        assert (tmp_path / "projects" / f"{project.project_id}.json").exists()

    def test_create_project_persists_across_restart(self, manager, tmp_path):
        project = manager.create_project(name="重启存活", owner_id="user-1")

        # 新实例从同一目录加载
        reloaded = CollaborationIsolationManager(data_dir=str(tmp_path))
        restored = reloaded.get_project(project.project_id, "user-1")
        assert restored is not None
        assert restored.name == "重启存活"

    def test_get_project(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        # 所有者可以查看
        assert manager.get_project(project.project_id, "user-1") is not None
        # 非成员不能查看（private 可见性）
        assert manager.get_project(project.project_id, "user-2") is None

    def test_get_project_not_found(self, manager):
        assert manager.get_project("non-existent", "user-1") is None

    def test_list_user_projects(self, manager):
        manager.create_project(name="项目1", owner_id="user-1")
        manager.create_project(name="项目2", owner_id="user-1")

        projects = manager.list_user_projects("user-1")
        assert len(projects) == 2

    def test_list_user_projects_with_status_filter(self, manager):
        project1 = manager.create_project(name="项目1", owner_id="user-1")

        manager.delete_project(project1.project_id, "user-1")

        # 默认不含已删除项目
        assert len(manager.list_user_projects("user-1")) == 0
        # 显式包含已删除
        assert len(manager.list_user_projects("user-1", include_deleted=True)) == 1

    def test_update_project(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        result = manager.update_project(
            project_id=project.project_id,
            user_id="user-1",
            updates={"name": "更新后的项目", "tags": ["updated"]},
        )

        assert result is not None
        assert result.name == "更新后的项目"
        assert "updated" in result.tags

    def test_update_project_no_permission(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        # 非成员尝试更新
        result = manager.update_project(
            project_id=project.project_id,
            user_id="user-2",
            updates={"name": "恶意更新"},
        )
        assert result is None

    def test_delete_project(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        assert manager.delete_project(project.project_id, "user-1") is True

        # 软删除：仍在存储中但状态为 DELETED，list/get 默认不可见
        assert manager.get_project(project.project_id, "user-1").status == ProjectStatus.DELETED
        assert len(manager.list_user_projects("user-1")) == 0
        # 数据文件仍在磁盘（可恢复）
        assert (manager.data_dir / "projects" / f"{project.project_id}.json").exists()

    def test_delete_project_no_permission(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        assert manager.delete_project(project.project_id, "user-2") is False
        assert manager.delete_project(project.project_id, "user-1") is True

    def test_add_project_member(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        result = manager.add_project_member(
            project_id=project.project_id,
            inviter_id="user-1",
            user_id="user-2",
            role=MemberRole.EDITOR,
        )
        assert result is True

        updated = manager.get_project(project.project_id, "user-1")
        assert updated.is_member("user-2")
        assert updated.get_member("user-2").role == MemberRole.EDITOR
        # 成员关系建立后 user-2 也能访问
        assert manager.get_project(project.project_id, "user-2") is not None

    def test_add_project_member_no_permission(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")

        # 非成员尝试添加
        assert (
            manager.add_project_member(
                project_id=project.project_id,
                inviter_id="user-2",
                user_id="user-3",
                role=MemberRole.EDITOR,
            )
            is False
        )

    def test_add_project_member_duplicate(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")
        manager.add_project_member(project.project_id, "user-1", "user-2", MemberRole.EDITOR)

        # 重复添加失败
        assert manager.add_project_member(project.project_id, "user-1", "user-2", MemberRole.VIEWER) is False

    def test_remove_project_member(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")
        manager.add_project_member(project.project_id, "user-1", "user-2", MemberRole.EDITOR)

        assert manager.remove_project_member(project.project_id, "user-1", "user-2") is True
        assert not manager.get_project(project.project_id, "user-1").is_member("user-2")

    def test_remove_owner(self, manager):
        """移除所有者（应该失败）"""
        project = manager.create_project(name="测试项目", owner_id="user-1")

        assert manager.remove_project_member(project.project_id, "user-1", "user-1") is False

    def test_update_member_role(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")
        manager.add_project_member(project.project_id, "user-1", "user-2", MemberRole.VIEWER)

        assert manager.update_member_role(project.project_id, "user-1", "user-2", MemberRole.EDITOR) is True
        assert manager.get_project(project.project_id, "user-1").get_member("user-2").role == MemberRole.EDITOR

    def test_list_project_files(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")
        manager.add_project_file(
            project.project_id,
            "user-1",
            ProjectFile(file_id="f1", name="file1.txt"),
        )
        manager.add_project_file(
            project.project_id,
            "user-1",
            ProjectFile(file_id="f2", name="file2.txt"),
        )

        files = manager.list_project_files(project.project_id, "user-1")
        assert len(files) == 2

    def test_list_project_files_no_permission(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")
        manager.add_project_file(project.project_id, "user-1", ProjectFile(file_id="f1", name="a.txt"))

        assert manager.list_project_files(project.project_id, "user-2") == []

    def test_list_project_workflows(self, manager):
        project = manager.create_project(name="测试项目", owner_id="user-1")
        manager.add_project_workflow(project.project_id, "user-1", ProjectWorkflow(workflow_id="wf1"))
        manager.add_project_workflow(project.project_id, "user-1", ProjectWorkflow(workflow_id="wf2"))

        workflows = manager.list_project_workflows(project.project_id, "user-1")
        assert len(workflows) == 2

    def test_admin_list_all_projects(self, manager):
        manager.create_project(name="项目1", owner_id="user-1")
        manager.create_project(name="项目2", owner_id="user-2")

        assert len(manager.admin_list_all_projects("admin")) == 2

    def test_admin_delete_user_projects(self, manager):
        manager.create_project(name="项目1", owner_id="user-1")
        manager.create_project(name="项目2", owner_id="user-1")
        manager.create_project(name="项目3", owner_id="user-2")

        deleted_count = manager.admin_delete_user_projects("admin", "user-1")

        assert deleted_count == 2
        assert len(manager.list_user_projects("user-1")) == 0
        # 其他用户项目不受影响
        assert len(manager.list_user_projects("user-2")) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
