"""
RBAC (Role-Based Access Control) 单元测试
"""

import unittest
import threading
import json
from datetime import datetime
from unittest.mock import patch, MagicMock

try:
    from neurova.security.rbac import RBACManager, Role, Permission
    HAS_RBAC = True
except ImportError:
    HAS_RBAC = False


@unittest.skipIf(not HAS_RBAC, "RBACManager not available")
class TestRBACManager(unittest.TestCase):
    """RBACManager 测试类 — 使用 mock 数据库避免真实文件 I/O"""

    def setUp(self) -> None:
        RBACManager._instance = None
        RBACManager._lock = threading.Lock()

        self.mock_conn = MagicMock()
        self.mock_cursor = MagicMock()
        self.mock_cursor.fetchone.return_value = None
        self.mock_conn.cursor.return_value = self.mock_cursor

        self._patcher_conn = patch.object(RBACManager, '_get_conn', return_value=self.mock_conn)
        self._patcher_conn.start()
        self.addCleanup(self._patcher_conn.stop)

        self._patcher_dir = patch.object(RBACManager, '_ensure_db_dir')
        self._patcher_dir.start()
        self.addCleanup(self._patcher_dir.stop)

        self._patcher_db = patch.object(RBACManager, '_init_db')
        self._patcher_db.start()
        self.addCleanup(self._patcher_db.stop)

        self.rbac = RBACManager()
        self.rbac._cache_loaded = True

    def _add_role_to_cache(self, role_id, name, description, permissions):
        from datetime import datetime
        role = Role(
            id=role_id, name=name, description=description,
            permissions=permissions, is_system=False,
            created_at=datetime.now(), updated_at=datetime.now(),
        )
        self.rbac._roles_cache[role_id] = role

    def _assign_role_in_cache(self, user_id, role_id):
        if user_id not in self.rbac._user_roles_cache:
            self.rbac._user_roles_cache[user_id] = set()
        self.rbac._user_roles_cache[user_id].add(role_id)

    def test_create_role(self) -> None:
        self.mock_cursor.lastrowid = 1
        role = self.rbac.create_role("editor", "Content Editor", {"content.create", "content.read"})
        self.assertIsNotNone(role)
        self.assertEqual(role.name, "editor")
        self.assertEqual(role.description, "Content Editor")
        self.assertEqual(role.permissions, {"content.create", "content.read"})

    def test_get_role(self) -> None:
        self._add_role_to_cache("admin", "admin", "Administrator", {"user.manage"})
        role = self.rbac.get_role("admin")
        self.assertIsNotNone(role)
        self.assertEqual(role.name, "admin")
        self.assertIsNone(self.rbac.get_role("nonexistent"))

    def test_get_role_by_name(self) -> None:
        self._add_role_to_cache("editor", "editor", "Editor", {"content.read"})
        role = self.rbac.get_role_by_name("editor")
        self.assertIsNotNone(role)
        self.assertEqual(role.name, "editor")

    def test_list_roles(self) -> None:
        self._add_role_to_cache("admin", "admin", "Admin", {"*"})
        self._add_role_to_cache("editor", "editor", "Editor", {"content.read"})
        roles = self.rbac.list_roles()
        self.assertEqual(len(roles), 2)
        names = {r.name for r in roles}
        self.assertEqual(names, {"admin", "editor"})

    def test_delete_role(self) -> None:
        self._add_role_to_cache("temp", "temp", "Temp", {"temp.action"})
        self.mock_cursor.rowcount = 1
        result = self.rbac.delete_role("temp")
        self.assertTrue(result)
        self.assertIsNone(self.rbac.get_role("temp"))

    def test_delete_nonexistent_role(self) -> None:
        result = self.rbac.delete_role("nonexistent")
        self.assertFalse(result)

    def test_has_permission(self) -> None:
        self._add_role_to_cache("editor", "editor", "Editor", {"content.create", "content.read"})
        self._assign_role_in_cache("user123", "editor")
        self.assertTrue(self.rbac.has_permission("user123", "content.create"))
        self.assertTrue(self.rbac.has_permission("user123", "content.read"))
        self.assertFalse(self.rbac.has_permission("user123", "content.delete"))

    def test_has_any_permission(self) -> None:
        self._add_role_to_cache("editor", "editor", "Editor", {"content.read"})
        self._assign_role_in_cache("user123", "editor")
        self.assertTrue(self.rbac.has_any_permission("user123", ["content.read", "content.delete"]))
        self.assertFalse(self.rbac.has_any_permission("user123", ["content.delete"]))

    def test_has_all_permissions(self) -> None:
        self._add_role_to_cache("editor", "editor", "Editor", {"content.create", "content.read"})
        self._assign_role_in_cache("user123", "editor")
        self.assertTrue(self.rbac.has_all_permissions("user123", ["content.create", "content.read"]))
        self.assertFalse(self.rbac.has_all_permissions("user123", ["content.create", "content.delete"]))

    def test_get_user_permissions(self) -> None:
        self._add_role_to_cache("editor", "editor", "Editor", {"content.create", "content.read"})
        self._add_role_to_cache("reviewer", "reviewer", "Reviewer", {"content.approve"})
        self._assign_role_in_cache("user123", "editor")
        self._assign_role_in_cache("user123", "reviewer")
        perms = self.rbac.get_user_permissions("user123")
        self.assertEqual(perms, {"content.create", "content.read", "content.approve"})

    def test_assign_role(self) -> None:
        self._add_role_to_cache("editor", "editor", "Editor", {"content.read"})
        result = self.rbac.assign_role("user123", "editor", "admin_user")
        self.assertTrue(result)

    def test_assign_nonexistent_role(self) -> None:
        result = self.rbac.assign_role("user123", "nonexistent", "admin_user")
        self.assertFalse(result)

    def test_revoke_role(self) -> None:
        self.mock_cursor.rowcount = 1
        result = self.rbac.revoke_role("user123", "editor")
        self.assertTrue(result)

    def test_revoke_nonexistent_role(self) -> None:
        self.mock_cursor.rowcount = 0
        result = self.rbac.revoke_role("user123", "nonexistent")
        self.assertFalse(result)

    def test_get_user_roles(self) -> None:
        self._add_role_to_cache("admin", "admin", "Admin", {"*"})
        self._add_role_to_cache("editor", "editor", "Editor", {"content.read"})
        self._assign_role_in_cache("user123", "admin")
        self._assign_role_in_cache("user123", "editor")
        roles = self.rbac.get_user_roles("user123")
        self.assertEqual(len(roles), 2)
        self.assertIsInstance(roles[0], Role)
        self.assertIsInstance(roles[1], Role)

    def test_get_user_roles_empty(self) -> None:
        roles = self.rbac.get_user_roles("unknown_user")
        self.assertEqual(roles, [])

    def test_get_user_permissions_empty(self) -> None:
        perms = self.rbac.get_user_permissions("unknown_user")
        self.assertEqual(perms, set())

    def test_update_role(self) -> None:
        self._add_role_to_cache("editor", "editor", "Old Desc", {"old.perm"})
        now_str = datetime.now().isoformat()
        mock_row = {
            "id": "editor", "name": "editor",
            "description": "Old Desc",
            "permissions": json.dumps(["new.perm"]),
            "is_system": 0,
            "created_at": now_str,
            "updated_at": now_str,
        }
        self.mock_cursor.fetchone.return_value = mock_row
        updated = self.rbac.update_role("editor", permissions={"new.perm"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated.permissions, {"new.perm"})

    def test_update_nonexistent_role(self) -> None:
        result = self.rbac.update_role("nonexistent", permissions={"p"})
        self.assertIsNone(result)

    def test_get_all_permissions(self) -> None:
        perms = self.rbac.get_all_permissions()
        self.assertIsInstance(perms, list)
        self.assertGreater(len(perms), 0)
        for p in perms:
            self.assertIn("id", p)
            self.assertIn("name", p)

    def test_create_permission_request(self) -> None:
        self.mock_cursor.lastrowid = 42
        request_id = self.rbac.create_permission_request(
            requester_id="user1",
            target_user_id="user2",
            action="assign_role",
            reason="Need access",
            role_id="editor",
        )
        self.assertEqual(request_id, 42)


if __name__ == "__main__":
    unittest.main()