
"""安全模块集成测试

测试安全相关模块（RBAC、数据脱敏、密码加密）的集成
"""

import unittest
import tempfile
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from neurova.core.event_bus import EventBus
from neurova.core.config import ConfigManager
from neurova.security.rbac import RBACManager, Role, Permission
from neurova.security.data_masking import DataMasking
from neurova.auth.password_hasher import PasswordHasher


class TestSecurityIntegration(unittest.TestCase):
    """安全模块集成测试"""

    def setUp(self):
        """设置测试环境"""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        
        self.event_bus = EventBus()
        self.config_manager = ConfigManager(str(self.temp_path / "config.json"))
        self.rbac_manager = RBACManager()
        self.data_masker = DataMasking()
        self.password_hasher = PasswordHasher()

    def tearDown(self):
        """清理测试环境"""
        self.temp_dir.cleanup()

    def test_full_user_authentication_flow(self):
        """测试完整的用户认证流程"""
        plain_password = "test_password_123"
        
        hashed_password = self.password_hasher.hash_password(plain_password)
        
        self.assertTrue(self.password_hasher.verify_password(plain_password, hashed_password))
        
        self.assertFalse(self.password_hasher.verify_password("wrong_password", hashed_password))

    def test_rbac_with_data_masking(self):
        """测试RBAC与数据脱敏的结合使用"""
        self.rbac_manager.add_role(Role("admin", "Admin"))
        self.rbac_manager.add_role(Role("user", "Regular User"))
        
        self.rbac_manager.add_permission(Permission("view_full_data", "View full unmasked data"))
        self.rbac_manager.add_permission(Permission("view_masked_data", "View masked data"))
        
        self.rbac_manager.assign_permission_to_role("admin", "view_full_data")
        self.rbac_manager.assign_permission_to_role("admin", "view_masked_data")
        self.rbac_manager.assign_permission_to_role("user", "view_masked_data")
        
        self.rbac_manager.assign_role_to_user("user1", "admin")
        self.rbac_manager.assign_role_to_user("user2", "user")
        
        sensitive_data = {
            "name": "张三",
            "phone": "13812345678",
            "email": "zhangsan@example.com",
            "id_card": "110101199001011234"
        }
        
        if self.rbac_manager.user_has_permission("user1", "view_full_data"):
            data_for_admin = sensitive_data
        else:
            data_for_admin = self.data_masker.mask_dict(sensitive_data)
        
        if self.rbac_manager.user_has_permission("user2", "view_full_data"):
            data_for_user = sensitive_data
        else:
            data_for_user = self.data_masker.mask_dict(sensitive_data)
        
        self.assertEqual(data_for_admin, sensitive_data)
        
        self.assertNotEqual(data_for_user, sensitive_data)
        self.assertTrue("*" in data_for_user["phone"])
        self.assertTrue("*" in data_for_user["id_card"])

    def test_security_events(self):
        """测试安全事件的触发"""
        security_events = []
        
        def on_security_event(event):
            security_events.append({
                "type": event.get("type"),
                "user": event.get("user")
            })
        
        self.event_bus.subscribe("security.login", on_security_event)
        self.event_bus.subscribe("security.access_denied", on_security_event)
        
        self.event_bus.emit("security.login", {"type": "login", "user": "user1", "success": True})
        
        self.event_bus.emit("security.access_denied", {"type": "access_denied", "user": "user2", "resource": "admin_panel"})
        
        self.assertEqual(len(security_events), 2)
        self.assertEqual(security_events[0]["type"], "login")
        self.assertEqual(security_events[1]["type"], "access_denied")

    def test_config_based_security_settings(self):
        """测试基于配置的安全设置"""
        self.config_manager.set("security.password.min_length", 8)
        self.config_manager.set("security.password.require_special", True)
        self.config_manager.set("security.masking.enabled", True)
        
        min_length = self.config_manager.get("security.password.min_length", 6)
        require_special = self.config_manager.get("security.password.require_special", False)
        masking_enabled = self.config_manager.get("security.masking.enabled", False)
        
        self.assertEqual(min_length, 8)
        self.assertTrue(require_special)
        self.assertTrue(masking_enabled)


if __name__ == "__main__":
    unittest.main()

