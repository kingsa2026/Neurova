"""Tests for neurova/admin/resource_quota_manager.py - core scenarios."""
import threading
import pytest


class TestResourceUsageDataclass:
    def test_to_from_dict_roundtrip(self):
        from neurova.admin.resource_quota_manager import ResourceUsage
        u = ResourceUsage(
            user_id="u_1",
            group_type="user",
            agent_count=2,
            project_count=3,
            llm_call_count=10,
            llm_token_count=5000,
            storage_bytes=2_000_000,
            file_size_bytes=1_000_000,
            private_skill_count=1,
            collab_project_count=0,
            api_call_count=42,
            concurrent_session_count=1,
        )
        d = u.to_dict()
        assert d["user_id"] == "u_1"
        assert d["agent_count"] == 2
        assert d["concurrent_session_count"] == 1
        u2 = ResourceUsage.from_dict(d)
        assert u2.user_id == "u_1"
        assert u2.agent_count == 2
        assert u2.api_call_count == 42

    def test_defaults_zero(self):
        from neurova.admin.resource_quota_manager import ResourceUsage
        u = ResourceUsage(user_id="u_x")
        assert u.agent_count == 0
        assert u.project_count == 0
        assert u.llm_call_count == 0
        assert u.storage_bytes == 0
        assert u.concurrent_session_count == 0
        assert u.group_type == "user"

    def test_reset_daily_usage_zeros_counters(self):
        from neurova.admin.resource_quota_manager import ResourceUsage
        u = ResourceUsage(user_id="u_2", llm_call_count=99, llm_token_count=12345)
        u.reset_daily_usage()
        assert u.llm_call_count == 0
        assert u.llm_token_count == 0


class TestResourceQuotaManagerInit:
    def test_default_init(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"))
        assert mgr is not None
        quota = mgr.get_user_quota("u_any", group_type="user")
        assert isinstance(quota, dict)
        assert "max_agents" in quota
        assert quota["max_agents"] > 0

    def test_custom_limits(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        custom = {"max_agents": 3, "max_projects": 5, "max_llm_calls_per_day": 100}
        mgr = ResourceQuotaManager(str(tmp_path / "quota"), custom_limits=custom)
        q = mgr.get_user_quota("u_x", group_type="user")
        assert q["max_agents"] == 3
        assert q["max_projects"] == 5
        assert q["max_llm_calls_per_day"] == 100

    def test_group_specific_limits(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(
            str(tmp_path / "quota"),
            group_limits={
                "admin": {"max_agents": 999, "max_projects": 999},
                "guest": {"max_agents": 1, "max_projects": 1},
            },
        )
        admin_q = mgr.get_user_quota("u_a", group_type="admin")
        guest_q = mgr.get_user_quota("u_g", group_type="guest")
        user_q = mgr.get_user_quota("u_u", group_type="user")
        assert admin_q["max_agents"] == 999
        assert guest_q["max_agents"] == 1
        assert user_q["max_agents"] < admin_q["max_agents"]


class TestQuotaChecks:
    def test_check_agent_quota_allowed(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"), custom_limits={"max_agents": 5})
        result = mgr.check_agent_quota("u_1")
        assert result["allowed"] is True

    def test_check_agent_quota_denied(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"), custom_limits={"max_agents": 2})
        mgr.increment_agent_count("u_1")
        mgr.increment_agent_count("u_1")
        result = mgr.check_agent_quota("u_1")
        assert result["allowed"] is False
        assert "reason" in result

    def test_consume_and_return(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"), custom_limits={"max_agents": 3})
        mgr.increment_agent_count("u_1")
        mgr.increment_agent_count("u_1")
        usage = mgr.get_usage("u_1")
        assert usage.agent_count == 2
        mgr.decrement_agent_count("u_1")
        assert mgr.get_usage("u_1").agent_count == 1

    def test_decrement_floors_at_zero(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"))
        mgr.decrement_agent_count("u_1")
        mgr.decrement_agent_count("u_1")
        assert mgr.get_usage("u_1").agent_count == 0

    def test_check_storage_quota(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(
            str(tmp_path / "quota"),
            custom_limits={"max_storage_bytes": 1000},
        )
        mgr.increment_storage("u_1", 600)
        mgr.increment_storage("u_1", 300)
        result = mgr.check_storage_quota("u_1", additional_bytes=200)
        assert result["allowed"] is False
        result2 = mgr.check_storage_quota("u_1", additional_bytes=50)
        assert result2["allowed"] is True


class TestQuotaStatusAndNearLimits:
    def test_get_quota_status(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(
            str(tmp_path / "quota"),
            custom_limits={"max_agents": 10, "max_projects": 10},
        )
        mgr.increment_agent_count("u_1")
        status = mgr.get_quota_status("u_1")
        assert status["user_id"] == "u_1"
        assert "limits" in status
        assert "usage" in status
        assert status["usage"]["agent_count"] == 1

    def test_list_users_near_limits(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(
            str(tmp_path / "quota"),
            custom_limits={"max_agents": 10},
        )
        mgr.increment_agent_count("u_low")
        mgr.increment_agent_count("u_high")
        for _ in range(8):
            mgr.increment_agent_count("u_high")
        near = mgr.list_users_near_limits(threshold=0.8)
        uids = [u["user_id"] for u in near]
        assert "u_high" in uids
        assert "u_low" not in uids


class TestPersistence:
    def test_persistence_across_instances(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        d = str(tmp_path / "quota")
        m1 = ResourceQuotaManager(d, custom_limits={"max_agents": 5})
        m1.increment_agent_count("u_persist")
        m1.increment_agent_count("u_persist")

        m2 = ResourceQuotaManager(d)
        u = m2.get_usage("u_persist")
        assert u.agent_count == 2


class TestThreadSafety:
    def test_concurrent_increments(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"), custom_limits={"max_agents": 100000})
        n_threads = 10
        per_thread = 50

        def worker():
            for _ in range(per_thread):
                mgr.increment_agent_count("u_race")

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert mgr.get_usage("u_race").agent_count == n_threads * per_thread

    def test_concurrent_check_then_increment(self, tmp_path):
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        mgr = ResourceQuotaManager(str(tmp_path / "quota"), custom_limits={"max_agents": 25})
        allowed_count = [0]
        denied_count = [0]
        lock = threading.Lock()

        def worker():
            for _ in range(10):
                if mgr.try_consume("u_consume", "agent_count", "max_agents"):
                    with lock:
                        allowed_count[0] += 1
                else:
                    with lock:
                        denied_count[0] += 1

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert allowed_count[0] == 25
        assert denied_count[0] == 75
        assert mgr.get_usage("u_consume").agent_count == 25


class TestCircularImportSafe:
    def test_can_import_admin_service_independently(self, tmp_path):
        from neurova.admin.admin_service import AdminService
        from neurova.admin.resource_quota_manager import ResourceQuotaManager
        svc = AdminService(str(tmp_path / "admin"))
        u = svc.create_user(username="alice", email="a@x.com", password="pw")
        assert u is not None
        qm = ResourceQuotaManager(str(tmp_path / "quota"))
        assert qm is not None
