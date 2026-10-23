"""企业微信客服回调的签名与 AES 加解密（EncodingAESKey 协议）。"""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_BLOCK_SIZE = 32


def verifyKfSignature(
    token: str, timestamp: str, nonce: str, encrypt: str, msgSignature: str
) -> None:
    """SHA1(sort(token,timestamp,nonce,encrypt))；不匹配抛 ValueError。"""
    if not token or not msgSignature:
        raise ValueError("WeCom kf callback rejected: callback token/signature missing")
    expected = hashlib.sha1(
        "".join(sorted([token, timestamp, nonce, encrypt])).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(expected, msgSignature):
        raise ValueError("WeCom kf callback rejected: msg_signature mismatch")


def _aesKey(encodingAesKey: str) -> bytes:
    raw = (encodingAesKey or "").strip()
    raw += "=" * (-len(raw) % 4)
    try:
        key = base64.b64decode(raw, validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("WeCom kf callback rejected: invalid EncodingAESKey") from exc
    if len(key) != _BLOCK_SIZE:
        raise ValueError("WeCom kf callback rejected: EncodingAESKey must decode to 32 bytes")
    return key


def _pad(data: bytes) -> bytes:
    pad = _BLOCK_SIZE - (len(data) % _BLOCK_SIZE)
    return data + bytes([pad]) * pad


def _unpad(data: bytes) -> bytes:
    if not data:
        raise ValueError("WeCom kf callback rejected: empty plaintext")
    pad = data[-1]
    if pad < 1 or pad > _BLOCK_SIZE or data[-pad:] != bytes([pad]) * pad:
        raise ValueError("WeCom kf callback rejected: invalid PKCS7 padding")
    return data[:-pad]


def decryptKfPayload(encodingAesKey: str, encrypt: str, receiveId: str = "") -> str:
    """解密回调/echo 密文；receiveId 非空时必须是回调体的 corpid。"""
    key = _aesKey(encodingAesKey)
    try:
        cipherText = base64.b64decode(encrypt or "", validate=True)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("WeCom kf callback rejected: invalid base64 payload") from exc
    decryptor = Cipher(algorithms.AES(key), modes.CBC(key[:16])).decryptor()
    plain = _unpad(decryptor.update(cipherText) + decryptor.finalize())
    if len(plain) < 20:
        raise ValueError("WeCom kf callback rejected: plaintext too short")
    msgLen = struct.unpack(">I", plain[16:20])[0]
    if 20 + msgLen > len(plain):
        raise ValueError("WeCom kf callback rejected: invalid message length")
    message = plain[20:20 + msgLen].decode("utf-8", errors="replace")
    actualReceiveId = plain[20 + msgLen:].decode("utf-8", errors="replace")
    if receiveId and actualReceiveId and not hmac.compare_digest(receiveId, actualReceiveId):
        raise ValueError("WeCom kf callback rejected: receiveId mismatch")
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
