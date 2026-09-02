"""
ConfigManager 单元测试（2026-09-02 修复 A 类导入漂移）。

本文件测试目标原为 KV 简单版 ConfigManager（neurova/core/config_manager.py，
支持单例+JSON 文件持久化），但导入被漂移到 neurova.core.config（统一分层
配置管理器，非单例、set 需显式 save 才落盘）——7/9 用例通过纯属两个 API
恰好同名。修复：指向正确被测对象 + 按真实持久化契约（save/load 显式调用）
重写 persistence 用例。
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from neurova.core.config_manager import ConfigManager


class TestConfigManager(unittest.TestCase):
    """ConfigManager（KV 简单版）测试类"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._temp_path = Path(self._temp_dir.name)
        self._home_patcher = patch.object(Path, 'home', return_value=self._temp_path)
        self._home_patcher.start()
        # KV 版无 _instance 单例机制（__init__ 每次新建）；持久化用例改走
        # save/load 显式文件往返，不再依赖单例重置
        self._config_file = self._temp_path / "config.json"

    def tearDown(self) -> None:
        self._home_patcher.stop()
        self._temp_dir.cleanup()

    def test_get_set_config(self) -> None:
        manager = ConfigManager()
        manager.set("test_key", "test_value")
        value = manager.get("test_key")
        self.assertEqual(value, "test_value")

    def test_get_default_value(self) -> None:
        manager = ConfigManager()
        value = manager.get("non_existent_key", "default_value")
        self.assertEqual(value, "default_value")

    def test_delete_config(self) -> None:
        manager = ConfigManager()
        manager.set("key_to_delete", "value")
        self.assertEqual(manager.get("key_to_delete"), "value")
        manager.delete("key_to_delete")
        self.assertIsNone(manager.get("key_to_delete"))

    def test_get_all(self) -> None:
        manager = ConfigManager()
        manager.set("key1", "value1")
        manager.set("key2", "value2")
        all_config = manager.get_all()
        self.assertEqual(all_config, {"key1": "value1", "key2": "value2"})

    def test_has_config(self) -> None:
        manager = ConfigManager()
        manager.set("existing_key", "value")
        self.assertTrue(manager.has("existing_key"))
        self.assertFalse(manager.has("non_existing_key"))

    def test_complex_data_types(self) -> None:
        manager = ConfigManager()
        test_dict = {"nested": {"key": "value"}}
        test_list = [1, 2, 3, "string"]
        manager.set("dict_config", test_dict)
        manager.set("list_config", test_list)
        self.assertEqual(manager.get("dict_config"), test_dict)
        self.assertEqual(manager.get("list_config"), test_list)

    def test_file_persistence(self) -> None:
        """set → save 落盘；新实例 load 后可读（显式文件往返契约）"""
        manager1 = ConfigManager(config_path=str(self._config_file))
        manager1.set("persistent_key", "persistent_value")
        manager1.save()

        manager2 = ConfigManager(config_path=str(self._config_file))
        manager2.load()
        self.assertEqual(manager2.get("persistent_key"), "persistent_value")


if __name__ == "__main__":
    unittest.main()
