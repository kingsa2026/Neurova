"""ResourceQuotaManager 单元测试（对齐真实实现）。

真实 API（neurova/admin/resource_quota_manager.py）：
    ResourceQuotaManager(storage_dir, custom_limits=None, group_limits=None)
    get_user_quota(user_id, group_type="user") -> Dict[str, int]
    get_usage(user_id) -> ResourceUsage
    check_*_quota(...) -> {"allowed", "current", "projected", "limit", ...}
    increment_*/decrement_* 计数；try_consume；reset_user/reset_all；
    get_quota_status；list_users_near_limits；get_all_usage；get_stats。

判定语义：_check 中 projected = current + additional，projected >= limit 即拒绝。
"""

import pytest

from neurova.admin.resource_quota_manager import (
    DEFAULT_LIMITS,
    ResourceQuotaManager,
    ResourceUsage,
)


@pytest.fixture
def manager(tmp_path):
    return ResourceQuotaManager(str(tmp_path / "quota"))


class TestConstruction:
    def test_creates_storage_dir(self, tmp_path):
        target = tmp_path / "quota"
        ResourceQuotaManager(str(target))
        assert target.exists()

    def test_default_quota_matches_default_limits(self, manager):
        assert manager.get_user_quota("u1") == DEFAULT_LIMITS

    def test_custom_limits_override_defaults(self, tmp_path):
        mgr = ResourceQuotaManager(str(tmp_path / "q"), custom_limits={"max_agents": 2})
        quota = mgr.get_user_quota("u1")
        assert quota["max_agents"] == 2
        assert quota["max_projects"] == DEFAULT_LIMITS["max_projects"]

    def test_group_limits_apply_for_matching_group(self, tmp_path):
        mgr = ResourceQuotaManager(
            str(tmp_path / "q"),
            group_limits={"vip": {"max_agents": 50}},
        )
        assert mgr.get_user_quota("u1", group_type="vip")["max_agents"] == 50
        assert mgr.get_user_quota("u1", group_type="user")["max_agents"] == DEFAULT_LIMITS["max_agents"]


class TestGetUsage:
    def test_returns_resource_usage_with_user_id(self, manager):
        usage = manager.get_usage("u1")
        assert isinstance(usage, ResourceUsage)
        assert usage.user_id == "u1"

    def test_fresh_usage_is_zeroed(self, manager):
        usage = manager.get_usage("u1")
        assert usage.agent_count == 0
        assert usage.llm_call_count == 0
        assert usage.storage_bytes == 0


class TestCheckQuota:
    def test_allowed_when_under_limit(self, manager):
        result = manager.check_agent_quota("u1")
        assert result["allowed"] is True
        assert result["current"] == 0
        assert result["limit"] == DEFAULT_LIMITS["max_agents"]

    def test_denied_when_at_limit(self, tmp_path):
        mgr = ResourceQuotaManager(str(tmp_path / "q"), custom_limits={"max_agents": 2})
        mgr.increment_agent_count("u1")
        mgr.increment_agent_count("u1")
        result = mgr.check_agent_quota("u1")
        assert result["allowed"] is False
        assert result["current"] == 2
        assert result["projected"] == 2

    def test_storage_check_honours_additional_bytes(self, tmp_path):
        mgr = ResourceQuotaManager(str(tmp_path / "q"), custom_limits={"max_storage_bytes": 100})
        assert mgr.check_storage_quota("u1", additional_bytes=50)["allowed"] is True
        assert mgr.check_storage_quota("u1", additional_bytes=100)["allowed"] is False

    def test_all_check_endpoints_return_allowed_flag(self, manager):
        checks = [
            manager.check_agent_quota("u1"),
            manager.check_project_quota("u1"),
            manager.check_llm_call_quota("u1"),
            manager.check_llm_token_quota("u1"),
            manager.check_storage_quota("u1"),
            manager.check_file_size_quota("u1"),
            manager.check_private_skill_quota("u1"),
            manager.check_collab_project_quota("u1"),
            manager.check_api_call_quota("u1"),
            manager.check_concurrent_session_quota("u1"),
        ]
        assert all(c["allowed"] is True for c in checks)


