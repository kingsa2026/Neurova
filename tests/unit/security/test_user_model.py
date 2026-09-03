"""
neurova/auth/user_model.py 测试

覆盖: UserModel 类的 CRUD、登录计数、失败锁定、登录日志
"""
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from neurova.auth.user_model import UserModel


# ================================================================
# 辅助工具
# ================================================================

def _hash(pw: str) -> str:
    """bcrypt 哈希"""
    import bcrypt
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def tmp_db(tmp_path):
    """临时数据库文件路径"""
    return str(tmp_path / "test_users.db")


@pytest.fixture
def model(tmp_db):
    """用临时数据库的 UserModel 实例，自动初始化"""
    m = UserModel(db_path=tmp_db)
    m._init_db()
    return m


# ================================================================
# 初始化
# ================================================================

class TestInit:
    def test_init_creates_tables(self, model):
        """users 表和 login_logs 表存在"""
        conn = model._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "users" in tables
        assert "login_logs" in tables
        conn.close()

    def test_custom_db_path_creates_file(self, tmp_path):
        db = str(tmp_path / "custom.db")
        m = UserModel(db_path=db)
        m._init_db()
        assert Path(db).exists()


# ================================================================
# 创建用户
# ================================================================

class TestCreateUser:
    def test_create_basic(self, model):
        user = model.create_user("alice", _hash("pw"), "alice@test.com")
        assert user is not None
        assert user["username"] == "alice"
        assert user["email"] == "alice@test.com"
        assert user["role"] == "user"
        assert user["status"] == "active"

    def test_create_admin_role(self, model):
        user = model.create_user("admin", _hash("pw"), role="admin")
        assert user["role"] == "admin"

    def test_create_duplicate_username(self, model):
        model.create_user("dup", _hash("pw1"), "dup@test.com")
        user = model.create_user("dup", _hash("pw2"), "dup2@test.com")
        assert user is None

    def test_create_duplicate_email(self, model):
        model.create_user("a1", _hash("pw"), "same@test.com")
        user = model.create_user("a2", _hash("pw"), "same@test.com")
        assert user is None

    def test_auto_generated_fields(self, model):
        user = model.create_user("bob", _hash("pw"))
        assert "id" in user
        assert "created_at" in user
        assert "updated_at" in user
        assert user["login_count"] == 0
        assert user["failed_attempts"] == 0
        assert user["locked_until"] is None
        assert user["reset_token"] is None


# ================================================================
# 查询用户
# ================================================================

class TestGetUserById:
    def test_found(self, model):
        created = model.create_user("alice", _hash("pw"))
        user = model.get_user_by_id(created["id"])
        assert user is not None
        assert user["username"] == "alice"

    def test_not_found(self, model):
        assert model.get_user_by_id(999) is None


class TestGetUserByUsername:
    def test_found(self, model):
        model.create_user("alice", _hash("pw"))
        user = model.get_user_by_username("alice")
        assert user is not None
        assert user["email"] is None  # no email provided

    def test_not_found(self, model):
        assert model.get_user_by_username("nobody") is None

    def test_case_sensitive(self, model):
        model.create_user("Alice", _hash("pw"))
        assert model.get_user_by_username("alice") is None


class TestGetUserByEmail:
    def test_found(self, model):
        model.create_user("alice", _hash("pw"), "alice@test.com")
        user = model.get_user_by_email("alice@test.com")
        assert user is not None
        assert user["username"] == "alice"

    def test_not_found(self, model):
        assert model.get_user_by_email("nobody@test.com") is None

    def test_null_email(self, model):
        model.create_user("alice", _hash("pw"))
        assert model.get_user_by_email(None) is None


class TestListUsers:
    def test_empty(self, model):
        assert model.list_users() == []

    def test_returns_all(self, model):
        model.create_user("a", _hash("pw"))
        model.create_user("b", _hash("pw"))
        users = model.list_users()
        assert len(users) == 2

    def test_pagination(self, model):
        for i in range(10):
            model.create_user(f"user_{i}", _hash("pw"))
        assert len(model.list_users(limit=3)) == 3
        assert len(model.list_users(limit=5, offset=8)) == 2

    def test_returns_list(self, model):
        """list_users 返回列表（按 created_at DESC 排序）"""
        model.create_user("b", _hash("pw"))
        model.create_user("a", _hash("pw"))
        users = model.list_users()
        assert len(users) == 2
        # 两个不同的用户
        assert {u["username"] for u in users} == {"a", "b"}


class TestCountUsers:
    def test_zero(self, model):
        assert model.count_users() == 0

    def test_multiple(self, model):
        model.create_user("a", _hash("pw"))
        model.create_user("b", _hash("pw"))
        assert model.count_users() == 2


# ================================================================
# 更新用户
# ================================================================

class TestUpdateUser:
    def test_update_email(self, model):
        u = model.create_user("alice", _hash("pw"))
        ok = model.update_user(u["id"], email="new@test.com")
        assert ok is True
        assert model.get_user_by_id(u["id"])["email"] == "new@test.com"

    def test_update_role(self, model):
        u = model.create_user("alice", _hash("pw"))
        model.update_user(u["id"], role="admin")
        assert model.get_user_by_id(u["id"])["role"] == "admin"

    def test_update_status(self, model):
        u = model.create_user("alice", _hash("pw"))
        model.update_user(u["id"], status="inactive")
        assert model.get_user_by_id(u["id"])["status"] == "inactive"

    def test_update_unknown_field_ignored(self, model):
        """只允许 allowed_fields 中的字段"""
        u = model.create_user("alice", _hash("pw"))
        ok = model.update_user(u["id"], username="bob", email="new@test.com")
        assert ok is True
        # username 不在 allowed_fields 中，不应生效
        assert model.get_user_by_id(u["id"])["username"] == "alice"
        # email 在 allowed_fields 中，应生效
        assert model.get_user_by_id(u["id"])["email"] == "new@test.com"

    def test_update_nonexistent(self, model):
        ok = model.update_user(999, email="x@test.com")
        assert ok is False

    def test_update_with_empty_updates(self, model):
        """没有合法的更新字段时返回 False"""
        ok = model.update_user(999)
        assert ok is False


