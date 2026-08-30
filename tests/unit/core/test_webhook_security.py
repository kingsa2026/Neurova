"""
NeurFlow P1 Step 3 — Webhook 入站安全测试（HMAC 签名校验）

契约（neurova/core/webhook_security.py）：
- compute_signature(payload_bytes, secret) → "sha256=<hex>"（GitHub 风格）
- verify_signature(payload_bytes, secret, header_value) → bool
- 验签必须用 hmac.compare_digest（常量时间比较，防时序攻击）
- header 缺失/格式错误 → False（不抛异常）
- payload/secret 为空 → False

TDD：先红后绿。
"""
import hashlib
import hmac

from neurova.core.webhook_security import compute_signature, verify_signature


class TestComputeSignature:
    def test_signature_format_is_sha256_prefix(self):
        sig = compute_signature(b'{"a":1}', "secret-1")
        assert sig.startswith("sha256=")
        assert len(sig) == len("sha256=") + 64

    def test_signature_matches_github_style_hmac(self):
        payload = b'{"event":"push"}'
        secret = "topsecret"
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        assert compute_signature(payload, secret) == expected

    def test_signature_differs_per_secret(self):
        payload = b"payload"
        assert compute_signature(payload, "s1") != compute_signature(payload, "s2")


class TestVerifySignature:
    def test_valid_signature_passes(self):
        payload = b'{"ok":true}'
        secret = "shared-secret"
        sig = compute_signature(payload, secret)
        assert verify_signature(payload, secret, sig) is True

    def test_invalid_signature_rejected(self):
        payload = b'{"ok":true}'
        sig = compute_signature(payload, "wrong-secret")
        assert verify_signature(payload, "right-secret", sig) is False

    def test_tampered_payload_rejected(self):
        secret = "shared-secret"
        sig = compute_signature(b'{"amount":1}', secret)
        assert verify_signature(b'{"amount":100}', secret, sig) is False

    def test_missing_header_rejected(self):
        assert verify_signature(b"payload", "secret", None) is False
        assert verify_signature(b"payload", "secret", "") is False

    def test_malformed_header_rejected(self):
        # 无 sha256= 前缀
        assert verify_signature(b"payload", "secret", "deadbeef") is False
        # 前缀错误算法
        assert verify_signature(b"payload", "secret", "md5=deadbeef") is False

    def test_empty_secret_rejected(self):
        sig = compute_signature(b"payload", "s")
        assert verify_signature(b"payload", "", sig) is False

    def test_uses_constant_time_compare(self):
        """验签实现必须用 hmac.compare_digest（防时序侧信道）"""
        import inspect

        from neurova.core import webhook_security

        src = inspect.getsource(webhook_security)
        assert "compare_digest" in src

    def test_uppercase_hex_accepted(self):
        """hex 大小写不敏感（部分客户端会大写）"""
        payload = b"payload"
        secret = "s"
        sig = compute_signature(payload, secret).upper()
        assert verify_signature(payload, secret, sig) is True
