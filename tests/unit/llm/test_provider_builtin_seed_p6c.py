"""
P6c 修复:内置服务商定义(openrouter/opencode 等)播种回后端。

TDD Red Phase:当前实现(_load_builtin_providers 空播种)下全部失败。

背景:前端 ModelPage 种子卡片展示 openrouter/opencode,但 P5 后后端无
内置定义 → 这些服务商的后端实体不存在,配置/发现全部落空。
修复:内置定义只补缺失 id,绝不覆盖用户已配置的服务商。
"""

from __future__ import annotations

import os
import threading
from unittest.mock import MagicMock

import pytest

from neurova.llm.provider_manager import (
    LLMProviderManager,
    ProviderConfig,
    _BUILTIN_PROVIDER_DEFS,
)

# 测试占位,不落源码;真实密钥只能来自配置/环境变量
_CRED = os.environ.get("NEUROVA_TEST_CRED", "seed-test-placeholder")


@pytest.fixture
def manager():
    mgr = LLMProviderManager.__new__(LLMProviderManager)
    mgr._providers = {}
    mgr._default_provider_id = None
    mgr._config_lock = threading.RLock()
    mgr._save_config = MagicMock()
    mgr._config_path = MagicMock()
    return mgr


class TestBuiltinDefs:
    def test_defs_cover_frontend_seed_core(self):
        ids = {d["id"] for d in _BUILTIN_PROVIDER_DEFS}
        assert {"openrouter", "opencode"} <= ids

    def test_empty_scope_seeds_builtins(self, manager):
        manager._load_builtin_providers()
        providers = manager.list_providers()
        by_id = {p.id: p for p in providers}
        assert by_id["openrouter"].base_url == "https://openrouter.ai/api/v1"
        assert by_id["openrouter"].is_builtin is True
        assert by_id["opencode"].is_builtin is True
        # 无默认模型(发现/筛选才能填充真实清单)
        assert by_id["openrouter"].models == []

    def test_does_not_override_user_configured_provider(self, manager):
        manager._providers["openrouter"] = ProviderConfig(
            id="openrouter",
            name="OpenRouter",
            provider="openrouter",
            base_url="https://custom.example.com/v1",
            api_key=_CRED,
            models=["openai/gpt-4o"],
        )
        manager._load_builtin_providers()
        kept = manager.get_provider("openrouter")
        assert kept.base_url == "https://custom.example.com/v1"
        assert kept.api_key == _CRED
        assert kept.models == ["openai/gpt-4o"]


class TestLoadConfigMergesBuiltins:
    def test_existing_config_merges_missing_builtins(self, tmp_path, monkeypatch):
        cfg_file = tmp_path / "providers.json"
        cfg_file.write_text(
            '{"providers": [{"id": "modelscope", "name": "MS", "provider": "openai",'
            ' "base_url": "https://api.example.com/v1", "models": []}],'
            ' "default_provider_id": null}',
            encoding="utf-8",
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path.parent)
        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._preset_registry = None
        mgr._config = {"config_path": str(cfg_file)}
        mgr._config_path = cfg_file
        mgr._providers = {}
        mgr._default_provider_id = None
        mgr._config_lock = threading.RLock()
        mgr._save_config = MagicMock()
        mgr._load_config()

        by_id = {p.id: p for p in mgr.list_providers()}
        assert "modelscope" in by_id  # 用户原有配置保留
        assert "openrouter" in by_id  # 缺失的内置定义补上
        assert by_id["openrouter"].is_builtin is True


class TestSensetimeBuiltin:
    """商汤非内置修复:ModelPage 展示卡片依赖后端实体,否则无种子可播种。

    实地查明:前端卡片 base_url 为 api.sensetime.com/v1(不可用),
    真实端点 token.sensenova.cn/v1 —— 内置定义必须对齐真实端点,
    用户只需填 key 即可开箱配置,不再需要手动新建自定义 provider。
    """

    def test_sensetime_in_builtin_defs(self):
        ids = {d["id"] for d in _BUILTIN_PROVIDER_DEFS}
        assert "sensetime" in ids

    def test_sensetime_seeds_with_real_base_url(self, manager):
        manager._load_builtin_providers()
        st = manager.get_provider("sensetime")
        assert st is not None
        assert st.is_builtin is True
        assert st.provider == "openai"
        assert st.base_url == "https://token.sensenova.cn/v1"
        assert st.models == []

    def test_sensetime_does_not_override_user_configured_provider(self, manager):
        manager._providers["sensetime"] = ProviderConfig(
            id="sensetime",
            name="商汤科技",
            provider="openai",
            base_url="https://token.sensenova.cn/v1",
            api_key=_CRED,
            models=["sensenova-6.7-flash-lite"],
        )
        manager._load_builtin_providers()
        kept = manager.get_provider("sensetime")
        assert kept.base_url == "https://token.sensenova.cn/v1"
        assert kept.api_key == _CRED
        assert kept.models == ["sensenova-6.7-flash-lite"]
