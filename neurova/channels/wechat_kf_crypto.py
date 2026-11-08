"""企业微信回调协议加解密单源（EncodingAESKey 协议）＋会话存档 RSA 半边。

微信客服（kf）面与自建应用回调面（wecom.py）共用本模块——签名公式、AES-CBC
加解密、PKCS7、receiveId（corpid）校验只此一份，两处各写一遍必然在某处放宽。

会话存档（批 C7b，方案 §5/§16-1）的解密链是「RSA 本仓半边＋官方 SDK 内 AES」：
`encrypt_random_key` base64 → RSA PKCS1 私钥解密 → `encrypt_key`，随后连同
`encrypt_chat_msg` 交官方 `DecryptData` 出明文。AES-CBC 由 SDK 内部完成，
本仓不实现也不该实现（存档模块再写一份即第二套实装，test_wecomCryptoSingleSource
以 AST 反证钉住）——故 RSA 是本模块新增的唯一形状。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BLOCK_SIZE = 32


def callbackSignature(token: str, timestamp: str, nonce: str, encrypt: str) -> str:
    """官方签名公式（文档 91144）：SHA1(sort(token, timestamp, nonce, encrypt))。

    SHA1 为平台强制互操作算法（非本实现的安全选择）；
    明文模式回调体无 Encrypt 字段时，encrypt 传空串。
    """
    raw = "".join(sorted([token, timestamp, nonce, encrypt]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def verifyKfSignature(
    token: str, timestamp: str, nonce: str, encrypt: str, msgSignature: str
) -> None:
    """SHA1(sort(token,timestamp,nonce,encrypt))；不匹配抛 ValueError。"""
    if not token or not msgSignature:
        raise ValueError("WeCom callback rejected: callback token/signature missing")
    expected = callbackSignature(token, timestamp, nonce, encrypt)
    if not hmac.compare_digest(expected, msgSignature):
        raise ValueError("WeCom callback rejected: msg_signature mismatch")


def _aesKey(encodingAesKey: str) -> bytes:
    raw = (encodingAesKey or "").strip()
    raw += "=" * (-len(raw) % 4)
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("WeCom callback rejected: invalid EncodingAESKey") from exc
    if len(key) != _BLOCK_SIZE:
        raise ValueError("WeCom callback rejected: EncodingAESKey must decode to 32 bytes")
    return key


def _pad(data: bytes) -> bytes:
    pad = _BLOCK_SIZE - (len(data) % _BLOCK_SIZE)
    return data + bytes([pad]) * pad


def _unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("WeCom callback rejected: empty plaintext")
    pad = data[-1]
    if pad < 1 or pad > _BLOCK_SIZE or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("WeCom callback rejected: invalid PKCS7 padding")
    return data[:-pad]


def decryptKfPayload(encodingAesKey: str, encrypt: str, receiveId: str = "") -> str:
    """解密回调/echo 密文；receiveId 非空时必须是回调体的 corpid。"""
    key = _aesKey(encodingAesKey)
    try:
        cipherText = base64.b64decode(encrypt or "", validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("WeCom callback rejected: invalid base64 payload") from exc
    decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    plain = _unpad(decryptor.update(cipherText) + decryptor.finalize())
    if len(plain) < 20:
        raise ValueError("WeCom callback rejected: plaintext too short")
    msgLen = struct.unpack(">I", plain[16:20])[0]
    if 20 + msgLen > len(plain):
        raise ValueError("WeCom callback rejected: invalid message length")
    message = plain[20:20 + msgLen].decode("utf-8", errors="replace")
    actualReceiveId = plain[20 + msgLen:].decode("utf-8", errors="replace")
    if receiveId and actualReceiveId and not hmac.compare_digest(receiveId, actualReceiveId):
        raise ValueError("WeCom callback rejected: receiveId mismatch")
    return message


def encryptKfPayload(
    encodingAesKey: str, message: str, receiveId: str = "", randomPrefix: bytes = b"0123456789abcdef"
) -> str:
    """测试/自检用的反向实现；生产只解密。"""
    key = _aesKey(encodingAesKey)
    body = message.encode("utf-8")
    plain = _pad(randomPrefix[:16] + struct.pack(">I", len(body)) + body + receiveId.encode("utf-8"))
    encryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).encryptor()
    return base64.b64encode(encryptor.update(plain) + encryptor.finalize()).decode("ascii")


def decryptArchiveRandomKey(encryptRandomKeyB64: str, privateKeyPem: bytes) -> bytes:
    """会话存档解密链的 RSA 半边（批 C7b，方案 §5/§16-1）。

    `encrypt_random_key`（base64）→ RSA PKCS1 私钥解密 → `encrypt_key`（官方
    `DecryptData` 的 AES 密钥）。失败一律显式抛 ValueError，**不静默返回密文**；
    异常文案不回显密文/私钥内容。
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import padding

    try:
        sealed = base64.b64decode(encryptRandomKeyB64 or "", validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "WeCom archive rejected: encrypt_random_key 不是合法 base64（内容不回显）") from exc
    try:
        key = serialization.load_pem_private_key(privateKeyPem or b"", password=None)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(
            "WeCom archive rejected: 私钥不可解析（publickey_ver 映射错误？内容不回显）") from exc
    try:
        recovered = key.decrypt(sealed, padding.PKCS1v15())
    except ValueError as exc:
        raise ValueError(
            "WeCom archive rejected: RSA 解密失败——密文与该版本私钥不匹配或已损坏"
            "（内容不回显）") from exc
    # 错钥/损坏密文下 cryptography 的 PKCS1v15 解密**可能不抛而返回垃圾**（实测），
    # 而 encrypt_key 是给官方 DecryptData 做 AES 的密钥——长度只可能是 16/24/32
    # （AES 全部合法钥长）。链的数学必然：越界长度必不是 encrypt_key，当场显式抛，
    # 不让垃圾流进 SDK（方案 §5：RSA 失败即显式抛，不静默）。
    if len(recovered) not in (16, 24, 32):
        raise ValueError(
            "WeCom archive rejected: RSA 解出长度 %d 不是合法 AES 密钥长度——"
            "密文与该版本私钥不匹配或已损坏（内容不回显）" % len(recovered))
    return recovered
