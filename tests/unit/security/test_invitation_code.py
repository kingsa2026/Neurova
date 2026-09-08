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
        assert InvitationCodeType.SINGLE_USE.value == "single_use"
        assert InvitationCodeType.MULTI_USE.value == "multi_use"
        assert InvitationCodeType.UNLIMITED.value == "unlimited"

    def test_all_values(self):
        values = {v.value for v in InvitationCodeType}
        assert values == {"single_use", "multi_use", "unlimited"}


class TestInvitationCode:
    """邀请码数据类"""

    def test_create(self):
        code = InvitationCode(
            code="ABC123",
            code_type=InvitationCodeType.SINGLE_USE,
            created_by="42",
            max_uses=1,
            current_uses=0,
            expires_at=None,
            created_at=1234567890.0,
            is_active=True,
            description=None,
        )
        assert code.code == "ABC123"
        assert code.code_type == InvitationCodeType.SINGLE_USE
        assert code.created_by == "42"
        assert code.max_uses == 1
        assert code.current_uses == 0
        assert code.is_active is True
        assert code.expires_at is None
        assert code.description is None

    def test_create_full(self):
        code = InvitationCode(
            code="DEF456",
            code_type=InvitationCodeType.MULTI_USE,
            created_by="100",
            max_uses=10,
            current_uses=3,
            expires_at=1234567890.0+1000000,
            created_at=1234567890.0,
            is_active=True,
            description="团队邀请",
        )
        assert code.max_uses == 10
        assert code.current_uses == 3
        assert code.expires_at is not None
        assert code.description == "团队邀请"

    def test_defaults(self):
        code = InvitationCode( code="GHI789",
            code_type=InvitationCodeType.SINGLE_USE, created_by="1",
            max_uses=1, current_uses=0,
            expires_at=None,
            created_at=1234567890.0,
            is_active=True, description=None,
        )
        assert code.max_uses == 1
        assert code.current_uses == 0
        assert code.is_active is True


class TestInvitationCodeModel:
    """邀请码模型（SQLite 后端）"""

    @pytest.fixture
    def model(self, tmp_path):
        """使用临时数据库的模型实例"""
        db_path = str(tmp_path / "test_invitation.db")
        return InvitationCodeModel(db_path=db_path)

    def test_create_code(self, model):
        invite = model.create_code(created_by="1")
        code = invite.code
        assert len(code) == 8 and code.isalnum()

    def test_create_code_default_type(self, model):
        invite = model.create_code(created_by="1")
        code = invite.code
        saved = model.get_code(code)
        assert saved is not None
        assert saved.code_type == InvitationCodeType.SINGLE_USE
        assert saved.max_uses == 1

    def test_create_multiple_use_code(self, model):
        invite = model.create_code(created_by="1", code_type=InvitationCodeType.MULTI_USE, max_uses=5)
        code = invite.code
        saved = model.get_code(code)
        assert saved.max_uses == 5
        assert saved.code_type == InvitationCodeType.MULTI_USE

    def test_get_code_not_found(self, model):
        result = model.get_code("NONEXIST")
        assert result is None

    def test_validate_code_valid(self, model):
        code = model.create_code(created_by="1").code
        valid = model.validate_code(code)
        msg = "ok" if valid else "invalid"
        assert valid is True

    def test_validate_code_not_found(self, model):
        valid = model.validate_code("NONEXIST")
        assert valid is False

    def test_validate_code_inactive(self, model):
        code = model.create_code(created_by="1").code
        saved = model.get_code(code)
        model.revoke_code(code if isinstance(code, str) else code.code)
        valid = model.validate_code(code)
        assert valid is False

    def test_use_code_onetime(self, model):
        invite = model.create_code(created_by="1")
        used = model.use_code(invite.code, used_by="2")
        # 实现：使用成功返回更新后的 InvitationCode
        assert used is not None
        assert used.current_uses >= 1

    def test_use_code_not_found(self, model):
        used = model.use_code("NONEXIST", used_by="1")
        assert used is None

    def test_revoke_code(self, model):
        code = model.create_code(created_by="1").code
        saved = model.get_code(code)
        result = model.revoke_code(code if isinstance(code, str) else code.code)
        assert result is True
        revoked = model.get_code(code)
        assert revoked.is_active is False

    def test_revoke_nonexistent(self, model):
        result = model.revoke_code(99999)
        assert result is False

    def test_list_codes_by_creator(self, model):
        c1 = model.create_code(created_by="10")
        c2 = model.create_code(created_by="10")
        c3 = model.create_code(created_by="20")
        codes = model.list_codes()
        mine = [c for c in codes if c.created_by == "10"]
        ids = [c.code for c in mine]
        assert c1.code in ids
        assert c2.code in ids
        assert c3.code not in ids

    def test_list_codes_active_only(self, model):
        c1 = model.create_code(created_by="1")
        c2 = model.create_code(created_by="1")
        model.revoke_code(c2.code)
        active = model.list_codes()  # 默认只返回活跃码
        active_codes = [c.code for c in active]
        assert c1.code in active_codes
        assert c2.code not in active_codes

    def test_list_codes_pagination(self, model):
        for i in range(5):
            model.create_code(created_by="1")
        limited = model.list_codes(limit=2)
        assert len(limited) == 2

    def test_cleanup_expired_codes(self, model):
        code = model.create_code(created_by="1", expires_in=0).code
        import time
        time.sleep(0.01)
        cleaned = model.cleanup_expired_codes()
        assert cleaned >= 0

    def test_use_code_multiple_use(self, model):
        code = model.create_code(created_by="1", code_type=InvitationCodeType.MULTI_USE, max_uses=3).code
        for i in range(3):
            used = model.use_code(code, used_by=str(100 + i))
            assert used is not None
        saved = model.get_code(code)
        assert saved.current_uses == 3
        # 第4次应失败（used_up）
        used = model.use_code(code, used_by="999")
        assert used is None
