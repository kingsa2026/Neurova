# -*- coding: utf-8 -*-
"""NeurFlow Webhook 入站安全测试（HMAC + 时间戳时效）。"""

import hashlib
import hmac
import time

from neurova.core.webhook_security import (
    compute_signature,
    compute_signed_payload_signature,
    verify_request,
)


class TestComputeSignature:
    def test_signature_format_is_sha256_prefix(self):
        sig = compute_signature(b'{"a":1}', "secret-1")
        assert sig.startswith("sha256=")
        assert len(sig) == len("sha256=") + 64

    def test_signature_matches_hmac(self):
        payload = b'{"event":"push"}'
        secret = "topsecret"
        expected = "sha256=" + hmac.new(
            secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        assert compute_signature(payload, secret) == expected

    def test_signature_differs_per_secret(self):
        assert compute_signature(b"payload", "s1") != compute_signature(b"payload", "s2")


class TestVerifyRequest:
    def test_valid_signed_request_passes(self):
        payload = b'{"ok":true}'
        secret = "shared-secret"
        timestamp = str(int(time.time()))
        signature = compute_signed_payload_signature(timestamp, payload, secret)
        assert verify_request(payload, secret, signature, timestamp) == (True, "OK")

    def test_invalid_signature_rejected(self):
        payload = b'{"ok":true}'
        timestamp = str(int(time.time()))
        signature = compute_signed_payload_signature(timestamp, payload, "wrong-secret")
        assert verify_request(payload, "right-secret", signature, timestamp) == (
            False, "INVALID_SIGNATURE")

    def test_tampered_payload_rejected(self):
        secret = "shared-secret"
        timestamp = str(int(time.time()))
        signature = compute_signed_payload_signature(timestamp, b'{"amount":1}', secret)
        assert verify_request(b'{"amount":100}', secret, signature, timestamp) == (
            False, "INVALID_SIGNATURE")

    def test_missing_signature_rejected(self):
        timestamp = str(int(time.time()))
        assert verify_request(b"payload", "secret", None, timestamp) == (
            False, "MISSING_SIGNATURE")

    def test_missing_timestamp_rejected(self):
        signature = compute_signed_payload_signature("123", b"payload", "secret")
        assert verify_request(b"payload", "secret", signature, None) == (
            False, "MISSING_TIMESTAMP")

    def test_malformed_signature_rejected(self):
        timestamp = str(int(time.time()))
        assert verify_request(b"payload", "secret", "deadbeef", timestamp) == (
            False, "INVALID_SIGNATURE")
        assert verify_request(b"payload", "secret", "md5=deadbeef", timestamp) == (
            False, "INVALID_SIGNATURE")

    def test_empty_secret_rejected(self):
        timestamp = str(int(time.time()))
        signature = compute_signed_payload_signature(timestamp, b"payload", "s")
        assert verify_request(b"payload", "", signature, timestamp) == (
            False, "MISSING_SIGNATURE")

    def test_uses_constant_time_compare(self):
        import inspect

        from neurova.core import webhook_security

        assert "compare_digest" in inspect.getsource(webhook_security)

    def test_uppercase_hex_accepted(self):
        payload = b"payload"
        secret = "s"
        timestamp = str(int(time.time()))
        signature = compute_signed_payload_signature(timestamp, payload, secret).upper()
        assert verify_request(payload, secret, signature, timestamp) == (True, "OK")
