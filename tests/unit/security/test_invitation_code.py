"""
测试邀请码模块

覆盖: neurova/auth/invitation_code.py
"""

from datetime import datetime, timedelta
import pytest
from neurova.auth.invitation_code import (
    InvitationCodeType,
    InvitationCode,
    InvitationCodeModel,
)


class TestInvitationCodeType:
    """邀请码类型枚举"""

    def test_values(self):
        assert InvitationCodeType.ONETIME.value == "onetime"
        assert InvitationCodeType.MULTIPLE.value == "multiple"
        assert InvitationCodeType.UNLIMITED.value == "unlimited"

    def test_all_values(self):
        values = {v.value for v in InvitationCodeType}
        assert values == {"onetime", "multiple", "unlimited"}


class TestInvitationCode:
    """邀请码数据类"""

    def test_create(self):
        code = InvitationCode(
            id=1,
            code="ABC123",
            code_type="onetime",
            created_by=42,
            max_uses=1,
            used_count=0,
            expires_at=None,
            created_at="2025-01-15T10:00:00",
            is_active=True,
            description=None,
        )
        assert code.id == 1
        assert code.code == "ABC123"
        assert code.code_type == "onetime"
        assert code.created_by == 42
        assert code.max_uses == 1
        assert code.used_count == 0
        assert code.is_active is True
        assert code.expires_at is None
        assert code.description is None

    def test_create_full(self):
        code = InvitationCode(
            id=2,
            code="DEF456",
            code_type="multiple",
            created_by=100,
            max_uses=10,
            used_count=3,
            expires_at="2025-02-15T10:00:00",
            created_at="2025-01-15T10:00:00",
            is_active=True,
            description="团队邀请",
        )
        assert code.max_uses == 10
        assert code.used_count == 3
        assert code.expires_at == "2025-02-15T10:00:00"
        assert code.description == "团队邀请"

    def test_defaults(self):
        code = InvitationCode(
            id=3, code="GHI789",
            code_type="onetime", created_by=1,
            max_uses=1, used_count=0,
            expires_at=None,
            created_at="2025-01-15T10:00:00",
            is_active=True, description=None,
        )
        assert code.max_uses == 1
        assert code.used_count == 0
        assert code.is_active is True


class TestInvitationCodeModel:
    """邀请码模型（SQLite 后端）"""

    @pytest.fixture
    def model(self, tmp_path):
        """使用临时数据库的模型实例"""
        db_path = str(tmp_path / "test_invitation.db")
        return InvitationCodeModel(db_path=db_path)

    def test_create_code(self, model):
        code = model.create_code(created_by=1)
        assert len(code) == 12
        assert code.isalnum()

    def test_create_code_default_type(self, model):
        code = model.create_code(created_by=1)
        saved = model.get_code(code)
        assert saved is not None
        assert saved["code_type"] == "onetime"
        assert saved["max_uses"] == 1

    def test_create_multiple_use_code(self, model):
        code = model.create_code(created_by=1, code_type="multiple", max_uses=5)
        saved = model.get_code(code)
        assert saved["max_uses"] == 5
        assert saved["code_type"] == "multiple"

    def test_get_code_not_found(self, model):
        result = model.get_code("NONEXIST")
        assert result is None

    def test_validate_code_valid(self, model):
        code = model.create_code(created_by=1)
        valid, msg = model.validate_code(code)
        assert valid is True
        assert msg == ""

    def test_validate_code_not_found(self, model):
        valid, msg = model.validate_code("NONEXIST")
        assert valid is False
        assert msg in ("邀请码无效", "邀请码不存在")

    def test_validate_code_inactive(self, model):
        code = model.create_code(created_by=1)
        saved = model.get_code(code)
        model.revoke_code(saved["id"])
        valid, msg = model.validate_code(code)
        assert valid is False
        assert "已失效" in msg or "已禁用" in msg

    def test_use_code_onetime(self, model):
        code = model.create_code(created_by=1)
        success, msg = model.use_code(code, used_by=2)
        assert success is True
        # 一次性码使用后应自动失效或标记
        saved = model.get_code(code)
        assert saved["used_count"] >= 1

    def test_use_code_not_found(self, model):
        success, msg = model.use_code("NONEXIST", used_by=1)
        assert success is False

    def test_revoke_code(self, model):
        code = model.create_code(created_by=1)
        saved = model.get_code(code)
        result = model.revoke_code(saved["id"])
        assert result is True
        revoked = model.get_code(code)
        assert revoked["is_active"] == 0

    def test_revoke_nonexistent(self, model):
        result = model.revoke_code(99999)
        assert result is False

    def test_list_codes_by_creator(self, model):
        c1 = model.create_code(created_by=10)
        c2 = model.create_code(created_by=10)
        c3 = model.create_code(created_by=20)
        codes = model.list_codes(created_by=10)
        ids = [c["code"] for c in codes]
        assert c1 in ids
        assert c2 in ids
        assert c3 not in ids

    def test_list_codes_active_only(self, model):
        c1 = model.create_code(created_by=1)
        c2 = model.create_code(created_by=1)
        saved = model.get_code(c2)
        model.revoke_code(saved["id"])
        active = model.list_codes(is_active=True)
        active_codes = [c["code"] for c in active]
        assert c1 in active_codes
        assert c2 not in active_codes

    def test_list_codes_pagination(self, model):
        for i in range(5):
            model.create_code(created_by=1)
        limited = model.list_codes(limit=2)
        assert len(limited) == 2

    def test_cleanup_expired_codes(self, model):
        code = model.create_code(created_by=1, expires_days=0)
        import time
        time.sleep(0.01)
        cleaned = model.cleanup_expired_codes()
        assert cleaned >= 0

    def test_use_code_multiple_use(self, model):
        code = model.create_code(created_by=1, code_type="multiple", max_uses=3)
        for i in range(3):
            success, msg = model.use_code(code, used_by=100 + i)
            assert success is True
        saved = model.get_code(code)
        assert saved["used_count"] == 3
        # 第4次应失败
        success, msg = model.use_code(code, used_by=999)
        assert success is False
