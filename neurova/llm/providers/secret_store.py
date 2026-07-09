"""
Secret store with AES-GCM encryption and JSON persistence.

安全说明:
    使用 AES-256-GCM 进行认证加密，替代不安全的 XOR 混淆。
    - 每次加密使用随机 salt（PBKDF2 密钥派生）和随机 nonce（AES-GCM IV）
    - GCM 模式提供机密性和完整性认证
    - 向后兼容旧 XOR 数据（仅用于解密迁移，不再用于新加密）
"""

import base64
import datetime
import hashlib
import json
import os
import secrets
from neurova.core import config
from neurova.core.logger import get_logger
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# pycryptodome 依赖检测(fail-fast)
# ---------------------------------------------------------------------------
# secret_store 是 pycryptodome (Crypto 模块) 的唯一消费者。
# 之前用懒导入(在 _aes_gcm_encrypt / _aes_gcm_decrypt 函数体内 from Crypto.Cipher import AES),
# 导致 pycryptodome 缺失时:
#   - decrypt_api_key 抛 ValueError("AES-GCM decryption failed: No module named 'Crypto'")
#   - provider_manager.py 的 from_dict catch 后只 logger.warning(易被忽略)
#   - 静默创建 api_key=None 的 ProviderConfig,整个 LLM 链路瘫痪但日志显示"Loaded N providers"
# 改为模块顶部显式检测,缺失时 HAS_CRYPTO=False 并立即记 ERROR 日志,
# 调用 _aes_gcm_* 时直接抛 RuntimeError("pycryptodome not installed — run: pip install pycryptodome")
# ---------------------------------------------------------------------------
try:
    from Crypto.Cipher import AES as _AES_MODULE  # noqa: F401
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    _AES_MODULE = None
    logger.error(
        "pycryptodome not installed — API key encryption/decryption disabled. "
        "Run: pip install pycryptodome"
    )


_PREFIX = "enc:"
_PREFIX_V2 = "enc:v2:"
_SALT = b"neurova-secret-store-v1"
_SALT_LEGACY = b"neurova-secret-store-legacy"
_VERSION_BYTE = 0x01
_DEFAULT_PATH = "./data/secrets.json"
_ITERATIONS = 10000

# AES-GCM 参数
_PBKDF2_ITERATIONS = 200000  # NIST 推荐的最小迭代次数
_AES_KEY_SIZE = 32  # AES-256
_GCM_NONCE_SIZE = 12  # 96-bit nonce (NIST 推荐)
_GCM_TAG_SIZE = 16  # 128-bit tag


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


def _now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _coerce_master(master_key: Any) -> str:
    if master_key is None:
        return ""
    if isinstance(master_key, bytes):
        try:
            return master_key.decode("utf-8")
        except Exception:
            return master_key.hex()
    return str(master_key)


def _derive_key_simple(master_key: str = "", salt: bytes = b"") -> bytes:
    mk = _coerce_master(master_key).encode("utf-8")
    hk = hashlib.sha256()
    hk.update(salt if salt else b"\x00")
    hk.update(mk)
    hk.update(b"|neurova|secret|v1")
    return hk.digest()


def _derive_key_legacy(master_key: str = "", salt: bytes = b"") -> bytes:
    mk = _coerce_master(master_key).encode("utf-8")
    hk = hashlib.sha256()
    hk.update(salt if salt else b"\x00")
    hk.update(mk)
    hk.update(b"|neurova|legacy")
    return hk.digest()


def _derive_key(master_key: str = "") -> bytes:
    return _derive_key_simple(master_key, salt=_SALT)


def _xor_encrypt(plaintext: bytes, key: bytes) -> bytes:
    """旧版 XOR 混淆（仅用于解密遗留数据，不再用于新加密）"""
    if not key:
        return bytes(plaintext)
    klen = len(key)
    out = bytearray(len(plaintext))
    for i, b in enumerate(plaintext):
        out[i] = b ^ key[i % klen]
    return bytes(out)


def _derive_aes_key(master_key: str, salt: bytes) -> bytes:
    """使用 PBKDF2-SHA256 派生 AES-256 密钥"""
    mk = _coerce_master(master_key).encode("utf-8")
    return hashlib.pbkdf2_hmac(
        "sha256", mk, salt, iterations=_PBKDF2_ITERATIONS, dklen=_AES_KEY_SIZE
    )


