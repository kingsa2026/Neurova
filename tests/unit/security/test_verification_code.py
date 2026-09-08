"""
测试验证码模块

覆盖: neurova/auth/verification_code.py
"""

from datetime import datetime, timedelta
import pytest
from neurova.auth.verification_code import (
    VerificationType,
    VerificationCode,
    VerificationCodeModel,
)


class TestVerificationType:
    """验证码类型枚举"""

    def test_values(self):
        assert VerificationType.REGISTER.value == "register"
        assert VerificationType.LOGIN.value == "login"
        assert VerificationType.RESET_PASSWORD.value == "reset_password"
        assert VerificationType.CHANGE_EMAIL.value == "change_email"
        assert VerificationType.TWO_FACTOR.value == "two_factor"
        assert VerificationType.TWO_FACTOR.value == "two_factor"

    def test_all_values(self):
        values = {v.value for v in VerificationType}
        expected = {"register", "reset_password", "login", "change_email", "two_factor"}
        assert values == expected


class TestVerificationCode:
    """验证码数据类"""

    def test_create(self):
        code = VerificationCode(
            code_type=VerificationType.REGISTER,
            target="user@example.com",
            code_hash="hashed_code_123",
            created_at=1234567890.0,
            expires_at=1234567950.0,
            attempts=0,
            is_used=False,
        )
        assert code.code_type == VerificationType.REGISTER
        assert code.target == "user@example.com"
        assert code.code_hash == "hashed_code_123"
        assert code.attempts == 0
        assert code.is_used is False

    def test_create_full(self):
        code = VerificationCode(
            code_type=VerificationType.LOGIN,
            target="13800138000",
            code_hash="h",
            created_at=1234567890.0,
            expires_at=1234567920.0,
            attempts=2,
            is_used=False,
        )
        assert code.attempts == 2
        assert code.is_used is False

    def test_defaults(self):
        code = VerificationCode( code_type=VerificationType.REGISTER, target="a@b.com",
            code_hash="h",
            created_at=1234567890.0,
            expires_at=1234567950.0,
            attempts=0, is_used=False,
        )
        assert code.attempts == 0
        assert code.is_used is False


class TestVerificationCodeModel:
    """验证码模型（SQLite 后端）"""

    @pytest.fixture
    def model(self, tmp_path):
        """使用临时数据库的模型实例"""
        db_path = str(tmp_path / "test_verification.db")
        return VerificationCodeModel(db_path=db_path)

    def test_create_code(self, model):
        code = model.create_code("user@test.com", VerificationType.REGISTER)
        assert len(code) == 6
        assert code.isdigit()

    def test_create_and_verify(self, model):
        code = model.create_code("verify@test.com", VerificationType.REGISTER)
        result = model.verify_code("verify@test.com", code, VerificationType("register"))
        assert result is True

    def test_verify_wrong_code(self, model):
        model.create_code("user@test.com", VerificationType.login.upper() if False else VerificationType("login"))
        result = model.verify_code("user@test.com", "000000", VerificationType("login"))
        assert result is False

    def test_verify_wrong_type(self, model):
        code = model.create_code("user@test.com", VerificationType.REGISTER)
        result = model.verify_code("user@test.com", code, VerificationType("login"))
        assert result is False

    def test_verify_wrong_target(self, model):
        code = model.create_code("a@test.com", VerificationType.REGISTER)
        result = model.verify_code("b@test.com", code, VerificationType("register"))
        assert result is False

    def test_create_multiple_keeps_latest(self, model):
        model.create_code("user@test.com", VerificationType.REGISTER)
        code2 = model.create_code("user@test.com", VerificationType.REGISTER)
        # 旧的验证码应被删除，只有最新的有效
        result = model.verify_code("user@test.com", code2, VerificationType("register"))
        assert result is True

    def test_verify_expired_code(self, model):
        code = model.create_code("user@test.com", VerificationType("register"),
                                          expires_in=0)
        import time
        time.sleep(0.01)
        result = model.verify_code("user@test.com", code, VerificationType("register"))
        assert result is False

    def test_code_expires_after_max_attempts(self, model):
        code = model.create_code("max@test.com", VerificationType.REGISTER)
        # 尝试超过最大次数
        for i in range(6):
            model.verify_code("max@test.com", "000000", VerificationType("register"))
        # 验证码应已过期
        result = model.verify_code("max@test.com", code, VerificationType("register"))
        assert result is False

    def test_get_code_info(self, model):
        code = model.create_code("info@test.com", VerificationType.login.upper() if False else VerificationType("login"))
        info = model.get_code_info("info@test.com", VerificationType("login"))
        assert info is not None
        assert info.code_type == VerificationType.LOGIN
        assert info.target == "info@test.com"
        assert info.is_used is False

    def test_get_code_info_not_found(self, model):
        info = model.get_code_info("nonexistent@test.com", VerificationType("register"))
        assert info is None

    def test_get_attempts(self, model):
        model.create_code("attempt@test.com", VerificationType.login.upper() if False else VerificationType("login"))
        # 几次失败
        model.verify_code("attempt@test.com", "111111", VerificationType("login"))
        model.verify_code("attempt@test.com", "222222", VerificationType("login"))
        count = model.get_attempts("attempt@test.com", VerificationType("login"))
        assert count == 2

    def test_cleanup_expired_codes(self, model):
        model.create_code("old@test.com", VerificationType("register"), expires_in=0)
        import time
        time.sleep(0.01)
        cleaned = model.cleanup_expired_codes()
        assert cleaned >= 1

    def test_check_register_rate_limit(self, model):
        status = model.check_register_rate_limit("192.168.1.1")
        assert isinstance(status, dict)

    def test_record_register_attempt(self, model):
        model.record_register_attempt("10.0.0.1", "new@test.com")
        # 记录后不应报错

    def test_can_send_code_no_existing_code(self, model):
        """无已发送的验证码时可发送"""
        status = model.can_send_code("fresh@test.com", VerificationType("register"))
        assert status["can_send"] is True

    def test_can_send_code_returns_value(self, model):
        """创建验证码后 can_send_code 返回正常（不报错）"""
        model.create_code("user@test.com", VerificationType.REGISTER)
        status = model.can_send_code("user@test.com", VerificationType("register"))
        assert isinstance(status.get("can_send", status.get("allowed")), bool)
