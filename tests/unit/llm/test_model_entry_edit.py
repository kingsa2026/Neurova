"""
TDD Red:模型条目编辑（rename_model_entry）

需求:内置/发现的模型条目允许用户编辑模型 ID 与显示名称;改 ID 须联动
迁移 models 列表、model_metadata 键、default_model;仅改名须写 metadata。
当前实现(provider_manager 无此方法)下全部失败。
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

import pytest

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig


@pytest.fixture
def manager():
    mgr = LLMProviderManager.__new__(LLMProviderManager)
    mgr._providers = {
        "sensetime": ProviderConfig(
            id="sensetime",
            name="商汤科技",
            provider="openai",
            base_url="https://token.sensenova.cn/v1",
            api_key="enc-test",
            default_model="sensenova-6.7-flash-lite",
            models=["sensenova-6.7-flash-lite", "sensechat-5", "glm-5.2"],
            model_metadata={
                "sensenova-6.7-flash-lite": {
                    "id": "sensenova-6.7-flash-lite",
                    "name": "Sensenova 6.7 Flash Lite",
                    "capabilities": ["text"],
                },
                "sensechat-5": {"id": "sensechat-5", "name": "SenseChat 5"},
            },
            is_builtin=True,
        )
    }
    mgr._default_provider_id = None
    mgr._config_lock = threading.RLock()
    mgr._save_config = MagicMock()
    mgr._config_path = MagicMock()
    return mgr


class TestRenameModelEntry:
    def test_rename_id_replaces_models_list(self, manager):
        ok = manager.rename_model_entry("sensetime", "sensechat-5", new_id="sensechat-5-pro")
        assert ok is True
        kept = manager.get_provider("sensetime")
        assert "sensechat-5-pro" in kept.models
        assert "sensechat-5" not in kept.models
        assert kept.models == ["sensenova-6.7-flash-lite", "sensechat-5-pro", "glm-5.2"]

    def test_rename_id_migrates_metadata_key(self, manager):
        manager.rename_model_entry("sensetime", "sensechat-5", new_id="sensechat-5-pro")
        meta = manager.get_provider("sensetime").model_metadata
        assert "sensechat-5-pro" in meta
        assert "sensechat-5" not in meta
        assert meta["sensechat-5-pro"]["name"] == "SenseChat 5"
        assert meta["sensechat-5-pro"]["id"] == "sensechat-5-pro"

    def test_rename_name_only_keeps_id(self, manager):
        ok = manager.rename_model_entry("sensetime", "sensechat-5", name="商量 5 Pro")
        assert ok is True
        meta = manager.get_provider("sensetime").model_metadata
        assert meta["sensechat-5"]["name"] == "商量 5 Pro"

    def test_rename_syncs_default_model(self, manager):
        manager.rename_model_entry(
            "sensetime", "sensenova-6.7-flash-lite", new_id="sensenova-6.7-flash-lite-v2"
        )
        assert manager.get_provider("sensetime").default_model == "sensenova-6.7-flash-lite-v2"

    def test_rename_does_not_touch_default_model_when_other(self, manager):
        # 改非默认模型的 ID 不应改变 default_model
        manager.rename_model_entry("sensetime", "sensechat-5", new_id="sensechat-5-pro")
        assert manager.get_provider("sensetime").default_model == "sensenova-6.7-flash-lite"

    def test_rename_unknown_provider_returns_false(self, manager):
        assert manager.rename_model_entry("no-such", "x", new_id="y") is False

    def test_rename_unknown_model_returns_false(self, manager):
        assert manager.rename_model_entry("sensetime", "no-such-model", name="X") is False

    def test_rename_creates_metadata_for_untracked_model(self, manager):
        # models 中存在但无 metadata 键(如 add_model 手动添加)的条目,仅改名时补建
        manager.rename_model_entry("sensetime", "glm-5.2", name="GLM 5.2 定制")
        meta = manager.get_provider("sensetime").model_metadata
        assert meta["glm-5.2"]["name"] == "GLM 5.2 定制"

    def test_rename_persists(self, manager):
        manager.rename_model_entry("sensetime", "sensechat-5", new_id="sensechat-5-pro")
        manager._save_config.assert_called()