def _aes_gcm_encrypt(plaintext: bytes, master_key: str) -> str:
    """使用 AES-256-GCM 加密，返回 v2 格式字符串"""
    if not HAS_CRYPTO:
        # fail-fast:依赖缺失时立即抛 RuntimeError,而非懒导入后再抛 ImportError
        # 被 encrypt_api_key 直接向上抛出,不被捕获包装
        raise RuntimeError(
            "pycryptodome not installed — run: pip install pycryptodome"
        )

    # 每次加密使用随机 salt 和 nonce
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(_GCM_NONCE_SIZE)

    # 派生密钥
    key = _derive_aes_key(master_key, salt)

    # AES-GCM 加密
    cipher = _AES_MODULE.new(key, _AES_MODULE.MODE_GCM, nonce=nonce)
    ciphertext, tag = cipher.encrypt_and_digest(plaintext)

    # 格式: enc:v2:<salt_b64>:<nonce_b64>:<ct_b64>:<tag_b64>
    return (
        _PREFIX_V2
        + base64.urlsafe_b64encode(salt).decode("ascii")
        + ":"
        + base64.urlsafe_b64encode(nonce).decode("ascii")
        + ":"
        + base64.urlsafe_b64encode(ciphertext).decode("ascii")
        + ":"
        + base64.urlsafe_b64encode(tag).decode("ascii")
    )


def _aes_gcm_decrypt(payload: str, master_key: str) -> bytes:
    """解密 v2 格式的 AES-256-GCM 密文"""
    if not HAS_CRYPTO:
        # fail-fast:依赖缺失时立即抛 RuntimeError,而非懒导入后再抛 ImportError
        raise RuntimeError(
            "pycryptodome not installed — run: pip install pycryptodome"
        )

    parts = payload.split(":")
    # 格式: enc:v2:<salt_b64>:<nonce_b64>:<ct_b64>:<tag_b64>
    # split 后: ["enc", "v2", "<salt_b64>", "<nonce_b64>", "<ct_b64>", "<tag_b64>"]
    if len(parts) != 6:
        raise ValueError("invalid v2 payload format")

    salt = base64.urlsafe_b64decode(parts[2])
    nonce = base64.urlsafe_b64decode(parts[3])
    ciphertext = base64.urlsafe_b64decode(parts[4])
    tag = base64.urlsafe_b64decode(parts[5])

    key = _derive_aes_key(master_key, salt)
    cipher = _AES_MODULE.new(key, _AES_MODULE.MODE_GCM, nonce=nonce)
    return cipher.decrypt_and_verify(ciphertext, tag)


def _try_decode_b64(payload: str) -> bytes:
    try:
        padded = payload + "=" * (-len(payload) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii"))
    except Exception:
        try:
            return base64.b64decode(payload.encode("ascii"), validate=False)
        except Exception as exc:
            raise ValueError(f"invalid base64 payload: {exc}") from exc


def encrypt_api_key(plaintext: str, master_key: str = "") -> str:
    if plaintext is None or plaintext == "":
        raise ValueError("plaintext must be a non-empty string")
    if not isinstance(plaintext, str):
        plaintext = str(plaintext)
    mk = _coerce_master(master_key)
    # 使用 AES-256-GCM 加密（替代不安全的 XOR）
    return _aes_gcm_encrypt(plaintext.encode("utf-8"), mk)


def _decrypt_with_key(payload: bytes, key: bytes) -> str:
    """旧版 XOR 解密（仅用于向后兼容遗留数据）"""
    dec = _xor_encrypt(payload, key)
    if not dec or dec[0] != _VERSION_BYTE:
        raise ValueError("decryption failed: invalid version marker")
    try:
        return dec[1:].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"decryption failed: invalid utf-8: {exc}") from exc


def decrypt_api_key(encrypted: Any, master_key: str = "") -> str:
    if encrypted is None:
        return ""
    if not isinstance(encrypted, str):
        try:
            encrypted = str(encrypted)
        except Exception:
            return ""

    # v2 格式：AES-256-GCM 加密
    if encrypted.startswith(_PREFIX_V2):
        mk = _coerce_master(master_key)
        try:
            plaintext_bytes = _aes_gcm_decrypt(encrypted, mk)
            return plaintext_bytes.decode("utf-8")
        except RuntimeError:
            # fail-fast 异常(如 pycryptodome 缺失)直接穿透,不被包装为 ValueError
            # 原因:依赖缺失是根因,与"AES-GCM 解密失败"是不同层级的问题,
            # 包装为 ValueError 会抹除根本原因的语义信号
            raise
        except Exception as exc:
            raise ValueError(f"AES-GCM decryption failed: {exc}") from exc

    # 旧版格式：XOR 混淆（仅用于解密遗留数据以支持迁移）
    if not encrypted.startswith(_PREFIX):
        return encrypted
    payload = encrypted[len(_PREFIX) :]
    try:
        raw = _try_decode_b64(payload)
    except Exception:
        raise ValueError("encrypted payload is not valid base64")
    mk = _coerce_master(master_key)
    try:
        return _decrypt_with_key(raw, _derive_key(mk))
    except Exception:
        try:
            return _decrypt_with_key(raw, _derive_key_legacy(mk, salt=_SALT_LEGACY))
        except Exception as exc:
            raise ValueError(f"decryption failed: {exc}") from exc


