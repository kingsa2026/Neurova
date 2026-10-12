"""
ConfigManager 通用 KV 面（unittest 形态那一份）

沿革两改：
- 2026-09-02 修复 A 类导入漂移：本文件原本测 KV 简单版（`core/config_manager.py`），导入却
  被漂移到分层版，7/9 通过纯属两个 API 恰好同名 —— 当时改指简单版。
- 2026-10-10 批 E：两份 KV 实现合并到分层版（`neurova.core.config.ConfigManager`），简单版
  退役，本文件随之改指。合并前逐格比过：本文件的 A 类语义（读写/默认值/删除/全等 get_all）
  与 B 类语义（显式 save → 新实例 load 往返）在分层版上等价成立，故原样保留断言。

先前 setup 里那句 `patch.object(Path, 'home', ...)` 已删：被测类的构造从不读 `Path.home()`
（`config.py:67` 只用显式 `config_path`），空设一个补丁只会让后来人以为有默认落点这回事。
"""

import tempfile
import unittest
from pathlib import Path

from neurova.core.config import ConfigManager


class TestConfigManager(unittest.TestCase):
    """ConfigManager 通用 KV 面"""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self._config_file = Path(self._temp_dir.name) / "config.json"

    def tearDown(self) -> None:
        self._temp_dir.cleanup()

    def test_get_set_config(self) -> None:
        manager = ConfigManager()
        manager.set("test_key", "test_value")
        self.assertEqual(manager.get("test_key"), "test_value")

    def test_get_default_value(self) -> None:
        manager = ConfigManager()
        self.assertEqual(manager.get("non_existent_key", "default_value"), "default_value")

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
        self.assertEqual(manager.get_all(), {"key1": "value1", "key2": "value2"})

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
