"""
项目管理集成测试
测试ProjectManager和相关模块的集成
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

try:
    from neurova.projects.project_manager import ProjectManager
    from neurova.core.config import ConfigManager
    from neurova.core.state_manager import StateManager
    from neurova.core.event_bus import EventBus
    HAS_REQUIRED_MODULES = True
except ImportError:
    HAS_REQUIRED_MODULES = False


@unittest.skipIf(not HAS_REQUIRED_MODULES, "Required modules not available")
class TestProjectManagementIntegration(unittest.TestCase):
    """项目管理集成测试"""

    def setUp(self):
        """测试前初始化"""
        self.temp_dir = tempfile.mkdtemp()
        self.event_bus = EventBus()
        self.state_manager = StateManager(event_bus=self.event_bus)
        self.project_manager = ProjectManager(Path(self.temp_dir))

    def tearDown(self):
        """测试后清理"""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_project_crud_with_state_sync(self):
        """测试项目CRUD操作与状态管理器的集成"""
        # 1. 创建项目
        project = self.project_manager.create_project(
            name="Integration Test",
            description="Integration test project",
            owner_id="test_user"
        )
        self.assertIsNotNone(project)

        # 2. 检查状态更新到状态管理器
        self.state_manager.set(
            f"project:{project.id}",
            {
                "id": project.id,
                "name": project.name,
                "status": "active"
            }
        )

        # 3. 更新项目
        updated_project = self.project_manager.update_project(
            project.id,
            name="Updated Integration Test",
            description="Updated description"
        )
        self.assertEqual(updated_project.name, "Updated Integration Test")

        # 4. 检查状态同步
        state_data = self.state_manager.get(f"project:{project.id}")
        self.assertEqual(state_data["name"], "Updated Integration Test")

        # 5. 删除项目
        self.assertTrue(self.project_manager.delete_project(project.id))
        self.assertIsNone(self.project_manager.get_project(project.id))

        # 6. 清理状态
        self.state_manager.delete(f"project:{project.id}")
        self.assertIsNone(self.state_manager.get(f"project:{project.id}"))

    def test_project_with_config(self):
        """测试项目与配置管理的集成"""
        # 1. 创建配置项目
        project = self.project_manager.create_project(
            name="Config Project",
            description="Test project with config",
            owner_id="user_456"
        )

        # 2. 存储项目配置
        config_manager = ConfigManager()
        config_manager.set(
            f"project:{project.id}:setting1",
            "value1"
        )
        config_manager.set(
            f"project:{project.id}:setting2",
            "value2"
        )

        # 3. 获取配置验证
        self.assertEqual(
            config_manager.get(f"project:{project.id}:setting1"),
            "value1"
        )
        self.assertEqual(
            config_manager.get(f"project:{project.id}:setting2"),
            "value2"
        )

    def test_project_with_team(self):
        """测试项目与团队管理的集成"""
        # 创建项目
        project = self.project_manager.create_project(
            name="Team Project",
            description="Team collaboration project",
            owner_id="owner_789"
        )

        # 添加团队成员
        self.project_manager.add_project_member(
            project.id,
            "member1",
            "developer"
        )
        self.project_manager.add_project_member(
            project.id,
            "member2",
            "reviewer"
        )

        # 检查成员
        members = self.project_manager.get_project_members(project.id)
        self.assertEqual(len(members), 2)

        # 移除成员
        self.project_manager.remove_project_member(project.id, "member1")
        members = self.project_manager.get_project_members(project.id)
        self.assertEqual(len(members), 1)


if __name__ == "__main__":
    unittest.main()
