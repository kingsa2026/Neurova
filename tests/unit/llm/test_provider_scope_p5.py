"""
P5 升级:LLM 配置用户隔离 — ProviderManager scope 化。

TDD Red Phase:以下测试定义目标行为,当前实现应全部失败。

需求:管理员(admin scope)持有全局配置;普通用户仅可见/可使用自己的配置。
- scope "admin" 沿用存量 ~/.neurova/config/providers.json(升级不丢配置)
- scope "user:<user_id>" 使用独立配置文件 providers.<sanitized>.json
- 各 scope 实例内存隔离,互不影响
- 无参 get_provider_manager() 保持默认(admin)行为,向后兼容
"""

from __future__ import annotations

import threading

import pytest
from unittest.mock import patch

from neurova.llm.provider_manager import (
    LLMProviderManager,
    get_provider_manager,
    reset_provider_manager,
    _provider_manager_lock,
)


@pytest.fixture(autouse=True)
def reset_all():
    # 注意:reset_provider_manager 内部已持 _provider_manager_lock(非重入锁),
    # 外层不得再加锁,否则测试收尾必然死锁。
    yield
    reset_provider_manager()


class TestScopeIsolation:
    def test_default_manager_is_admin_scope(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mgr = get_provider_manager()
        # 向后兼容:默认仍是全局配置路径(存量 providers.json)
        assert mgr._config_path.name == "providers.json"

    def test_user_scope_gets_separate_config_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mgr = get_provider_manager(scope="user:alice")
        assert mgr._config_path.name == "providers.user-alice.json"

    def test_admin_scope_uses_global_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert (
            get_provider_manager(scope="admin")._config_path
            == get_provider_manager()._config_path
        )

    def test_user_scope_instances_are_distinct(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        alice = get_provider_manager(scope="user:alice")
        bob = get_provider_manager(scope="user:bob")
        assert alice is not bob
        assert alice._providers is not bob._providers

    def test_config_content_isolated_between_scopes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        admin = get_provider_manager(scope="admin")
        alice = get_provider_manager(scope="user:alice")
        admin.add_provider(
            name="Admin Only", provider="openai", base_url="https://x.example/v1",
        )
        # id 会被 _generate_provider_id 改写(name 化的小写形式),按 name 断言归属
        admin_names = {p.name for p in admin.list_providers()}
        alice_names = {p.name for p in alice.list_providers()}
        assert "Admin Only" in admin_names
        assert "Admin Only" not in alice_names

    def test_sanitized_scope_path(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        mgr = get_provider_manager(scope="user:alice@acme/CN")
        # 非法文件名字符需被替换,不得产生嵌套/特殊路径
        assert mgr._config_path.parent == tmp_path / ".neurova" / "config"
        assert ".." not in mgr._config_path.name
        assert mgr._config_path.suffix == ".json"

    def test_reset_clears_all_scopes(self, tmp_path, monkeypatch):
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        alice = get_provider_manager(scope="user:alice")
        admin = get_provider_manager(scope="admin")
        reset_provider_manager()
        alice2 = get_provider_manager(scope="user:alice")
        admin2 = get_provider_manager(scope="admin")
        assert alice2 is not alice
        assert admin2 is not admin
