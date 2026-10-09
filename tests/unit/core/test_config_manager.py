"""
配置管理器测试（通用 KV 面 + 显式持久化 + env 装载）

被测对象自 2026-10-10 起是 `neurova.core.config.ConfigManager`（原 `core/config_manager.py`
那份 KV 简单版与本份分层版并存、两份都零生产消费者，按教义第 7 条合到分层那份）。
本文件只测**与分层无关**的那半区：键当字面量、默认值回落、删除返回真/假、save/load 显式往返、
`load_from_env` 剥前缀转小写。分层/validator/on_change 由 `test_config_schema.py`、
`test_config_unified.py` 承担，不在这里重复一遍（教义第 6 条：口径一处定义，判据也一处）。

摘掉的一格：`test_clear`。KV 简单版有 `clear()`，分层版没有，而 `clear()` 全仓零消费者
（生产与测试都只有那一条用例自己在调）——没有需求的 API 不并过来，也不再留判据；
若日后要"运行期整张清空"，先立需求再接线。
"""
import json

import pytest

from neurova.core.config import ConfigManager


class TestConfigManager:
    """测试配置管理器的通用 KV 面"""

    @pytest.fixture
    def config_manager(self):
        return ConfigManager()

    def test_init(self, config_manager):
        assert config_manager is not None
        assert config_manager.get_all() == {}

    def test_set_and_get(self, config_manager):
        config_manager.set("test.key", "test_value")
        assert config_manager.get("test.key") == "test_value"

    def test_get_nonexistent(self, config_manager):
        assert config_manager.get("nonexistent", default="default") == "default"

    def test_get_with_default_none(self, config_manager):
        assert config_manager.get("nonexistent") is None

    def test_delete(self, config_manager):
        config_manager.set("test.key", "value")
        assert config_manager.delete("test.key") is True
        assert config_manager.has("test.key") is False

    def test_delete_nonexistent(self, config_manager):
        assert config_manager.delete("nonexistent") is False

    def test_has(self, config_manager):
        config_manager.set("test.key", "value")
        assert config_manager.has("test.key") is True
        assert config_manager.has("nonexistent") is False

    def test_get_all(self, config_manager):
        config_manager.set("key1", "value1")
        config_manager.set("key2", "value2")
        all_configs = config_manager.get_all()
        assert len(all_configs) == 2
        assert all_configs["key1"] == "value1"
        assert all_configs["key2"] == "value2"

    def test_save_to_file(self, config_manager, tmp_path):
        config_manager.set("key1", "value1")
        config_manager.set("key2", 123)
        path = tmp_path / "out.json"
        config_manager.save(str(path))
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["key1"] == "value1"
        assert data["key2"] == 123

    def test_load_from_file(self, config_manager, tmp_path):
        path = tmp_path / "in.json"
        path.write_text(json.dumps({"key1": "value1", "key2": 123}), encoding="utf-8")
        config_manager.load(str(path))
        assert config_manager.get("key1") == "value1"
        assert config_manager.get("key2") == 123

    def test_load_from_env_strips_prefix_and_lowercases(self, config_manager, monkeypatch):
        monkeypatch.setenv("NEUVA_TEST_KEY", "env_value")
        count = config_manager.load_from_env("NEUVA_")
        assert count >= 1
        assert config_manager.get("test_key") == "env_value"

    def test_dotted_key_is_literal_not_a_path(self, config_manager):
        """点号键当一个整键存 —— 简单版与分层版在这一点上语义相同，必须钉住别漂移"""
        config_manager.set("server.port", 8080)
        assert config_manager.get("server.port") == 8080
        assert config_manager.get("server") is None

    def test_complex_value(self, config_manager):
        complex_value = {"list": [1, 2, 3], "nested": {"key": "value"}}
        config_manager.set("complex", complex_value)
        assert config_manager.get("complex")["list"] == [1, 2, 3]

    def test_none_value_is_stored_not_treated_as_missing(self, config_manager):
        """存 None 与"缺键"在 get 上同值，但在 has 上必须分得开——分层版能分开，本格钉住它"""
        config_manager.set("null_key", None)
        assert config_manager.get("null_key") is None
        assert config_manager.has("null_key") is True
        assert config_manager.has("never_set") is False

    def test_boolean_value(self, config_manager):
        config_manager.set("enabled", True)
        assert config_manager.get("enabled") is True

    def test_update_existing(self, config_manager):
        config_manager.set("key", "value1")
        config_manager.set("key", "value2")
        assert config_manager.get("key") == "value2"

    def test_init_with_config_path(self, tmp_path):
        path = tmp_path / "init.json"
        path.write_text(json.dumps({"init_key": "init_value"}), encoding="utf-8")
        manager = ConfigManager(config_path=str(path))
        manager.load()
        assert manager.get("init_key") == "init_value"
