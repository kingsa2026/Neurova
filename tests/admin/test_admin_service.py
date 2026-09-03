"""Tests for neurova/admin/admin_service.py - core scenarios."""
import datetime
import pytest


class TestAdminService:
    def test_init_and_create_user(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        user = svc.create_user(username="alice", email="a@x.com", password="pw")
        assert user is not None
        assert user.get("username") == "alice"
        assert user.get("email") == "a@x.com"
        assert isinstance(user.get("id"), str) and user.get("id")

    def test_create_user_duplicate_username_raises(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        svc.create_user(username="alice", email="a@x.com")
        with pytest.raises(ValueError):
            svc.create_user(username="alice", email="b@x.com")

    def test_update_and_delete_user(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        user = svc.create_user(username="bob", email="b@x.com")
        uid = user["id"]
        assert svc.update_user(uid, username="bobby", email="bobby@x.com") is True
        result = svc.delete_user(uid)
        assert result.get("user_id") == uid
        assert result.get("deleted") is True

    def test_delete_user_not_found_raises(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        with pytest.raises(ValueError):
            svc.delete_user("u_nonexistent")

    def test_backup_list_and_delete_backup(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        u1 = svc.create_user(username="u1", email="u1@x.com")
        u2 = svc.create_user(username="u2", email="u2@x.com")
        b1 = svc.backup_user(u1["id"], description="first")
        svc.backup_user(u2["id"])
        all_backups = svc.list_backups()
        u1_backups = svc.list_backups(user_id=u1["id"])
        assert len(all_backups) == 2
        assert len(u1_backups) == 1
        assert u1_backups[0].user_id == u1["id"]
        assert u1_backups[0].description == "first"
        assert svc.delete_backup(b1.backup_id) is True
        assert svc.delete_backup(b1.backup_id) is False

    def test_restore_user_and_not_found_raises(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        user = svc.create_user(username="frank", email="f@x.com")
        uid = user["id"]
        backup = svc.backup_user(uid)
        result = svc.restore_user(backup.backup_id)
        assert result.get("user_id") == uid
        assert result.get("restored") is True
        with pytest.raises(ValueError):
            svc.restore_user("bk_nonexistent")

    def test_get_system_stats_returns_dict(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        svc = AdminService(str(tmp_path / "admin"))
        svc.create_user(username="g1", email="g1@x.com")
        svc.create_user(username="g2", email="g2@x.com")
        stats = svc.get_system_stats()
        assert isinstance(stats, dict)
        assert stats.get("total_users") == 2
        assert "group_stats" in stats


class TestUserBackupDataclass:
    def test_to_from_dict_roundtrip(self):
        from neurova.admin.admin_service import UserBackup
        b = UserBackup(
            backup_id="bk_1",
            user_id="u_1",
            created_at=datetime.datetime(2024, 1, 1, 12, 0, 0),
            backup_path="/tmp/bk.json",
            size_bytes=1024,
            description="test",
            metadata={"k": "v"},
        )
        d = b.to_dict()
        assert d["backup_id"] == "bk_1"
        assert d["user_id"] == "u_1"
        b2 = UserBackup.from_dict(d)
        assert b2.backup_id == "bk_1"
        assert b2.user_id == "u_1"
        assert b2.metadata == {"k": "v"}

    def test_metadata_defaults_to_empty(self):
        from neurova.admin.admin_service import UserBackup
        b = UserBackup(
            backup_id="bk_2",
            user_id="u_2",
            created_at=datetime.datetime(2024, 1, 1),
            backup_path="/tmp/bk2.json",
            size_bytes=0,
        )
        assert b.metadata == {}