# ================================================================
# 删除用户
# ================================================================

class TestDeleteUser:
    def test_delete_existing(self, model):
        u = model.create_user("alice", _hash("pw"))
        ok = model.delete_user(u["id"])
        assert ok is True
        assert model.get_user_by_id(u["id"]) is None

    def test_delete_nonexistent(self, model):
        ok = model.delete_user(999)
        assert ok is False


# ================================================================
# 登录计数
# ================================================================

class TestIncrementLoginCount:
    def test_increments(self, model):
        u = model.create_user("alice", _hash("pw"))
        assert u["login_count"] == 0
        model.increment_login_count(u["id"])
        model.increment_login_count(u["id"])
        user = model.get_user_by_id(u["id"])
        assert user["login_count"] == 2

    def test_updates_last_login(self, model):
        """last_login 由 SQLite datetime('now') 写入（UTC），校验存在且格式合法"""
        u = model.create_user("alice", _hash("pw"))
        assert u["last_login"] is None
        model.increment_login_count(u["id"])
        user = model.get_user_by_id(u["id"])
        assert user["last_login"] is not None
        # 验证能被解析为 ISO 时间字符串
        parsed = datetime.fromisoformat(user["last_login"])
        assert isinstance(parsed, datetime)


# ================================================================
# 失败尝试与锁定
# ================================================================

class TestIncrementFailedAttempts:
    def test_increments_and_locks(self, model):
        u = model.create_user("alice", _hash("pw"))
        assert u["failed_attempts"] == 0
        model.increment_failed_attempts(u["id"], max_attempts=3)
        model.increment_failed_attempts(u["id"], max_attempts=3)
        user = model.get_user_by_id(u["id"])
        assert user["failed_attempts"] == 2
        assert user["locked_until"] is None

        model.increment_failed_attempts(u["id"], max_attempts=3)
        user = model.get_user_by_id(u["id"])
        assert user["failed_attempts"] == 3
        assert user["locked_until"] is not None
        # locked_until 应在未来
        locked_until = datetime.fromisoformat(user["locked_until"])
        assert locked_until > datetime.now()

    def test_custom_lock_duration(self, model):
        u = model.create_user("alice", _hash("pw"))
        model.increment_failed_attempts(u["id"], max_attempts=1, lock_duration_minutes=5)
        user = model.get_user_by_id(u["id"])
        locked_until = datetime.fromisoformat(user["locked_until"])
        # 默认锁定 15 分钟，这里指定 5 分钟
        diff = (locked_until - datetime.now()).total_seconds()
        assert 4 * 60 <= diff <= 6 * 60


# ================================================================
# 登录日志
# ================================================================

class TestLogLogin:
    def test_log_success(self, model):
        u = model.create_user("alice", _hash("pw"))
        model.log_login(u["id"], "alice", "192.168.1.1", True, "登录成功")
        logs = model.get_login_logs(u["id"])
        assert len(logs) == 1
        assert logs[0]["username"] == "alice"
        assert logs[0]["success"] == 1  # SQLite boolean is int
        assert logs[0]["ip_address"] == "192.168.1.1"

    def test_log_failure(self, model):
        u = model.create_user("alice", _hash("pw"))
        model.log_login(u["id"], "alice", "10.0.0.1", False, "密码错误")
        logs = model.get_login_logs(u["id"])
        assert logs[0]["success"] == 0

    def test_multiple_logs(self, model):
        u = model.create_user("alice", _hash("pw"))
        for _ in range(5):
            model.log_login(u["id"], "alice", "10.0.0.1", True, "")
        logs = model.get_login_logs(u["id"])
        assert len(logs) == 5

    def test_log_limit(self, model):
        u = model.create_user("alice", _hash("pw"))
        for _ in range(20):
            model.log_login(u["id"], "alice", "", True, "")
        logs = model.get_login_logs(u["id"], limit=10)
        assert len(logs) == 10

    def test_logs_ordered_by_newest(self, model):
        u = model.create_user("alice", _hash("pw"))
        model.log_login(u["id"], "alice", "", True, "first")
        import time
        time.sleep(1.1)  # SQLite datetime('now') 精度为秒级
        model.log_login(u["id"], "alice", "", True, "second")
        logs = model.get_login_logs(u["id"])
        assert len(logs) == 2
        # 最新的在前
        assert logs[0]["message"] == "second"

    def test_empty_logs(self, model):
        assert model.get_login_logs(999) == []

    def test_log_without_user_id(self, model):
        """可以查询所有日志（user_id=None）"""
        u1 = model.create_user("a", _hash("pw"))
        u2 = model.create_user("b", _hash("pw"))
        model.log_login(u1["id"], "a", "", True, "")
        model.log_login(u2["id"], "b", "", True, "")
        all_logs = model.get_login_logs()
        assert len(all_logs) == 2
