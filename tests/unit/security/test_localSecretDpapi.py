# -*- coding: utf-8 -*-
"""P2-2（审计 2026-11-04）：本机凭据密钥不得与密文同以明文落盘。

Windows 走 DPAPI：keyfile 里是 `dpapi:` 密文，只有同一用户/机器能解开；
旧 64 位 hex 明文在首次加载时迁移；解不开按错误抛出，不静默回退明文。
"""
import os

import pytest

from neurova.security.local_key_protection import (
    DPAPI_PREFIX,
    loadOrCreateKeyfile,
    protectSecret,
    unprotectSecret,
)

pytestmark = pytest.mark.skipif(os.name != "nt", reason="DPAPI 仅 Windows")


def test_dpapiRoundTripDoesNotLeakPlaintext():
    secret = "a" * 64
    token = protectSecret(secret)
    assert token.startswith(DPAPI_PREFIX)
    assert secret not in token, "DPAPI 输出里仍能看到明文密钥"
    assert unprotectSecret(token) == secret


def test_keyfileIsProtectedAndReloadsSameSecret(tmp_path):
    path = tmp_path / "_keyfile"
    first = loadOrCreateKeyfile(path, purpose="probe")
    raw = path.read_text(encoding="utf-8")
    assert raw.startswith(DPAPI_PREFIX)
    assert first not in raw, "keyfile 里仍能直接读到密钥"
    assert loadOrCreateKeyfile(path, purpose="probe") == first


def test_legacyPlaintextKeyfileIsMigratedInPlace(tmp_path):
    path = tmp_path / "_keyfile"
    legacy = "b" * 64
    path.write_text(legacy, encoding="utf-8")

    assert loadOrCreateKeyfile(path, purpose="probe") == legacy
    migrated = path.read_text(encoding="utf-8")
    assert migrated.startswith(DPAPI_PREFIX), "旧明文没有迁移"
    assert legacy not in migrated
    assert unprotectSecret(migrated) == legacy


def test_corruptProtectedKeyfileFailsLoudly(tmp_path):
    path = tmp_path / "_keyfile"
    path.write_text(DPAPI_PREFIX + "not-base64!!", encoding="utf-8")
    with pytest.raises(RuntimeError, match="无法解开"):
        loadOrCreateKeyfile(path, purpose="probe")
