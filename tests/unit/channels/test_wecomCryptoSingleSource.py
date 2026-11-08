# -*- coding: utf-8 -*-
"""批 C7b：解密单源扩展——存档面只有 RSA 半边在本仓（方案 §5/§7/§11 C7b 第二行）。

判据：
- RSA PKCS1 半边落在 `wechat_kf_crypto`（回调 AES 与存档 RSA 共用一份加解密模块，
  不在存档模块另起炉灶——教义第 6/7 条）；
- **存档模块内不得出现 AES/Cipher 构造**：AES 半边在官方 `DecryptData` 内（C7a 核查
  更正，方案 §16-1），本仓再写一份即第二套实装——AST 判据吃源码文本，不 import
  被测模块，缺席时判据照红（红在行为断言上，不红在 import）；
- RSA 失败即显式抛 ValueError，**不静默返回密文**（方案 §5 硬纪律），
  且异常文案不回显密文内容。
"""
from __future__ import annotations

import ast
import base64
from pathlib import Path

import pytest

from neurova.channels import wechat_kf_crypto

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE_SOURCE = PROJECT_ROOT / "neurova" / "channels" / "wecom_archive.py"
CRYPTO_SOURCE = PROJECT_ROOT / "neurova" / "channels" / "wechat_kf_crypto.py"


@pytest.fixture()
def decryptArchiveRandomKey():
    """懒取被测函数：缺席时红在本用例体（AttributeError），不红在整档收集。"""
    fn = getattr(wechat_kf_crypto, "decryptArchiveRandomKey", None)
    if fn is None:
        pytest.fail("wechat_kf_crypto.decryptArchiveRandomKey 未实现（RSA 半边缺席）")
    return fn


def _rsaKeyPair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key, pem, key.public_key()


def test_rsa_pkcs1_roundtrip_recovers_encrypt_key(decryptArchiveRandomKey):
    """官方解密链：encrypt_random_key(base64) → RSA PKCS1 私钥解密 → encrypt_key。"""
    from cryptography.hazmat.primitives.asymmetric import padding

    _priv, pem, pub = _rsaKeyPair()
    plainKey = b"0123456789abcdef0123456789abcdef"
    sealed = base64.b64encode(pub.encrypt(plainKey, padding.PKCS1v15())).decode("ascii")
    assert decryptArchiveRandomKey(sealed, pem) == plainKey


def test_rsa_failure_raises_without_echoing_ciphertext(decryptArchiveRandomKey):
    """密文与私钥版本不匹配 → 显式抛，文案不回显密文（§5：不静默返回密文）。"""
    from cryptography.hazmat.primitives.asymmetric import padding

    _priv1, pem1, _pub1 = _rsaKeyPair()
    _priv2, _pem2, pub2 = _rsaKeyPair()
    sealed = base64.b64encode(pub2.encrypt(b"B" * 32, padding.PKCS1v15())).decode("ascii")
    with pytest.raises(ValueError) as excinfo:
        decryptArchiveRandomKey(sealed, pem1)
    assert sealed not in str(excinfo.value)
    assert "B" * 8 not in str(excinfo.value)


def test_bad_base64_random_key_raises(decryptArchiveRandomKey):
    with pytest.raises(ValueError):
        decryptArchiveRandomKey("!!not-base64!!", b"-----BEGIN NOPE-----")


def test_archive_module_has_no_aes_cipher():
    """AES 半边在官方 DecryptData 内——存档模块出现 ciphers/Cipher/AES 即第二套实装。"""
    archiveTree = ast.parse(ARCHIVE_SOURCE.read_text(encoding="utf-8"))
    for node in ast.walk(archiveTree):
        if isinstance(node, ast.ImportFrom):
            assert "ciphers" not in (node.module or ""), (
                "存档模块不得引入 AES/Cipher（AES 在官方 DecryptData 内，方案 §5/§16-1）")
            for alias in node.names:
                assert "Cipher" not in alias.name and "AES" not in alias.name, (
                    "存档模块不得引入 AES/Cipher（AES 在官方 DecryptData 内）")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "ciphers" not in (alias.name or "")
    # 反证（判据真阳性形状）：crypto 单源里 AES 的 import 确实存在，本判据不是恒真
    cryptoTree = ast.parse(CRYPTO_SOURCE.read_text(encoding="utf-8"))
    assert any(
        isinstance(n, ast.ImportFrom) and "ciphers" in (n.module or "")
        for n in ast.walk(cryptoTree)
    ), "判据失真：crypto 单源里找不到 AES import，AST 反证失效"


def test_rsa_half_lives_in_crypto_module_not_archive():
    """RSA 半边的定义点在 wechat_kf_crypto；存档模块只 import 消费（单源）。"""
    assert hasattr(wechat_kf_crypto, "decryptArchiveRandomKey"), (
        "RSA 半边必须落在 wechat_kf_crypto（与回调 AES 共用一份模块）")
    archiveText = ARCHIVE_SOURCE.read_text(encoding="utf-8")
    archiveNames = {
        node.name
        for node in ast.walk(ast.parse(archiveText))
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "decryptArchiveRandomKey" not in archiveNames, (
        "RSA 解密不得在存档模块里再定义一份（教义第 6 条）")
    assert "decryptArchiveRandomKey" in archiveText, (
        "存档读取面须实际消费 RSA 半边（判据咬合，不是挂名）")
