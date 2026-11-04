"""本机凭据密钥的 OS 级保护（P2-2，审计 2026-11-04）。

问题：`web_reach/credentials.py` 把 Fernet 密钥明文写在与密文同一个目录，
拿到文件读权限就同时拿到密钥与密文——加密只剩形式。

处置：Windows 走 DPAPI（`CryptProtectData`/`CryptUnprotectData`），密钥密文
只能由同一用户在同一台机器上解开；非 Windows 没有等价系统 API 时显式写
`plain:` 前缀并保持 0600，不冒充"已受 OS 保护"。

旧 keyfile（64 位 hex 明文）首次加载时就地迁移为 `dpapi:`，迁移失败按错误
抛出而不是悄悄继续用明文。
"""
from __future__ import annotations

import base64
import ctypes
import os
import secrets
from pathlib import Path
from typing import Optional

from neurova.core.logger import get_logger

logger = get_logger(__name__)

DPAPI_PREFIX = "dpapi:"
PLAIN_PREFIX = "plain:"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DataBlob(ctypes.Structure):
    _fields_ = [
        ("cbData", ctypes.c_uint32),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _blobOf(data: bytes) -> tuple[_DataBlob, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _DataBlob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))), buffer


def _dpapiProtect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.c_wchar_p, ctypes.POINTER(_DataBlob),
        ctypes.c_void_p, ctypes.POINTER(_DataBlob), ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptProtectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    inBlob, _buffer = _blobOf(data)
    outBlob = _DataBlob()
    if not crypt32.CryptProtectData(
        ctypes.byref(inBlob), "Neurova local secret", None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(outBlob),
    ):
        raise OSError(ctypes.get_last_error(), "CryptProtectData 失败")
    try:
        return ctypes.string_at(outBlob.pbData, outBlob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(outBlob.pbData, ctypes.c_void_p))


def _dpapiUnprotect(data: bytes) -> bytes:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(_DataBlob), ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.POINTER(_DataBlob),
        ctypes.c_uint32, ctypes.POINTER(_DataBlob),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.c_int
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p

    inBlob, _buffer = _blobOf(data)
    outBlob = _DataBlob()
    if not crypt32.CryptUnprotectData(
        ctypes.byref(inBlob), None, None, None, None,
        _CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(outBlob),
    ):
        raise OSError(ctypes.get_last_error(), "CryptUnprotectData 失败")
    try:
        return ctypes.string_at(outBlob.pbData, outBlob.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(outBlob.pbData, ctypes.c_void_p))


def protectSecret(secret: str) -> str:
    """把密钥包成可落盘文本：Windows 用 DPAPI，其余平台显式 plain:。"""
    if os.name == "nt":
        blob = _dpapiProtect(secret.encode("utf-8"))
        return DPAPI_PREFIX + base64.b64encode(blob).decode("ascii")
    return PLAIN_PREFIX + secret


def unprotectSecret(token: str) -> Optional[str]:
    """解回落盘文本；无法解开返回 None（调用方按错误处置，不静默降级）。"""
    text = str(token or "").strip()
    if text.startswith(DPAPI_PREFIX):
        if os.name != "nt":
            return None
        try:
            blob = base64.b64decode(text[len(DPAPI_PREFIX):], validate=True)
            return _dpapiUnprotect(blob).decode("utf-8")
        except (ValueError, OSError):
            return None
    if text.startswith(PLAIN_PREFIX):
        return text[len(PLAIN_PREFIX):]
    # 兼容旧格式：64 位 hex 明文
    return text or None


def _restrictPermissions(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:  # Windows 无 POSIX 权限位；DPAPI 已保证内容不可读
        pass


def loadOrCreateKeyfile(path: Path, *, purpose: str = "local secret") -> str:
    """读取或创建受保护密钥文件；旧明文就地迁移。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        secret = unprotectSecret(token)
        if not secret:
            raise RuntimeError(
                f"{purpose} 密钥文件无法解开（{path}）：文件损坏或不属于当前用户/机器"
            )
        if not token.startswith((DPAPI_PREFIX, PLAIN_PREFIX)):
            # 旧形态：明文 hex。迁移到 OS 保护，失败直接抛错。
            path.write_text(protectSecret(secret), encoding="utf-8")
            _restrictPermissions(path)
            logger.info("%s 密钥文件已迁移为受保护格式: %s", purpose, path)
        return secret

    secret = secrets.token_hex(32)
    path.write_text(protectSecret(secret), encoding="utf-8")
    _restrictPermissions(path)
    logger.info("Generated %s keyfile: %s", purpose, path)
    return secret
