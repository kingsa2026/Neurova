# -*- coding: utf-8 -*-
"""F3 红灯：neuacp 帧脱敏契约测试（设计文档 §3.3）。

双层：结构级=字段名命中→"[redacted]"；值级=复用记忆层单源
``neurova.security.sensitive_info.sanitizeSensitive``（sk-/ghp-/Bearer 等
值形状由单源覆盖）。计数键（*_tokens/tokens）与引用名（key_ref）不命中。
"""

from neurova.agent.neuacp.redaction import (
    CREDENTIAL_FIELD_RE,
    isCredentialField,
    redactFrame,
)


class TestCredentialFieldName:
    def test_credentialFieldRegexIsProvided(self):
        assert CREDENTIAL_FIELD_RE is not None
        assert CREDENTIAL_FIELD_RE.search("api_key")
        assert CREDENTIAL_FIELD_RE.search("ACCESS_TOKEN")

    def test_apiKeyAndAccessTokenHit(self):
        for name in ("api_key", "API_KEY", "apiKey", "api-key", "apikey",
                     "access_token", "accessToken", "Authorization",
                     "private_key", "refresh_token", "auth_token",
                     "personal_access_token", "credential", "secret",
                     "password", "passwd"):
            assert isCredentialField(name), f"{name!r} 应命中凭据字段名"

    def test_exactTokenAndPatHit(self):
        assert isCredentialField("token")
        assert isCredentialField("TOKEN")
        assert isCredentialField("pat")

    def test_usageCountFieldsNotHit(self):
        for name in ("input_tokens", "total_tokens", "output_tokens",
                     "cached_tokens", "tokens"):
            assert not isCredentialField(name), f"{name!r} 是 usage 计数，不得命中"

    def test_keyRefNotHit(self):
        assert not isCredentialField("key_ref"), "引用名非明文凭据"

    def test_exactMatchKeepsNearbyNamesClean(self):
        # token/pat 是恰等命中：邻近名不误伤
        assert not isCredentialField("token_count")
        assert not isCredentialField("patch")
        assert not isCredentialField("pattern")
        # authorization 是子串命中：含该词的复合字段名按规格打码（宁可宽）
        assert isCredentialField("authorization_policy_doc")

    def test_normalFieldsNotHit(self):
        for name in ("session_id", "content", "model", "path", "command"):
            assert not isCredentialField(name)


class TestRedactFrame:
    def test_structuralHitReplacesValueWithMarker(self):
        frame = {"api_key": "sk-abcdef1234567890", "model": "gpt"}
        out = redactFrame(frame)
        assert out["api_key"] == "[redacted]"
        assert out["model"] == "gpt"

    def test_nestedDictAndListRedactedEveryLevel(self):
        frame = {
            "params": {
                "access_token": "tok-1",
                "items": [
                    {"secret": "s-1"},
                    {"safe": "keep", "nested": {"password": "p-1"}},
                ],
            },
        }
        out = redactFrame(frame)
        assert out["params"]["access_token"] == "[redacted]"
        assert out["params"]["items"][0]["secret"] == "[redacted]"
        assert out["params"]["items"][1]["safe"] == "keep"
        assert out["params"]["items"][1]["nested"]["password"] == "[redacted]"

    def test_usageCountsAndKeyRefPreserved(self):
        frame = {"input_tokens": 12, "total_tokens": 34, "tokens": 7,
                 "key_ref": "vault/main"}
        out = redactFrame(frame)
        assert out == {"input_tokens": 12, "total_tokens": 34, "tokens": 7,
                       "key_ref": "vault/main"}

    def test_bareSecretValueShapesMasked(self):
        frame = {"note": "key is sk-abcdef1234567890 and ghp_ABCDEFGHIJKLMNOPQRST"}
        out = redactFrame(frame)
        assert "sk-abcdef1234567890" not in out["note"]
        assert "ghp_ABCDEFGHIJKLMNOPQRST" not in out["note"]
        assert "[redacted]" in out["note"]

    def test_bearerLiteralMasked(self):
        frame = {"header": "Bearer abcdef123456"}
        out = redactFrame(frame)
        assert "abcdef123456" not in out["header"]
        assert "[redacted]" in out["header"]

    def test_originalFrameNotMutated(self):
        frame = {"api_key": "sk-abcdef1234567890",
                 "items": [{"secret": "s-1"}]}
        redactFrame(frame)
        assert frame == {"api_key": "sk-abcdef1234567890",
                         "items": [{"secret": "s-1"}]}, "原帧不得被就地修改"

    def test_nonStringScalarsKeptAsIs(self):
        frame = {"n": 5, "b": True, "none": None, "arr": [1, "x", {"ok": 2}]}
        assert redactFrame(frame) == frame

    def test_emptyFrameReturnsEmpty(self):
        assert redactFrame({}) == {}
