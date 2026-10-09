"""
ConfigManager 通用 KV 面判据（get/set/has/delete/get_all + 显式 save/load）

被测对象自 2026-10-10 起是 `neurova.core.config.ConfigManager`：仓内原有两份通用 KV 配置器
（`core/config.py:60` 分层版 354 行、`core/config_manager.py:21` 简单版 118 行），两份**都零生产
消费者**，属教义 §2 点名的"注册无消费者的模块"。按第 7 条比后合到超集那一份，简单版连同其
"保存后再读同一实例内存"那类假持久化断言一并退掉——本文件就是合并后仍在咬的那批格子。

分层版与简单版的一处真实差异必须写清楚：分层版的 `set` 带 `level`，`get` 回最高优先级，
`get_all()` 默认扁平。本文件全部按默认层级调用，不测分层语义（分层由
`tests/unit/core/test_config_schema.py` / `test_config_unified.py` 承担）。
"""
import json

import pytest

from neurova.core.config import ConfigManager


class TestConfigManagerBasic:
    """通用 KV 面：读写、默认值、存在性、删除、全量读"""

    @pytest.fixture
    def config_manager(self, tmp_path):
        return ConfigManager(config_path=str(tmp_path / "test_config.json"))

    def test_set_and_get(self, config_manager):
        config_manager.set("test_key", "test_value")
        assert config_manager.get("test_key") == "test_value"

    def test_get_with_default(self, config_manager):
        assert config_manager.get("nonexistent") is None
        assert config_manager.get("nonexistent", default="default") == "default"

    def test_has(self, config_manager):
        assert config_manager.has("nonexistent") is False
        config_manager.set("exists", "value")
        assert config_manager.has("exists") is True

    def test_delete(self, config_manager):
        config_manager.set("to_delete", "value")
        assert config_manager.has("to_delete") is True
        assert config_manager.delete("to_delete") is True
        assert config_manager.has("to_delete") is False

    def test_delete_nonexistent(self, config_manager):
        assert config_manager.delete("nonexistent") is False

    def test_get_all(self, config_manager):
        config_manager.set("key1", "value1")
        config_manager.set("key2", "value2")
        config_manager.set("key3", "value3")
        all_configs = config_manager.get_all()
        assert len(all_configs) == 3
        assert all_configs["key1"] == "value1"

    def test_save_then_readBackInAFreshInstance(self, config_manager, tmp_path):
        """往返必须换一只新对象去 load —— 读回同一实例的内存不叫持久化。

        这一格原先就写着 `save()` 后断 `get(...)`，测的仍是内存里的原值，恒真。
        """
        config_manager.set("save_key1", "value1")
        config_manager.set("save_key2", 42)
        config_manager.save()

        written = json.loads((tmp_path / "test_config.json").read_text(encoding="utf-8"))
        assert written == {"save_key1": "value1", "save_key2": 42}

        reloaded = ConfigManager(config_path=str(tmp_path / "test_config.json"))
        reloaded.load()
        assert reloaded.get("save_key1") == "value1"
        assert reloaded.get("save_key2") == 42

    def test_load_nonexistent_keeps_current_state(self, config_manager):
        """加载不存在的文件：不崩、不清空、不写入"""
        config_manager.set("keep", "me")
        config_manager.load("/nonexistent/path.json")
        assert config_manager.get("keep") == "me"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
