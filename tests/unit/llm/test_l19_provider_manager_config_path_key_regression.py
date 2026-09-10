"""L-19 回归测试：get_provider_manager 单例键必须纳入 config_path。

红绿：无修复时单例键固定 f"scope:{scope}"——scope=None 且显式传不同
config_path 时键均为 "scope:None"，不同配置路径错误共享同一实例。
断言：不同 config_path → 不同实例；相同 config_path → 同一实例；
既有 scope 命中行为不变。
"""

import pytest

from neurova.llm.provider_manager import (
    get_provider_manager,
    reset_provider_manager,
)


@pytest.fixture(autouse=True)
def reset_all():
    reset_provider_manager()
    yield
    reset_provider_manager()


class TestL19ConfigPathKey:
    def test_different_config_paths_get_different_instances(self, tmp_path):
        m1 = get_provider_manager(config_path=str(tmp_path / "a.json"))
        m2 = get_provider_manager(config_path=str(tmp_path / "b.json"))
        assert m1 is not m2, "L-19: 不同 config_path 不得共享同一单例"

    def test_same_config_path_returns_same_instance(self, tmp_path):
        p = str(tmp_path / "a.json")
        assert get_provider_manager(config_path=p) is get_provider_manager(config_path=p)

    def test_scope_hit_behavior_preserved(self, tmp_path, monkeypatch):
        """既有 scope 单例命中行为不变（键稳定）。"""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        u1 = get_provider_manager(scope="user:alice")
        u2 = get_provider_manager(scope="user:alice")
        assert u1 is u2

    def test_explicit_path_isolated_from_scope_singleton(self, tmp_path, monkeypatch):
        """显式 config_path 与 scope 派生路径互不串实例。"""
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        scoped = get_provider_manager(scope="user:bob")
        explicit = get_provider_manager(config_path=str(tmp_path / "custom.json"))
        assert scoped is not explicit
