"""Tests for collaboration/collaboration_isolation.py"""
import json
import time

import pytest

from neurova.collaboration.collaboration_isolation import (
    CollaborationIsolationManager,
    MemberRole,
    Project,
    ProjectFile,
    ProjectMember,
    ProjectStatus,
    ProjectVisibility,
    ProjectWorkflow,
    get_collaboration_manager,
    reset_collaboration_manager,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_collaboration_manager()
    yield
    reset_collaboration_manager()


@pytest.fixture
def mgr(tmp_path):
    return CollaborationIsolationManager(data_dir=str(tmp_path / "collab"))


class TestProjectDataclass:
    def test_create_project_minimal(self):
        p = Project(name="proj1", owner_id="u1")
        assert p.name == "proj1"
        assert p.owner_id == "u1"
        assert p.status == ProjectStatus.ACTIVE
        assert p.visibility == ProjectVisibility.PRIVATE
        assert isinstance(p.project_id, str)

    def test_to_dict_roundtrip(self):
        p = Project(name="p1", description="desc", owner_id="u1", tags=["a"])
        p.add_member("u1", MemberRole.OWNER)
        p.add_member("u2", MemberRole.EDITOR)
        d = p.to_dict()
        p2 = Project.from_dict(d)
        assert p2.name == "p1"
        assert p2.description == "desc"
        assert p2.tags == ["a"]
        assert len(p2.members) == 2
        assert p2.members["u2"].role == MemberRole.EDITOR
        assert p2.members["u1"].role == MemberRole.OWNER

    def test_from_dict_loads_members_and_files(self):
        p = Project(name="p1", owner_id="u1")
        p.add_member("u1", MemberRole.OWNER)
        p.add_file(ProjectFile(name="f1.txt", path="f1.txt"))
        d = p.to_dict()
        p2 = Project.from_dict(d)
        assert len(p2.members) == 1
        assert len(p2.files) == 1
        assert list(p2.files.values())[0].name == "f1.txt"


class TestProjectMember:
    def test_owner_has_all_permissions(self):
        m = ProjectMember(user_id="u1", role=MemberRole.OWNER)
        assert m.has_permission("delete") is True
        assert m.can_edit() is True
        assert m.can_view() is True

    def test_viewer_cannot_edit(self):
        m = ProjectMember(user_id="u1", role=MemberRole.VIEWER)
        assert m.can_edit() is False
        assert m.can_view() is True

    def test_guest_cannot_view(self):
        m = ProjectMember(user_id="u1", role=MemberRole.GUEST)
        assert m.can_view() is False

    def test_custom_permission(self):
        m = ProjectMember(user_id="u1", role=MemberRole.VIEWER, permissions={"deploy": True})
        assert m.has_permission("deploy") is True
        assert m.has_permission("admin") is False

    def test_member_to_dict_roundtrip(self):
        m = ProjectMember(user_id="u1", role=MemberRole.EDITOR, invited_by="u0")
        d = m.to_dict()
        m2 = ProjectMember.from_dict(d)
        assert m2.user_id == "u1"
        assert m2.role == MemberRole.EDITOR
        assert m2.invited_by == "u0"


class TestManagerInit:
    def test_init_creates_dirs(self, tmp_path):
        d = tmp_path / "new_collab"
        CollaborationIsolationManager(data_dir=str(d))
        assert (d / "projects").is_dir()
        assert (d / "files").is_dir()
        assert (d / "workflows").is_dir()
        assert (d / "backups").is_dir()

    def test_init_empty_projects(self, mgr):
        assert len(mgr._projects) == 0
        assert len(mgr._user_projects) == 0


class TestCreateProject:
    def test_create_and_get(self, mgr):
        p = mgr.create_project(name="Test", owner_id="u1")
        assert p is not None
        assert p.name == "Test"
        assert p.owner_id == "u1"
        assert p.project_id in mgr._projects
        fetched = mgr.get_project(p.project_id)
        assert fetched is not None
        assert fetched.name == "Test"

    def test_create_adds_owner_to_index(self, mgr):
        p = mgr.create_project(name="X", owner_id="u1")
        assert p.project_id in mgr._user_projects["u1"]

    def test_create_adds_owner_as_member(self, mgr):
        p = mgr.create_project(name="X", owner_id="u1")
        assert p.is_member("u1")
        assert p.members["u1"].role == MemberRole.OWNER

    def test_get_nonexistent(self, mgr):
        assert mgr.get_project("no-such-id") is None

    def test_list_user_projects_single(self, mgr):
        mgr.create_project(name="p1", owner_id="u1")
        u1_projects = mgr.list_user_projects("u1")
        assert len(u1_projects) == 1
        assert u1_projects[0].name == "p1"

    def test_list_user_projects_empty(self, mgr):
        assert mgr.list_user_projects("nobody") == []

    def test_list_projects(self, mgr):
        mgr.create_project(name="p1", owner_id="u1")
        time.sleep(0.01)
        mgr.create_project(name="p2", owner_id="u2")
        all_p = mgr.list_projects()
        assert len(all_p) == 2


class TestProjectACL:
    def test_add_member(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        result = mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.EDITOR)
        assert result is True
        fetched = mgr.get_project(p.project_id)
        assert fetched.is_member("u2")
        assert fetched.members["u2"].role == MemberRole.EDITOR

    def test_add_member_denied_for_viewer(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.VIEWER)
        result = mgr.add_project_member(p.project_id, inviter_id="u2", user_id="u3")
        assert result is False

    def test_remove_member(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2")
        result = mgr.remove_project_member(p.project_id, remover_id="u1", user_id="u2")
        assert result is True
        assert not mgr.get_project(p.project_id).is_member("u2")

    def test_cannot_remove_owner(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        result = mgr.remove_project_member(p.project_id, remover_id="u1", user_id="u1")
        assert result is False

    def test_cannot_remove_self(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.EDITOR)
        result = mgr.remove_project_member(p.project_id, remover_id="u2", user_id="u2")
        assert result is False

    def test_access_control_non_member(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        fetched = mgr.get_project(p.project_id, user_id="stranger")
        assert fetched is None

    def test_access_control_public(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1", visibility=ProjectVisibility.PUBLIC)
        fetched = mgr.get_project(p.project_id, user_id="stranger")
        assert fetched is not None

    def test_update_member_role(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.VIEWER)
        result = mgr.update_member_role(p.project_id, updater_id="u1", user_id="u2", role=MemberRole.ADMIN)
        assert result is True
        assert mgr.get_project(p.project_id).members["u2"].role == MemberRole.ADMIN

    def test_update_role_denied_for_non_owner(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.ADMIN)
        result = mgr.update_member_role(p.project_id, updater_id="u2", user_id="u1", role=MemberRole.VIEWER)
        assert result is False


class TestProjectUpdateDelete:
    def test_update_project(self, mgr):
        p = mgr.create_project(name="Old", owner_id="u1")
        updated = mgr.update_project(p.project_id, user_id="u1", updates={"name": "New"})
        assert updated.name == "New"

    def test_update_denied_for_viewer(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.VIEWER)
        result = mgr.update_project(p.project_id, user_id="u2", updates={"name": "X"})
        assert result is None

    def test_soft_delete(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        result = mgr.delete_project(p.project_id, user_id="u1")
        assert result is True
        fetched = mgr.get_project(p.project_id)
        assert fetched.status == ProjectStatus.DELETED

    def test_delete_denied_for_non_owner(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.ADMIN)
        result = mgr.delete_project(p.project_id, user_id="u2")
        assert result is False

    def test_hard_delete(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        result = mgr.hard_delete_project(p.project_id, user_id="u1")
        assert result is True
        assert p.project_id not in mgr._projects

    def test_list_excludes_deleted(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.delete_project(p.project_id, user_id="u1")
        projects = mgr.list_user_projects("u1")
        assert len(projects) == 0


class TestFileAndWorkflow:
    def test_add_and_list_files(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        f = ProjectFile(name="doc.txt", path="doc.txt", file_type="file")
        result = mgr.add_project_file(p.project_id, user_id="u1", file=f)
        assert result is True
        files = mgr.list_project_files(p.project_id)
        assert len(files) == 1
        assert files[0].name == "doc.txt"

    def test_add_file_denied_for_viewer(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        mgr.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.VIEWER)
        f = ProjectFile(name="x.txt", path="x.txt")
        result = mgr.add_project_file(p.project_id, user_id="u2", file=f)
        assert result is False

    def test_add_and_list_workflows(self, mgr):
        p = mgr.create_project(name="P", owner_id="u1")
        w = ProjectWorkflow(name="deploy", description="deploy workflow")
        result = mgr.add_project_workflow(p.project_id, user_id="u1", workflow=w)
        assert result is True
        wfs = mgr.list_project_workflows(p.project_id)
        assert len(wfs) == 1
        assert wfs[0].name == "deploy"

    def test_workflow_to_dict_roundtrip(self):
        w = ProjectWorkflow(name="w1", description="desc", is_active=False, version=3)
        d = w.to_dict()
        w2 = ProjectWorkflow.from_dict(d)
        assert w2.name == "w1"
        assert w2.is_active is False
        assert w2.version == 3

    def test_file_to_dict_roundtrip(self):
        f = ProjectFile(name="f1", path="a/b", file_type="file", size_bytes=1024, mime_type="text/plain")
        d = f.to_dict()
        f2 = ProjectFile.from_dict(d)
        assert f2.name == "f1"
        assert f2.size_bytes == 1024
        assert f2.mime_type == "text/plain"


class TestPersistence:
    def test_projects_persist_to_disk(self, tmp_path):
        d = tmp_path / "persist"
        mgr1 = CollaborationIsolationManager(data_dir=str(d))
        p = mgr1.create_project(name="PersistMe", owner_id="u1")
        pid = p.project_id

        mgr2 = CollaborationIsolationManager(data_dir=str(d))
        loaded = mgr2.get_project(pid)
        assert loaded is not None
        assert loaded.name == "PersistMe"
        assert loaded.owner_id == "u1"
        assert loaded.is_member("u1")

    def test_project_file_on_disk(self, tmp_path):
        d = tmp_path / "disk"
        mgr = CollaborationIsolationManager(data_dir=str(d))
        p = mgr.create_project(name="P", owner_id="u1")
        project_file = d / "projects" / f"{p.project_id}.json"
        assert project_file.exists()
        data = json.loads(project_file.read_text(encoding="utf-8"))
        assert data["name"] == "P"
        assert data["owner_id"] == "u1"

    def test_persisted_member_role(self, tmp_path):
        d = tmp_path / "persist2"
        mgr1 = CollaborationIsolationManager(data_dir=str(d))
        p = mgr1.create_project(name="P", owner_id="u1")
        mgr1.add_project_member(p.project_id, inviter_id="u1", user_id="u2", role=MemberRole.EDITOR)

        mgr2 = CollaborationIsolationManager(data_dir=str(d))
        loaded = mgr2.get_project(p.project_id)
        assert loaded.is_member("u2")
        assert loaded.members["u2"].role == MemberRole.EDITOR
