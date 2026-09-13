# -*- coding: utf-8 -*-
"""密钥静态加密存储（P2-3，Codex keyring+回退链对齐）。

- data/shared_config.json 中的 provider api_key 由明文 JSON 字段升级为
  Fernet 加密（"enc:v1:" 前缀标记），读侧解密、写侧加密——存量明文兼容
  （读侧原样透传，下次保存自动迁移为密文）
- 密钥通道三级：env NEUROVA_SECRET_KEY → keyring（服务名 "Neurova"）→
  data/.secret_key 文件（自动生成；POSIX chmod 0600，Windows 无 POSIX 权限位，
  目录 ACL 承担隔离——与 codex auth.json 0600 回退同构）
- 任何加解密异常 fail-open 返回原值（不因加密层故障瘫痪配置读写）
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

from neurova.core.logger import get_logger

logger = get_logger(__name__)

_ENC_PREFIX = "enc:v1:"
_KEY_FILE = "data/.secret_key"
_KEYRING_SERVICE = "Neurova"
_KEYRING_ENTRY = "config-secret-key"


def _load_or_create_key() -> bytes:
    """密钥获取链：env → keyring → 文件（自动生成）。"""
    env_key = os.environ.get("NEUROVA_SECRET_KEY", "")
    if env_key:
        return env_key.encode("utf-8")
    try:
        import keyring

        stored = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ENTRY)
        if stored:
            return stored.encode("utf-8")
    except Exception:  # noqa: BLE001 - keyring 不可用走文件
        pass
    path = Path(_KEY_FILE)
    if path.is_file():
        try:
            data = path.read_bytes().strip()
            if data:
                return data
        except OSError:
            pass
    import secrets

    new_key = secrets.token_urlsafe(32).encode("utf-8")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(new_key)
        try:
            os.chmod(path, 0o600)
        except OSError:  # noqa: BLE001 - Windows 无 POSIX 权限位
            pass
    except OSError as e:
        logger.error("密钥文件写入失败: %s", e)
    return new_key


def encrypt_secret(value: str) -> str:
    """明文 → "enc:v1:<fernet>"；空值/异常原样返回（fail-open）。"""
    text = str(value or "")
    if not text or text.startswith(_ENC_PREFIX):
        return text
    try:
        from cryptography.fernet import Fernet
        import base64

        key = _load_or_create_key()
        # token_urlsafe 密钥长度不定 → sha256 派生 Fernet 合规 32B key
        digest = __import__("hashlib").sha256(key).digest()
        fernet = Fernet(base64.urlsafe_b64encode(digest))
        return _ENC_PREFIX + fernet.encrypt(text.encode("utf-8")).decode("utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("密钥加密失败(存明文): %s", e)
        return text


def decrypt_secret(value: str) -> str:
    """"enc:v1:..." → 明文；无前缀（存量明文/空值）原样返回。"""
    text = str(value or "")
    if not text.startswith(_ENC_PREFIX):
        return text
    try:
        from cryptography.fernet import Fernet
        import base64
        import hashlib

        key = _load_or_create_key()
        digest = hashlib.sha256(key).digest()
        fernet = Fernet(base64.urlsafe_b64encode(digest))
        return fernet.decrypt(text[len(_ENC_PREFIX):].encode("utf-8")).decode("utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("密钥解密失败(返回原值): %s", e)
        return text


def _walk_api_keys(config: Dict[str, Any]):
    """深度优先遍历，产出所有 api_key 字段的 (容器, 键) 对。"""
    if isinstance(config, dict):
        for key, value in config.items():
            if key == "api_key" and isinstance(value, str):
                yield config, key
            elif isinstance(value, (dict, list)):
                yield from _walk_api_keys(value)
    elif isinstance(config, list):
        for item in config:
            yield from _walk_api_keys(item)


def encrypt_config_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """配置树内所有非空明文 api_key → 密文（就地修改并返回）。"""
    for container, key in _walk_api_keys(config):
        container[key] = encrypt_secret(container[key])
    return config


def decrypt_config_secrets(config: Dict[str, Any]) -> Dict[str, Any]:
    """配置树内所有密文 api_key → 明文（就地修改并返回；明文原样）。"""
    for container, key in _walk_api_keys(config):
        container[key] = decrypt_secret(container[key])
    return config
