# -*- coding: utf-8 -*-
"""服务商改名契约（P8 实机联调发现的后端断链）。

实测：PUT /providers/{id} 带 {"name": "新名"} 返回 status=updated，
但 ProviderInfo.name 原样不动——UpdateProviderRequest 声明了 name 字段，
端点却从不转发；ProviderManager.update_provider 也没有 name 参数。
改名这条链路从 API 到管理器整条断（静默无效，比 500 更隐蔽）。
"""
import pytest

from neurova.llm.provider_manager import LLMProviderManager, ProviderConfig


@pytest.fixture
def manager(tmp_path):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(LLMProviderManager, "__init__", lambda self, **kw: None)
        mgr = LLMProviderManager.__new__(LLMProviderManager)
        mgr._providers = {}
        mgr._default_provider_id = None
        mgr._config_lock = __import__("threading").RLock()
        mgr._config_path = tmp_path / "provider_config.json"
        yield mgr


def _add_provider(mgr, pid: str, name: str) -> ProviderConfig:
    cfg = ProviderConfig(
        id=pid,
        name=name,
        provider="openai",
        base_url="https://api.example.com/v1",
        models=[],
        enabled=True,
    )
    mgr._providers[pid] = cfg
    return cfg


class TestUpdateProviderRename:
    def test_update_provider_accepts_and_applies_name(self, manager):
        _add_provider(manager, "verify-provider", "Verify Provider")

        result = manager.update_provider("verify-provider", name="Verify Provider 2")

        assert result is True
        assert manager._providers["verify-provider"].name == "Verify Provider 2"

    def test_name_none_keeps_existing_name(self, manager):
        _add_provider(manager, "p1", "保持原名")

        manager.update_provider("p1", name=None, base_url="http://x/v1")

        assert manager._providers["p1"].name == "保持原名"
        assert manager._providers["p1"].base_url == "http://x/v1"
