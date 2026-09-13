"""
AdminService 单元测试

2026-09-13 残留处理：原文件按已被替换的旧实现书写（config/event_bus 构造 +
UserModel/StartupManager mock + tar 备份 + int user_id——现行 AdminService 为
JSON 存储面 `AdminService(storage_dir)`，user_id=str、backup 为快照 JSON）。
验证意图逐条保留：目录初始化、增删改查、唯一性、备份/列表/过滤/恢复/删除、
统计、UserBackup 序列化往返。
"""

import unittest
import tempfile
from pathlib import Path

from neurova.admin.admin_service import AdminService, UserBackup


class TestAdminService(unittest.TestCase):
    """AdminService 测试类（现行 JSON 存储契约）"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp_dir.name)
        self.service = AdminService(storage_dir=str(self.data_dir / "admin"))

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _mk_user(self, username="testuser", email="test@example.com"):
        return self.service.create_user(username=username, email=email, password="pw123456")

    def test_init_creates_directories(self) -> None:
        self.assertTrue(self.service._backups_dir.exists())
        self.assertTrue((self.data_dir / "admin").exists())

    def test_create_user_success(self) -> None:
        result = self._mk_user()
        self.assertEqual(result["username"], "testuser")
        self.assertEqual(result["email"], "test@example.com")
        self.assertTrue(result["id"].startswith("usr_"))
        self.assertEqual(result["status"], "active")

    def test_create_user_duplicate_username(self) -> None:
        self._mk_user()
        with self.assertRaises(ValueError):
            self._mk_user(email="other@example.com")

    def test_create_user_duplicate_email(self) -> None:
        self._mk_user()
        with self.assertRaises(ValueError):
            self._mk_user(username="otheruser")

    def test_update_user(self) -> None:
        uid = self._mk_user()["id"]
        self.assertTrue(self.service.update_user(uid, email="new@example.com"))
        self.assertEqual(self.service.get_user(uid)["email"], "new@example.com")

    def test_update_user_conflicting_username_raises(self) -> None:
        u1 = self._mk_user("alice", "a@x.com")
        self._mk_user("bob", "b@x.com")
        with self.assertRaises(ValueError):
            self.service.update_user(u1["id"], username="bob")

    def test_update_user_not_found_returns_false(self) -> None:
        # 现行契约：不存在 → False（不 raise）
        self.assertFalse(self.service.update_user("usr_missing", username="x"))

    def test_delete_user(self) -> None:
        uid = self._mk_user()["id"]
        result = self.service.delete_user(uid)
        self.assertEqual(result["user_id"], uid)
        self.assertEqual(result["username"], "testuser")
        self.assertIsNone(self.service.get_user(uid))

    def test_delete_user_not_found(self) -> None:
        with self.assertRaises(ValueError):
            self.service.delete_user("usr_missing")

    def test_delete_user_removes_from_group(self) -> None:
        uid = self._mk_user()["id"]
        self.service.delete_user(uid)
        stats = self.service.get_system_stats()
        self.assertNotIn(uid, stats["group_stats"]["default"]["members"])

    def test_backup_user(self) -> None:
        uid = self._mk_user()["id"]
        backup = self.service.backup_user(uid, description="manual")
        self.assertIsInstance(backup, UserBackup)
        self.assertEqual(backup.user_id, uid)
        self.assertEqual(backup.description, "manual")
        self.assertGreater(backup.size_bytes, 0)
        self.assertTrue(Path(backup.backup_path).exists())

    def test_backup_user_not_found(self) -> None:
        with self.assertRaises(ValueError):
            self.service.backup_user("usr_missing")

    def test_list_backups(self) -> None:
        uid = self._mk_user()["id"]
        self.service.backup_user(uid)
        self.service.backup_user(uid)
        self.assertEqual(len(self.service.list_backups()), 2)

    def test_list_backups_filter_by_user(self) -> None:
        u1 = self._mk_user("user1", "u1@test.com")
        u2 = self._mk_user("user2", "u2@test.com")
        self.service.backup_user(u1["id"])
        self.service.backup_user(u2["id"])
        backups = self.service.list_backups(user_id=u1["id"])
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].user_id, u1["id"])

    def test_restore_user(self) -> None:
        uid = self._mk_user()["id"]
        backup = self.service.backup_user(uid)
        self.service.update_user(uid, email="changed@example.com")
        result = self.service.restore_user(backup.backup_id)
        self.assertEqual(result["user_id"], uid)
        self.assertTrue(result["restored"])
        # 快照回写：email 回到备份时点
        self.assertEqual(self.service.get_user(uid)["email"], "test@example.com")

    def test_restore_user_backup_not_found(self) -> None:
        with self.assertRaises(ValueError):
            self.service.restore_user("bk_nonexistent")

    def test_delete_backup(self) -> None:
        uid = self._mk_user()["id"]
        backup = self.service.backup_user(uid)
        self.assertTrue(self.service.delete_backup(backup.backup_id))
        self.assertEqual(len(self.service.list_backups()), 0)
        self.assertFalse(Path(backup.backup_path).exists())

    def test_delete_nonexistent_backup(self) -> None:
        self.assertFalse(self.service.delete_backup("bk_nonexistent"))

    def test_get_system_stats(self) -> None:
        for i in range(3):
            self._mk_user(f"u{i}", f"u{i}@x.com")
        stats = self.service.get_system_stats()
        self.assertEqual(stats["total_users"], 3)
        self.assertIn("total_backups", stats)
        self.assertIn("group_stats", stats)
        self.assertEqual(stats["group_stats"]["default"]["count"], 3)

    def test_persistence_roundtrip(self) -> None:
        """JSON 落盘持久：新实例读回同数据（现行存储层的存在意义）。"""
        uid = self._mk_user()["id"]
        second = AdminService(storage_dir=str(self.data_dir / "admin"))
        self.assertEqual(second.get_user(uid)["username"], "testuser")

    def test_user_backup_to_dict(self) -> None:
        import datetime

        backup = UserBackup(
            backup_id="backup_test123",
            user_id="usr_1",
            created_at=datetime.datetime(2024, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc),
            backup_path="/tmp/test.json",
            size_bytes=1024,
            description="d",
        )
        d = backup.to_dict()
        self.assertEqual(d["backup_id"], "backup_test123")
        self.assertEqual(d["user_id"], "usr_1")
        self.assertEqual(d["size_bytes"], 1024)

    def test_user_backup_from_dict(self) -> None:
        data = {
            "backup_id": "backup_test456",
            "user_id": "usr_2",
            "created_at": "2024-01-01T12:00:00+00:00",
            "backup_path": "/tmp/test2.json",
            "size_bytes": 2048,
            "description": "x",
            "metadata": {},
        }
        backup = UserBackup.from_dict(data)
        self.assertEqual(backup.backup_id, "backup_test456")
        self.assertEqual(backup.user_id, "usr_2")
        self.assertEqual(backup.size_bytes, 2048)


if __name__ == "__main__":
    unittest.main()