class TestCounters:
    def test_increment_and_decrement_agent_count(self, manager):
        manager.increment_agent_count("u1")
        manager.increment_agent_count("u1")
        assert manager.get_usage("u1").agent_count == 2
        manager.decrement_agent_count("u1")
        assert manager.get_usage("u1").agent_count == 1

    def test_decrement_floors_at_zero(self, manager):
        manager.decrement_agent_count("u1")
        assert manager.get_usage("u1").agent_count == 0

    def test_increment_llm_call_and_token(self, manager):
        manager.increment_llm_call("u1", count=3)
        manager.increment_llm_token("u1", tokens=512)
        usage = manager.get_usage("u1")
        assert usage.llm_call_count == 3
        assert usage.llm_token_count == 512

    def test_increment_and_decrement_storage(self, manager):
        manager.increment_storage("u1", 1000)
        assert manager.get_usage("u1").storage_bytes == 1000
        manager.decrement_storage("u1", 400)
        assert manager.get_usage("u1").storage_bytes == 600

    def test_reset_api_call_zeroes_count(self, manager):
        manager.increment_api_call("u1", count=5)
        assert manager.get_usage("u1").api_call_count == 5
        manager.reset_api_call("u1")
        assert manager.get_usage("u1").api_call_count == 0


class TestPersistence:
    def test_usage_persists_across_instances(self, tmp_path):
        dir_path = str(tmp_path / "q")
        first = ResourceQuotaManager(dir_path)
        first.increment_agent_count("u1")
        first.increment_llm_token("u1", tokens=99)
        second = ResourceQuotaManager(dir_path)
        usage = second.get_usage("u1")
        assert usage.agent_count == 1
        assert usage.llm_token_count == 99


class TestTryConsume:
    def test_consumes_until_limit(self, tmp_path):
        mgr = ResourceQuotaManager(str(tmp_path / "q"), custom_limits={"max_agents": 2})
        assert mgr.try_consume("u1", "agent_count", "max_agents") is True
        assert mgr.try_consume("u1", "agent_count", "max_agents") is True
        assert mgr.try_consume("u1", "agent_count", "max_agents") is False
        assert mgr.get_usage("u1").agent_count == 2


class TestStatusAndReporting:
    def test_get_quota_status_shape(self, manager):
        manager.increment_agent_count("u1")
        status = manager.get_quota_status("u1")
        assert status["user_id"] == "u1"
        assert status["limits"] == DEFAULT_LIMITS
        assert status["usage"]["agent_count"] == 1

    def test_list_users_near_limits(self, tmp_path):
        mgr = ResourceQuotaManager(str(tmp_path / "q"), custom_limits={"max_agents": 10})
        for _ in range(8):
            mgr.increment_agent_count("u1")
        near = mgr.list_users_near_limits(threshold=0.8)
        assert any(entry["user_id"] == "u1" for entry in near)

    def test_list_users_near_limits_excludes_low_usage(self, manager):
        manager.increment_agent_count("u1")
        assert manager.list_users_near_limits(threshold=0.8) == []

    def test_get_all_usage_and_reset(self, manager):
        manager.increment_agent_count("u1")
        manager.increment_project_count("u2")
        all_usage = manager.get_all_usage()
        assert set(all_usage.keys()) == {"u1", "u2"}
        manager.reset_user("u1")
        assert set(manager.get_all_usage().keys()) == {"u2"}
        manager.reset_all()
        assert manager.get_all_usage() == {}

    def test_get_stats_totals(self, manager):
        manager.increment_agent_count("u1")
        manager.increment_agent_count("u2")
        stats = manager.get_stats()
        assert stats["total_users"] == 2
        assert stats["totals"]["agent_count"] == 2


class TestSingleton:
    def test_get_and_reset_singleton(self, tmp_path, monkeypatch):
        import neurova.admin.resource_quota_manager as mod

        monkeypatch.setattr(mod, "_DEFAULT_DIR", str(tmp_path / "singleton"))
        mod.reset_resource_quota_manager()
        try:
            a = mod.get_resource_quota_manager()
            b = mod.get_resource_quota_manager()
            assert a is b
        finally:
            mod.reset_resource_quota_manager()
