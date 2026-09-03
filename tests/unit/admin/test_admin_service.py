"""
AdminService 单元测试
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

try:
    from neurova.admin.admin_service import AdminService, UserBackup
    HAS_ADMIN_SERVICE = True
except ImportError:
    HAS_ADMIN_SERVICE = False


@unittest.skipIf(not HAS_ADMIN_SERVICE, "AdminService not available")
class TestAdminService(unittest.TestCase):
    """AdminService 测试类"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)

        self.mock_user_model = MagicMock()
        self.mock_group_manager = MagicMock()
        self.mock_skill_manager = MagicMock()
        self.mock_collab_manager = MagicMock()

        self.mock_sm = MagicMock()
        self.mock_sm.get_module.side_effect = lambda name: {
            "UserModel": self.mock_user_model,
            "UserGroupManager": self.mock_group_manager,
            "SkillPoolManager": self.mock_skill_manager,
            "CollaborationIsolationManager": self.mock_collab_manager,
        }.get(name)

        self.startup_patcher = patch(
            'neurova.core.startup_manager.get_startup_manager',
            return_value=self.mock_sm
        )
        self.startup_patcher.start()

        self.service = AdminService(
            config={"data_dir": str(self.data_dir)},
            event_bus=None,
        )
        self.service._on_init()

    def tearDown(self) -> None:
        self.startup_patcher.stop()
        self.temp_dir.cleanup()

    def test_init_creates_directories(self) -> None:
        self.assertTrue(self.service.backup_dir.exists())

    def test_create_user_success(self) -> None:
        self.mock_user_model.get_user_by_username.return_value = None
        self.mock_user_model.get_user_by_email.return_value = None
        self.mock_user_model.create_user.return_value = {
            "id": 1, "username": "testuser", "email": "test@example.com"
        }

        result = self.service.create_user(
            username="testuser",
            email="test@example.com",
            password="password123",
        )
        self.assertEqual(result["username"], "testuser")
        self.mock_user_model.create_user.assert_called_once()

    def test_create_user_duplicate_username(self) -> None:
        self.mock_user_model.get_user_by_username.return_value = {"id": 1, "username": "testuser"}

        with self.assertRaises(ValueError):
            self.service.create_user(
                username="testuser",
                email="test@example.com",
                password="password123",
            )

    def test_create_user_duplicate_email(self) -> None:
        self.mock_user_model.get_user_by_username.return_value = None
        self.mock_user_model.get_user_by_email.return_value = {"id": 1, "email": "test@example.com"}

        with self.assertRaises(ValueError):
            self.service.create_user(
                username="testuser",
                email="test@example.com",
                password="password123",
            )

    def test_update_user(self) -> None:
        self.mock_user_model.get_user_by_id.return_value = {
            "id": 1, "username": "oldname", "email": "old@example.com"
        }
        self.mock_user_model.get_user_by_username.return_value = None
        self.mock_user_model.get_user_by_email.return_value = None
        self.mock_user_model.update_user.return_value = True

        result = self.service.update_user(1, username="newname", email="new@example.com")
        self.assertTrue(result)
        self.mock_user_model.update_user.assert_called_once()

    def test_update_user_not_found(self) -> None:
        self.mock_user_model.get_user_by_id.return_value = None

        with self.assertRaises(ValueError):
            self.service.update_user(999, username="newname")

    def test_delete_user(self) -> None:
        self.mock_user_model.get_user_by_id.return_value = {
            "id": 1, "username": "testuser"
        }
        self.mock_user_model.delete_user.return_value = True
        self.mock_collab_manager.admin_delete_user_projects.return_value = 0
        self.mock_skill_manager.admin_delete_user_skills.return_value = 0

        result = self.service.delete_user(1, backup_before_delete=False)
        self.assertEqual(result["user_id"], 1)
        self.assertEqual(result["username"], "testuser")
        self.assertTrue(self.mock_user_model.delete_user.called)

    def test_delete_user_not_found(self) -> None:
        self.mock_user_model.get_user_by_id.return_value = None

        with self.assertRaises(ValueError):
            self.service.delete_user(999)

    @patch('tarfile.open')
    @patch.object(Path, 'stat')
    def test_backup_user(self, mock_stat, mock_tarfile_open) -> None:
        self.mock_user_model.get_user_by_id.return_value = {
            "id": 1, "username": "testuser", "email": "test@example.com"
        }

        mock_tar = MagicMock()
        mock_tarfile_open.return_value.__enter__.return_value = mock_tar
        mock_stat.return_value.st_size = 1024

        backup = self.service.backup_user(1)
        self.assertIsInstance(backup, UserBackup)
        self.assertEqual(backup.user_id, 1)
        self.assertEqual(backup.username, "testuser")

    def test_backup_user_not_found(self) -> None:
        self.mock_user_model.get_user_by_id.return_value = None

        with self.assertRaises(ValueError):
            self.service.backup_user(999)

    @patch('tarfile.open')
    @patch.object(Path, 'stat')
    def test_list_backups(self, mock_stat, mock_tarfile_open) -> None:
        self.mock_user_model.get_user_by_id.return_value = {
            "id": 1, "username": "testuser", "email": "test@example.com"
        }

        mock_tar = MagicMock()
        mock_tarfile_open.return_value.__enter__.return_value = mock_tar
        mock_stat.return_value.st_size = 1024

        self.service.backup_user(1)
        self.service.backup_user(1)

        backups = self.service.list_backups()
        self.assertEqual(len(backups), 2)

    @patch('tarfile.open')
    @patch.object(Path, 'stat')
    def test_list_backups_filter_by_user(self, mock_stat, mock_tarfile_open) -> None:
        self.mock_user_model.get_user_by_id.side_effect = [
            {"id": 1, "username": "user1", "email": "u1@test.com"},
            {"id": 2, "username": "user2", "email": "u2@test.com"},
        ]

        mock_tar = MagicMock()
        mock_tarfile_open.return_value.__enter__.return_value = mock_tar
        mock_stat.return_value.st_size = 1024

        self.service.backup_user(1)
        self.service.backup_user(2)

        backups = self.service.list_backups(user_id=1)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].user_id, 1)

    @patch('tarfile.open')
    @patch.object(Path, 'stat')
    def test_restore_user(self, mock_stat, mock_tarfile_open) -> None:
        self.mock_user_model.get_user_by_id.return_value = {
            "id": 1, "username": "testuser", "email": "test@example.com"
        }

        mock_tar = MagicMock()
        mock_tarfile_open.return_value.__enter__.return_value = mock_tar
        mock_stat.return_value.st_size = 1024

        backup = self.service.backup_user(1)
        backup_id = backup.backup_id

        backup.backup_file.parent.mkdir(parents=True, exist_ok=True)
        backup.backup_file.touch()

        result = self.service.restore_user(backup_id)
        self.assertEqual(result["user_id"], 1)
        self.assertEqual(result["username"], "testuser")

    def test_restore_user_backup_not_found(self) -> None:
        with self.assertRaises(ValueError):
            self.service.restore_user("nonexistent_backup")

    @patch('tarfile.open')
    @patch.object(Path, 'stat')
    def test_delete_backup(self, mock_stat, mock_tarfile_open) -> None:
        self.mock_user_model.get_user_by_id.return_value = {
            "id": 1, "username": "testuser", "email": "test@example.com"
        }

        mock_tar = MagicMock()
        mock_tarfile_open.return_value.__enter__.return_value = mock_tar
        mock_stat.return_value.st_size = 1024

        backup = self.service.backup_user(1)
        backup_id = backup.backup_id

        self.assertTrue(self.service.delete_backup(backup_id))
        backups = self.service.list_backups()
        self.assertEqual(len(backups), 0)

    def test_delete_nonexistent_backup(self) -> None:
        self.assertFalse(self.service.delete_backup("nonexistent"))

    def test_get_system_stats(self) -> None:
        self.mock_user_model.count_users.return_value = 10
        self.mock_group_manager.list_groups.return_value = []

        stats = self.service.get_system_stats()
        self.assertEqual(stats["total_users"], 10)
        self.assertIn("total_agents", stats)
        self.assertIn("total_projects", stats)
        self.assertIn("total_skills", stats)

    def test_user_backup_to_dict(self) -> None:
        from datetime import datetime
        backup = UserBackup(
            backup_id="backup_test123",
            user_id=1,
            username="testuser",
            backup_at=datetime(2024, 1, 1, 12, 0, 0),
            backup_file=Path("/tmp/test.tar.gz"),
            backup_size=1024,
            summary={"agents": 1, "projects": 2},
        )
        d = backup.to_dict()
        self.assertEqual(d["backup_id"], "backup_test123")
        self.assertEqual(d["user_id"], 1)
        self.assertEqual(d["username"], "testuser")

    def test_user_backup_from_dict(self) -> None:
        data = {
            "backup_id": "backup_test456",
            "user_id": 2,
            "username": "user2",
            "backup_at": "2024-01-01T12:00:00",
            "backup_file": "/tmp/test2.tar.gz",
            "backup_size": 2048,
            "summary": {},
        }
        backup = UserBackup.from_dict(data)
        self.assertEqual(backup.backup_id, "backup_test456")
        self.assertEqual(backup.user_id, 2)


if __name__ == "__main__":
    unittest.main()