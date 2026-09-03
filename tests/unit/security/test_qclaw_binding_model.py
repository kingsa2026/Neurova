"""
neurova/auth/qclaw_binding_model.py 测试

覆盖: QClawBindingModel 的 CRUD、加密/解密、多用户隔离、状态管理
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from neurova.auth.qclaw_binding_model import QClawBindingModel


# ================================================================
# Fixtures
# ================================================================

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_qclaw.db")


@pytest.fixture
def model(tmp_db):
    """用临时数据库的 QClawBindingModel 实例"""
    m = QClawBindingModel(db_path=tmp_db)
    m._init_db()
    return m


# ================================================================
# 初始化
# ================================================================

class TestInit:
    def test_init_creates_table(self, model):
        conn = model._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}
        assert "qclaw_bindings" in tables
        conn.close()

    def test_custom_path(self, tmp_path):
        db = str(tmp_path / "custom_qclaw.db")
        m = QClawBindingModel(db_path=db)
        m._init_db()
        assert Path(db).exists()


# ================================================================
# 创建绑定
# ================================================================

class TestCreateBinding:
    def test_create_basic(self, model):
        binding = model.create_binding("neuser_1", "user_1", "app_001", "secret_001")
        assert binding is not None
        assert binding["neuser_id"] == "neuser_1"
        assert binding["user_id"] == "user_1"
        assert binding["app_id"] == "app_001"
        assert binding["status"] == "enabled"

    def test_default_user_id(self, model):
        """user_id 为空时使用 neuser_id"""
        binding = model.create_binding("neuser_1", "", "app_002", "secret")
        assert binding["user_id"] == "neuser_1"

    def test_none_user_id(self, model):
        binding = model.create_binding("neuser_1", None, "app_003", "secret")  # type: ignore
        assert binding["user_id"] == "neuser_1"

    def test_with_qclaw_user_id(self, model):
        binding = model.create_binding("n1", "u1", "app_004", "secret", qclaw_user_id="qclaw_001")
        assert binding["qclaw_user_id"] == "qclaw_001"

    def test_duplicate_app_id_raises(self, model):
        model.create_binding("n1", "u1", "app_001", "secret")
        with pytest.raises(ValueError, match="已被其他用户绑定"):
            model.create_binding("n2", "u2", "app_001", "secret")

    def test_auto_generated_fields(self, model):
        binding = model.create_binding("n1", "u1", "app_005", "secret")
        assert "id" in binding
        assert "bound_at" in binding
        assert "created_at" in binding
        assert "updated_at" in binding
        assert binding["last_used_at"] is None

    def test_secret_encrypted(self, model):
        """存储时 secret 被加密（不是明文）"""
        binding = model.create_binding("n1", "u1", "app_006", "my_secret_key")
        # 直接查数据库看存储值
        conn = model._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT app_secret FROM qclaw_bindings WHERE id=?", (binding["id"],))
        row = cursor.fetchone()
        conn.close()
        stored = row["app_secret"]
        assert stored != "my_secret_key"  # 不是明文
        assert isinstance(stored, str)
        assert len(stored) > 0


# ================================================================
# 查询绑定
# ================================================================

class TestGetBindingById:
    def test_found(self, model):
        b = model.create_binding("n1", "u1", "app_001", "secret")
        result = model.get_binding_by_id(b["id"])
        assert result is not None
        assert result["app_id"] == "app_001"

    def test_not_found(self, model):
        assert model.get_binding_by_id(999) is None


class TestGetBindingByUser:
    def test_found(self, model):
        model.create_binding("n1", "u1", "app_001", "secret")
        results = model.get_binding_by_user("n1", "u1")
        assert results is not None
        assert len(results) >= 1
        # 可能是列表或单个记录
        if isinstance(results, list):
            assert any(b["app_id"] == "app_001" for b in results)
        else:
            assert results["app_id"] == "app_001"

    def test_not_found(self, model):
        result = model.get_binding_by_user("nobody", "nobody")
        # 可能是 []、None 或空列表
        assert result is None or result == [] or len(result) == 0

    def test_isolation(self, model):
        """用户之间隔离"""
        model.create_binding("n1", "u1", "app_001", "secret")
        result = model.get_binding_by_user("n2", "u2")
        assert result is None or result == [] or len(result) == 0


class TestGetBindingByAppId:
    def test_found(self, model):
        model.create_binding("n1", "u1", "app_001", "secret")
        result = model.get_binding_by_app_id("app_001")
        assert result is not None
        assert result["neuser_id"] == "n1"

    def test_not_found(self, model):
        assert model.get_binding_by_app_id("nonexistent") is None


class TestListUserBindings:
    def test_empty(self, model):
        assert model.list_user_bindings("nobody") == []

    def test_returns_user_bindings(self, model):
        model.create_binding("n1", "u1", "app_001", "secret")
        model.create_binding("n1", "u1", "app_002", "secret")
        model.create_binding("n2", "u2", "app_003", "secret")  # 不同用户
        bindings = model.list_user_bindings("n1")
        assert len(bindings) == 2
        app_ids = {b["app_id"] for b in bindings}
        assert app_ids == {"app_001", "app_002"}

    def test_returns_dicts(self, model):
        model.create_binding("n1", "u1", "app_001", "secret")
        bindings = model.list_user_bindings("n1")
        assert isinstance(bindings[0], dict)


# ================================================================
# 更新绑定
# ================================================================

class TestUpdateBinding:
    def test_update_status(self, model):
        b = model.create_binding("n1", "u1", "app_001", "secret")
        updated = model.update_binding(b["id"], status="disabled")
        assert updated is not None
        assert updated["status"] == "disabled"

    def test_update_secret(self, model):
        b = model.create_binding("n1", "u1", "app_001", "old_secret")
        updated = model.update_binding(b["id"], app_secret="new_secret")
        assert updated is not None
        # secret 应被加密存储
        assert updated["app_secret"] != "new_secret"

    def test_update_nonexistent(self, model):
        result = model.update_binding(999, status="disabled")
        assert result is None

    def test_update_empty_kwargs(self, model):
        b = model.create_binding("n1", "u1", "app_001", "secret")
        # 无有效字段，返回当前记录
        result = model.update_binding(b["id"])
        assert result is not None
        assert result["app_id"] == "app_001"


# ================================================================
# 删除绑定
# ================================================================

class TestDeleteBinding:
    def test_delete_existing(self, model):
        b = model.create_binding("n1", "u1", "app_001", "secret")
        ok = model.delete_binding(b["id"])
        assert ok is True
        assert model.get_binding_by_id(b["id"]) is None

    def test_delete_nonexistent(self, model):
        ok = model.delete_binding(999)
        assert ok is False


# ================================================================
# update_last_used
# ================================================================

class TestUpdateLastUsed:
    def test_updates_timestamp(self, model):
        b = model.create_binding("n1", "u1", "app_001", "secret")
        assert b["last_used_at"] is None
        model.update_last_used(b["id"])
        updated = model.get_binding_by_id(b["id"])
        assert updated["last_used_at"] is not None

    def test_idempotent(self, model):
        """多次调用不报错"""
        b = model.create_binding("n1", "u1", "app_001", "secret")
        model.update_last_used(b["id"])
        model.update_last_used(b["id"])


# ================================================================
# 加密/解密
# ================================================================

class TestEncryptDecrypt:
    def test_roundtrip(self, model):
        secret = "my_secret_key_123!@#"
        encrypted = model._encrypt_secret(secret)
        assert encrypted != secret
        decrypted = model._decrypt_secret(encrypted)
        assert decrypted == secret

    def test_encrypt_is_deterministic(self, model):
        """base64 编码是确定性的，相同输入产生相同输出"""
        s1 = model._encrypt_secret("same")
        s2 = model._encrypt_secret("same")
        assert s1 == s2

    def test_encrypt_masks_original(self, model):
        """加密结果不包含原始字符串"""
        encrypted = model._encrypt_secret("my_secret")
        assert "my_secret" not in encrypted

    def test_empty_string(self, model):
        encrypted = model._encrypt_secret("")
        decrypted = model._decrypt_secret(encrypted)
        assert decrypted == ""

    def test_unicode(self, model):
        secret = "中文密码🔑"
        encrypted = model._encrypt_secret(secret)
        decrypted = model._decrypt_secret(encrypted)
        assert decrypted == secret


# ================================================================
# _row_to_dict
# ================================================================

class TestRowToDict:
    def test_converts_all_columns(self, model):
        b = model.create_binding("n1", "u1", "app_001", "secret")
        conn = model._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM qclaw_bindings WHERE id=?", (b["id"],))
        row = cursor.fetchone()
        conn.close()
        d = model._row_to_dict(row)
        assert isinstance(d, dict)
        assert d["app_id"] == "app_001"
        assert d["neuser_id"] == "n1"
        assert "app_secret" in d
        assert "created_at" in d


# ================================================================
# close
# ================================================================

class TestClose:
    def test_close_does_not_crash(self, model):
        model.close()
        # 可重复关闭
        model.close()
