"""
ProjectManager 单元测试
"""

import unittest
import tempfile
import shutil

try:
    from neurova.projects.project_manager import ProjectManager
    HAS_PROJECT_MANAGER = True
except ImportError:
    HAS_PROJECT_MANAGER = False


@unittest.skipIf(not HAS_PROJECT_MANAGER, "ProjectManager not available")
class TestProjectManager(unittest.TestCase):
    """ProjectManager 测试类"""

    def setUp(self) -> None:
        self.temp_dir = tempfile.mkdtemp()
        self.manager = ProjectManager(self.temp_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_project(self) -> None:
        project_id = self.manager.create_project(
            name="Test Project",
            description="Test Description",
            owner_id="user123",
        )
        self.assertIsInstance(project_id, str)
        self.assertTrue(len(project_id) > 0)

    def test_get_project(self) -> None:
        project_id = self.manager.create_project(
            name="Get Test",
            description="Get Test Desc",
            owner_id="user123",
        )
        retrieved = self.manager.get_project(project_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["name"], "Get Test")

    def test_get_nonexistent_project(self) -> None:
        project = self.manager.get_project("nonexistent_id")
        self.assertIsNone(project)

    def test_update_project(self) -> None:
        project_id = self.manager.create_project(
            name="Original Name",
            description="Original Desc",
        )
        result = self.manager.update_project(project_id, name="Updated Name")
        self.assertTrue(result)
        retrieved = self.manager.get_project(project_id)
        self.assertEqual(retrieved["name"], "Updated Name")

    def test_delete_project(self) -> None:
        project_id = self.manager.create_project(
            name="To Delete",
            description="Delete Test",
        )
        self.assertTrue(self.manager.delete_project(project_id))
        self.assertIsNone(self.manager.get_project(project_id))

    def test_list_projects(self) -> None:
        self.manager.create_project(name="Project 1", owner_id="user123")
        self.manager.create_project(name="Project 2", owner_id="user123")
        self.manager.create_project(name="Project 3", owner_id="user456")

        all_projects = self.manager.list_projects()
        self.assertEqual(len(all_projects), 3)

        user_projects = self.manager.list_projects(owner_id="user123")
        self.assertEqual(len(user_projects), 2)

    def test_project_persistence(self) -> None:
        project_id = self.manager.create_project(
            name="Persistent",
            description="Desc",
            owner_id="user123",
        )
        manager2 = ProjectManager(self.temp_dir)
        retrieved = manager2.get_project(project_id)
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved["name"], "Persistent")

    def test_project_stats(self) -> None:
        project_id = self.manager.create_project(
            name="Stats Test",
            description="Desc",
        )
        stats = self.manager.get_project_stats(project_id)
        self.assertEqual(stats["name"], "Stats Test")
        self.assertIn("status", stats)

    def test_delete_nonexistent_project(self) -> None:
        self.assertFalse(self.manager.delete_project("nonexistent"))


if __name__ == "__main__":
    unittest.main()
