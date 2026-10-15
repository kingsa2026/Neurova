
"""安全模块集成测试

测试安全相关模块（RBAC、数据脱敏、密码加密）的集成。

这档长期在红却没人看见：它**不在** `scripts/ci/protected_tests.txt` 里，CI 的受保护子集按清单
逐文件跑，于是"调用早已不存在的 API"这种腐烂只在本机显式跑到时才暴露（台账按用户裁定取
(甲)＝改判据到现役 API，不在生产里为测试补别名壳）。逐格调用面对现役实装的
差异见各格 docstring；本批同时把它登进受保护子集，让"再漂一次"变成会红的判据。
"""

import unittest
import tempfile
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from neurova.core.event_bus import EventBus
from neurova.core.config import ConfigManager
from neurova.security.rbac import RBACManager, Permission
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
        # db_path 显式给到本轮临时目录：本档也能经 `unittest.main()` 直跑（那时没有 conftest
        # 注入的临时数据根），不隔离就会在真落点上留一份测试库。
        self.rbacDbPath = str(self.temp_path / "rbac.db")
        # `RBACManager` 是进程级单例（`rbac.py:186 __new__` 配 `_initialized` 短路）：不复位就
        # 会拿到**上一个用例那一份已随它的临时目录一起删掉**的库，实测读数是
        # `sqlite3.OperationalError: no such table: roles`。复位单例位是仓内既有配方
        # （`tests/unit/security/test_rbac.py:22`、`test_rbac_comprehensive.py:228` 那两处），
        # 生产侧没有 reset 钩子，这一处不是绕过装配点造假状态。
        RBACManager._instance = None
        self.rbac_manager = RBACManager(self.rbacDbPath)
        self.data_masker = DataMasking()
        self.password_hasher = PasswordHasher()

    def tearDown(self):
        """清理测试环境"""
        RBACManager._instance = None    # 交还单例位，别把已删的库留给下一个档
        # RBAC 走的是池化短连接（`rbac.py:207 _get_conn` 把 close 重定向成"归还池"），
        # 池按路径持有真句柄；`tests/conftest.py:134` 那道 `close_all_pools()` 在 pytest
        # fixture 收尾阶段跑，**晚于** unittest 的 tearDown，所以先删目录就会撞
        # WinError 32。按路径关自己那一池，不调全局（那会把同进程别人的池一起摘掉）。
        from neurova.core.connection_pool import get_connection_pool

        get_connection_pool(self.rbacDbPath).close_all()
        self.temp_dir.cleanup()

    def test_full_user_authentication_flow(self):
        """测试完整的用户认证流程"""
        plain_password = "test_password_123"

        hashed_password = self.password_hasher.hash_password(plain_password)

        self.assertTrue(self.password_hasher.verify_password(plain_password, hashed_password))

        self.assertFalse(self.password_hasher.verify_password("wrong_password", hashed_password))

    def test_rbac_with_data_masking(self):
        """测试RBAC与数据脱敏的结合使用：有无该项权限，决定拿到明文还是脱敏值。

        现役模型（`neurova/security/rbac.py`）与这档当年写的不同两处，改判按现役形状走：
        ① 权限**不是运行时可注册的实体**——`Permission` 是一张枚举目录，角色自己携带权限名集合
           （`create_role(name, description, permissions: Set[str])`），所以没有 `add_permission`
           与 `assign_permission_to_role` 这两步；权限名一律取自那份枚举，不在测试里另造词。
        ② 角色 id 由 `name.lower()` 推导，而构造时已 `_init_system_roles()` 落了 5 个系统角色，
           其中就有 `admin`/`user`——撞名时 `create_role` 返回 None（不覆盖）。故用不与系统角色
           相碰的名字，并把"创建成功"本身断下来：否则这一步静默失败，后面读到的
           是系统角色的权限集合，整档就变成在测别的东西。
        """
        canReadUser = self.rbac_manager.create_role(
            "user-data-reader", "读取用户明文信息",
            permissions={Permission.USER_READ.value})
        maskedOnly = self.rbac_manager.create_role("masked-observer", "只能看脱敏视图")
        self.assertIsNotNone(canReadUser, "角色没建成 ⇒ 后面读的是别的角色的权限")
        self.assertIsNotNone(maskedOnly)

        self.assertTrue(self.rbac_manager.assign_role("user1", canReadUser.id))
        self.assertTrue(self.rbac_manager.assign_role("user2", maskedOnly.id))

        sensitive_data = {
            "name": "张三",
            "phone": "13812345678",
            "email": "zhangsan@example.com",
            "id_card": "110101199001011234"
        }

        def view(uid: str):
            if self.rbac_manager.has_permission(uid, Permission.USER_READ.value):
                return sensitive_data
            return self.data_masker.mask_dict(sensitive_data)

        data_for_admin = view("user1")
        data_for_user = view("user2")

        self.assertEqual(data_for_admin, sensitive_data)

        self.assertNotEqual(data_for_user, sensitive_data)
        self.assertTrue("*" in data_for_user["phone"])
        self.assertTrue("*" in data_for_user["id_card"])

    def test_security_events(self):
        """测试安全事件的触发：订阅者按订阅顺序收到自己那两发，载荷完整。

        现役总线（`neurova/core/event_bus.py:174 publish`）递的是 **`Event` 数据类**
        （`.name` / `.data` / `.source`），不是旧档假设的 dict；且 handler 抛异常会被总线
        `logger.error` 吞掉——所以这里按 `Event` 的字段取，别用 `.get()`（用了就是恒不命中，
        两格断言会被"异常被吞"凑成一条看着像红的假信号，归因全错）。
        """
        security_events = []

        def on_security_event(event):
            security_events.append({
                "type": event.data.get("type"),
                "user": event.data.get("user"),
            })

        self.event_bus.subscribe("security.login", on_security_event)
        self.event_bus.subscribe("security.access_denied", on_security_event)

        self.event_bus.publish("security.login", {"type": "login", "user": "user1", "success": True})

        self.event_bus.publish(
            "security.access_denied",
            {"type": "access_denied", "user": "user2", "resource": "admin_panel"})

        self.assertEqual(len(security_events), 2)
        self.assertEqual(security_events[0]["type"], "login")
        self.assertEqual(security_events[1]["type"], "access_denied")
        self.assertEqual([e["user"] for e in security_events], ["user1", "user2"])

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

