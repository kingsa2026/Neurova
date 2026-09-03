"""Tests for auth/enhanced_user_model.py - core scenarios only."""
import pytest


class TestEnhancedUserModel:
    def test_init(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        assert svc is not None

    def test_create_user(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="alice", password="secret123", email="alice@example.com")
        assert user is not None
        assert isinstance(user, dict)
        assert user.get("username") == "alice"
        assert user.get("email") == "alice@example.com"
        assert isinstance(user.get("id"), str) and user.get("id")
        assert user.get("status") == "active"
        assert user.get("password_hash") and user.get("password_hash") != "secret123"

    def test_create_user_with_group_type(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="admin1", password="pw", email="admin@x.com", group_type="admin")
        assert user is not None
        assert user.get("group_type") == "admin"

    def test_create_user_duplicate_username_returns_none(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        svc.create_user(username="bob", password="pw", email="bob@x.com")
        dup = svc.create_user(username="bob", password="pw2", email="other@x.com")
        assert dup is None

    def test_get_user_by_id_and_username_and_email(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="carol", password="pw", email="carol@x.com")
        uid = user["id"]
        assert svc.get_user_by_id(uid)["username"] == "carol"
        assert svc.get_user_by_username("carol")["id"] == uid
        assert svc.get_user_by_email("carol@x.com")["id"] == uid
        assert svc.get_user_by_id("usr_nope") is None
        assert svc.get_user_by_username("ghost") is None

    def test_authenticate_user_success(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        svc.create_user(username="dave", password="correct-pw", email="d@x.com")
        result = svc.authenticate_user("dave", "correct-pw")
        assert result is not None
        assert result.get("username") == "dave"

    def test_authenticate_user_wrong_password(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        svc.create_user(username="eve", password="real-pw", email="e@x.com")
        assert svc.authenticate_user("eve", "wrong-pw") is None
        assert svc.authenticate_user("nobody", "anything") is None

    def test_authenticate_inactive_user_fails(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="frank", password="pw", email="f@x.com")
        svc.update_user(user["id"], status="inactive")
        assert svc.authenticate_user("frank", "pw") is None

    def test_update_user_profile(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="grace", password="pw", email="g@x.com")
        uid = user["id"]
        ok = svc.update_user(uid, display_name="Grace H", bio="ML engineer")
        assert ok is True
        fetched = svc.get_user_by_id(uid)
        assert fetched.get("display_name") == "Grace H"
        assert fetched.get("bio") == "ML engineer"

    def test_assign_group_type(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="henry", password="pw", email="h@x.com")
        assert svc.update_user(user["id"], group_type="admin") is True
        assert svc.get_user_by_id(user["id"]).get("group_type") == "admin"

    def test_deactivate_user(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="ivy", password="pw", email="i@x.com")
        assert svc.update_user(user["id"], status="inactive") is True
        assert svc.get_user_by_id(user["id"]).get("status") == "inactive"

    def test_delete_user(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="jack", password="pw", email="j@x.com")
        uid = user["id"]
        assert svc.delete_user(uid) is True
        assert svc.get_user_by_id(uid) is None
        assert svc.delete_user(uid) is False

    def test_list_and_count_users(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        svc.create_user(username="u1", password="pw", email="u1@x.com")
        svc.create_user(username="u2", password="pw", email="u2@x.com", group_type="admin")
        svc.create_user(username="u3", password="pw", email="u3@x.com")
        all_users = svc.list_users()
        assert isinstance(all_users, list)
        assert len(all_users) == 3
        admins = svc.list_users(group_type="admin")
        assert len(admins) == 1
        assert svc.count_users() == 3
        assert svc.count_users(group_type="admin") == 1

    def test_failed_attempts_lock_account(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="kim", password="real-pw", email="k@x.com")
        for _ in range(6):
            svc.authenticate_user("kim", "wrong-pw")
        fetched = svc.get_user_by_id(user["id"])
        assert fetched.get("failed_attempts", 0) >= 5
        assert fetched.get("status") == "locked" or fetched.get("locked_until")

    def test_log_login_and_get_logs(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="leo", password="pw", email="l@x.com")
        svc.log_login(user["id"], "leo", "127.0.0.1", True, "ok")
        svc.log_login(user["id"], "leo", "127.0.0.1", False, "bad")
        logs = svc.get_login_logs(user_id=user["id"])
        assert isinstance(logs, list)
        assert len(logs) >= 2

    def test_get_user_permissions_and_check(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="mia", password="pw", email="m@x.com", group_type="admin")
        perms = svc.get_user_permissions(user["id"])
        assert perms is not None
        has_admin = svc.check_user_permission(user["id"], "admin")
        assert isinstance(has_admin, bool)

    def test_persistence_across_instances(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        path = str(tmp_path / "users")
        svc1 = EnhancedUserModel(path)
        u = svc1.create_user(username="nina", password="pw", email="n@x.com")
        uid = u["id"]
        svc2 = EnhancedUserModel(path)
        fetched = svc2.get_user_by_id(uid)
        assert fetched is not None
        assert fetched.get("username") == "nina"

    def test_update_last_active(self, tmp_path):
        from neurova.auth.enhanced_user_model import EnhancedUserModel
        svc = EnhancedUserModel(str(tmp_path / "users"))
        user = svc.create_user(username="oscar", password="pw", email="o@x.com")
        ok = svc.update_last_active(user["id"])
        assert ok is True or ok is None
        fetched = svc.get_user_by_id(user["id"])
        assert fetched.get("last_active")


class TestGetEnhancedUserModelService:
    def test_returns_singleton(self):
        from neurova.auth.enhanced_user_model import get_enhanced_user_model
        a = get_enhanced_user_model()
        b = get_enhanced_user_model()
        assert a is b