class SecretStore:
    def __init__(
        self,
        master_key: str = "",
        storage_path: Optional[str] = None,
    ) -> None:
        self._master_key = _coerce_master(master_key)
        self._secrets: Dict[str, str] = {}
        self._meta: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._storage_path: Optional[Path] = Path(storage_path) if storage_path else None
        self._load()

    @property
    def storage_path(self) -> Optional[Path]:
        return self._storage_path

    @property
    def master_key(self) -> str:
        return self._master_key

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return
        try:
            data = json.loads(self._storage_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._secrets = {}
            return
        except Exception as exc:
            logger.warning("Failed to load secrets from %s: %s", self._storage_path, exc)
            self._secrets = {}
            return
        if not isinstance(data, dict):
            self._secrets = {}
            return
        secrets_payload: Dict[str, str] = {}
        meta_payload: Dict[str, Dict[str, Any]] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if isinstance(v, str):
                secrets_payload[k] = v
            elif isinstance(v, dict):
                encrypted = v.get("value")
                if isinstance(encrypted, str):
                    secrets_payload[k] = encrypted
                    meta = {mk: mv for mk, mv in v.items() if mk != "value"}
                    if meta:
                        meta_payload[k] = meta
        self._secrets = secrets_payload
        self._meta = meta_payload

    def _save(self) -> None:
        if self._storage_path is None:
            return
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            data: Dict[str, Any] = {}
            for k, v in self._secrets.items():
                meta = self._meta.get(k)
                if meta:
                    entry: Dict[str, Any] = dict(meta)
                    entry["value"] = v
                    data[k] = entry
                else:
                    data[k] = v
            self._storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save secrets to %s: %s", self._storage_path, exc)

    def set(self, key: str, value: str) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("key must be a non-empty string")
        if value is None or not isinstance(value, str):
            raise ValueError("value must be a string")
        with self._lock:
            self._secrets[key] = encrypt_api_key(value, master_key=self._master_key)
            self._meta[key] = {
                "updated_at": _now_iso(),
                "id": _new_id("sec_"),
            }
            self._save()

    def get(self, key: str) -> Optional[str]:
        if not isinstance(key, str):
            return None
        with self._lock:
            enc = self._secrets.get(key)
            if enc is None:
                return None
            try:
                return decrypt_api_key(enc, master_key=self._master_key)
            except Exception:
                return None

    def delete(self, key: str) -> bool:
        if not isinstance(key, str):
            return False
        with self._lock:
            existed = self._secrets.pop(key, None) is not None
            self._meta.pop(key, None)
            if existed:
                self._save()
            return existed

    def list_keys(self) -> List[str]:
        with self._lock:
            return list(self._secrets.keys())

    def has(self, key: str) -> bool:
        if not isinstance(key, str):
            return False
        with self._lock:
            return key in self._secrets

    def count(self) -> int:
        with self._lock:
            return len(self._secrets)

    def clear(self) -> int:
        with self._lock:
            n = len(self._secrets)
            self._secrets.clear()
            self._meta.clear()
            self._save()
            return n

    def to_dict(self) -> Dict[str, Optional[str]]:
        with self._lock:
            out: Dict[str, Optional[str]] = {}
            for k, v in self._secrets.items():
                try:
                    out[k] = decrypt_api_key(v, master_key=self._master_key)
                except Exception:
                    out[k] = None
            return out

    def get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        if not isinstance(key, str):
            return None
        with self._lock:
            meta = self._meta.get(key)
            return dict(meta) if meta else None

    def update_metadata(self, key: str, **fields: Any) -> bool:
        if not isinstance(key, str) or not key:
            return False
        with self._lock:
            if key not in self._secrets:
                return False
            self._meta.setdefault(key, {"updated_at": _now_iso()})
            self._meta[key].update(fields)
            self._meta[key]["updated_at"] = _now_iso()
            self._save()
            return True

    def rotate_secret(self, key: str, new_value: str) -> bool:
        if not isinstance(key, str) or not key:
            return False
        if not isinstance(new_value, str) or not new_value:
            raise ValueError("new_value must be a non-empty string")
        with self._lock:
            if key not in self._secrets:
                return False
            self._secrets[key] = encrypt_api_key(new_value, master_key=self._master_key)
            self._meta.setdefault(key, {"updated_at": _now_iso()})
            self._meta[key]["rotated_at"] = _now_iso()
            self._meta[key]["updated_at"] = _now_iso()
            self._save()
            return True


_singleton: Optional[SecretStore] = None
_singleton_lock = threading.Lock()


def get_secret_store() -> SecretStore:
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            mk = config.get("NEUROVA_MASTER_KEY", "")
            path = config.get("NEUROVA_SECRETS_PATH", _DEFAULT_PATH)
            try:
                _singleton = SecretStore(master_key=mk, storage_path=path)
            except Exception as exc:
                logger.warning("Failed to initialize singleton SecretStore: %s", exc)
                _singleton = SecretStore(master_key=mk, storage_path=None)
    return _singleton


def _reset_singleton_for_tests() -> None:
    global _singleton
    with _singleton_lock:
        _singleton = None
