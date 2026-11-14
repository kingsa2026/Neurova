"""
密钥安全存储（全仓单源，P2-22 合并）

本模块是凭据加密与持久化的**唯一**实现，合并自原 `providers/secret_store.py`
（AES-256-GCM 加解密 + 全局单文件库）与原 `secret_store_clean.py`
（web_reach 每用户凭据桶 + 元数据/访问日志）。两类持久化布局服务不同域：

- 单文件模式 ``SecretStore(master_key=, storage_path=<secrets.json 文件路径>)``：
  全局密钥库（LLM provider 凭据、neurflow 店铺凭据/OAuth state、构建会话问答密钥），
  持久化为单个 ``secrets.json``，经 :func:`get_secret_store` 取全局单例。
- 桶模式 ``SecretStore(storage_path=<目录>, encryption_key=<密钥>)``：
  web_reach 每用户凭据桶，``secrets.json`` / ``metadata.json`` / ``access_log.json``
  三件套，按用户物理隔离。

密码学口径只有一套：``enc:v2:`` = AES-256-GCM（per-record 随机 salt + nonce，
PBKDF2-SHA256 20 万次迭代派生密钥，机密性与完整性同时给），
``encrypt_api_key`` / ``decrypt_api_key`` 为全仓唯一加解密入口。
历史写格式（重复密钥流 XOR）只保留**只读**解码用于存量迁移，读回后自动升级。

两种布局的密文格式相同（同一加解密单源），但物理文件互不通用——
单文件库存全局密钥，桶库存按用户隔离的凭据，属不同存储域而非重复实现。
"""

import base64
import datetime
import hashlib
import json
import secrets
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.core import config
from neurova.core.data_root import dataPath
from neurova.core.logger import get_logger
from neurova.core.time_utils import nowIso as _now_iso

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# pycryptodome 依赖检测（fail-fast）
# ---------------------------------------------------------------------------
# 本模块是 pycryptodome (Crypto 模块) 的唯一消费者。
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
_DEFAULT_PATH = dataPath("secrets.json")
_ITERATIONS = 10000

# AES-GCM 参数
_PBKDF2_ITERATIONS = 200000  # NIST 推荐的最小迭代次数
_AES_KEY_SIZE = 32  # AES-256
_GCM_NONCE_SIZE = 12  # 96-bit nonce (NIST 推荐)
_GCM_TAG_SIZE = 16  # 128-bit tag

# 历史遗留 `enc:` 族（不含 v2 标记）与无前缀历史 XOR 格式的识别前缀
_ENCRYPTED_PREFIX = "enc:"


def _new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex}" if prefix else uuid.uuid4().hex


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


@dataclass
class SecretMetadata:
    """密钥元数据"""

    name: str
    description: str = ""
    created_at: Optional[float] = None
    updated_at: Optional[float] = None
    expires_at: Optional[float] = None
    rotation_count: int = 0
    last_accessed: Optional[float] = None
    access_count: int = 0
    tags: Optional[List[str]] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
        if self.updated_at is None:
            self.updated_at = time.time()
        if self.tags is None:
            self.tags = []

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SecretMetadata":
        """从字典创建"""
        return cls(**data)


class SecretStore:
    """密钥安全存储（双布局单实现，加密口径统一走本模块加解密单源）

    - 桶模式（web_reach 每用户凭据桶）：
      ``SecretStore(storage_path=<目录>, encryption_key=<密钥>)``
    - 单文件模式（全局密钥库，经 :func:`get_secret_store` 取单例）：
      ``SecretStore(master_key=<密钥>, storage_path=<secrets.json 文件路径>)``
    """

    def __init__(
        self,
        storage_path: Optional[str] = None,
        encryption_key: Optional[str] = None,
        master_key: Optional[str] = None,
    ) -> None:
        self._lock = threading.RLock()
        if encryption_key:
            # ---- 桶模式（原 web_reach 凭据桶布局）----
            if not storage_path:
                raise ValueError("storage_path 必填：默认落点曾是 Path.home()/.neurova，绕过数据根")
            self._mode = "bucket"
            self.storage_path = Path(storage_path)
            self.storage_path.mkdir(parents=True, exist_ok=True)
            self._key = encryption_key

            self.secrets_file = self.storage_path / "secrets.json"
            self.metadata_file = self.storage_path / "metadata.json"
            self.access_log_file = self.storage_path / "access_log.json"

            # 加载数据
            self._secrets: Dict[str, str] = {}
            # 解不开的条目按**原文**留档，_save_secrets 不得把它们从盘上抹掉
            self._unreadable: Dict[str, str] = {}
            # 读回来的历史 XOR 密文（值已是明文），当场换成认证格式
            self._pendingUpgrade: List[str] = []
            self._metadata: Dict[str, SecretMetadata] = {}
            self._access_log: List[Dict[str, Any]] = []

            self._load_secrets()
            self._upgradeLegacyEntries()

            logger.info("SecretStore initialized with storage_path=%s", self.storage_path)
        elif master_key is not None or (
            storage_path is not None and str(storage_path).endswith(".json")
        ):
            # ---- 单文件模式（原 providers/secret_store.py 全局密钥库布局）----
            self._mode = "single_file"
            self._master_key = _coerce_master(master_key)
            self._secrets: Dict[str, str] = {}
            self._meta: Dict[str, Dict[str, Any]] = {}
            self.storage_path: Optional[Path] = (
                Path(storage_path) if storage_path else None
            )
            self._load()
        else:
            # 目录桶不给密钥＝写出的凭据下个进程解不开，宁可当场拒绝构造
            raise ValueError(
                "encryption_key 必填：随机临时密钥写出的凭据重启后解不开，等同丢数据"
            )

    # ------------------------------------------------------------------
    # 模式内省
    # ------------------------------------------------------------------

    @property
    def master_key(self) -> str:
        """主密钥（仅单文件模式有语义；桶模式密钥见 ``_key``）"""
        return getattr(self, "_master_key", "")

    def _requireMode(self, mode: str, method: str) -> None:
        """越模式调用直接点名失败，不许静默走错布局"""
        if self._mode != mode:
            raise AttributeError(
                f"SecretStore.{method} 仅在 {mode} 模式可用（当前 {self._mode} 模式）"
            )

    # ==================================================================
    # 桶模式（web_reach 每用户凭据桶）
    # ==================================================================

    def _encryptValue(self, value: str) -> str:
        """写路径：认证加密单源实现（pycryptodome 缺失时它抛 RuntimeError）。"""
        return encrypt_api_key(value, self._key)

    def _decryptValue(self, stored: str) -> str:
        """读路径：`enc:` 族交单源实现分发，无前缀即本模块历史 XOR 格式。"""
        if stored.startswith(_ENCRYPTED_PREFIX):
            return decrypt_api_key(stored, self._key)
        return self._decodeLegacyKeystream(stored)

    def _decodeLegacyKeystream(self, stored: str) -> str:
        """只读解码历史写格式 base64(value XOR sha256(key))——不再用于加密。"""
        keystream = hashlib.sha256(self._key.encode("utf-8")).digest()
        raw = base64.b64decode(stored.encode("ascii"), validate=True)
        plain = bytes(b ^ keystream[i % len(keystream)] for i, b in enumerate(raw))
        return plain.decode("utf-8")

    def _load_secrets(self):
        """加载密钥数据"""
        try:
            # 加载密钥
            if self.secrets_file.exists():
                with open(self.secrets_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for name, stored in data.items():
                        try:
                            self._secrets[name] = self._decryptValue(stored)
                            if not stored.startswith(_ENCRYPTED_PREFIX):
                                self._pendingUpgrade.append(name)
                        except Exception as e:
                            # 失败必须响亮，且**原文留档**：静默丢凭据比红更危险
                            self._unreadable[name] = stored
                            logger.error("凭据 %s 解密失败，已按原文保留待处理: %s", name, e)

            # 加载元数据
            if self.metadata_file.exists():
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for name, metadata_dict in data.items():
                        self._metadata[name] = SecretMetadata.from_dict(metadata_dict)

            # 加载访问日志
            if self.access_log_file.exists():
                with open(self.access_log_file, "r", encoding="utf-8") as f:
                    self._access_log = json.load(f)

            logger.info("Loaded %d secrets", len(self._secrets))

        except Exception as e:
            logger.error("Failed to load secrets: %s", e)

    def _upgradeLegacyEntries(self) -> None:
        """读到的历史 XOR 密文当场换成认证格式，不等"下次有人写"。

        常规部署盘上已是 `enc:v2:`，这里直接返回（零成本）；只有存在存量弱密文时
        才付一次整桶重加密（实测每条 ≈40ms，按桶一次性）。加密失败时**不动盘**——
        `_save_secrets` 在写完之前就会抛出，原文原样留着。
        """
        if not self._pendingUpgrade:
            return
        pending = list(self._pendingUpgrade)
        try:
            self._save_secrets()
        except Exception as exc:
            logger.error("%d 条历史凭据未能升级为认证加密，盘上原文未动: %s", len(pending), exc)
            return
        logger.warning("已把 %d 条历史凭据从 XOR 升级为认证加密: %s", len(pending), pending)

    def _save_secrets(self):
        """加密并落盘。

        两条纪律：① 加密失败**在动盘之前**就抛出（`store_secret` 因此回 False，
        而不是"报成功却把凭据写成弱密文/写丢"）；② 解不开的存量条目按原文带回，
        避免一次普通保存把整批读不了的凭据从盘上抹掉。
        """
        try:
            encrypted_secrets = {
                name: self._encryptValue(value) for name, value in self._secrets.items()
            }
            for name, stored in self._unreadable.items():
                encrypted_secrets.setdefault(name, stored)

            with open(self.secrets_file, "w", encoding="utf-8") as f:
                json.dump(encrypted_secrets, f, indent=2)

            self._persistSideFiles()
            self._pendingUpgrade.clear()

            logger.debug("Secrets saved successfully")

        except Exception as e:
            logger.error("Failed to save secrets: %s", e)
            raise

    def _persistSideFiles(self) -> None:
        """只落元数据与访问日志。

        读一条凭据也要重写 `secrets.json` 的话，等于每次读都为整桶付一次 PBKDF2
        （实测 ≈40ms/条）——审计计数该留，密文不该重算。
        """
        metadata_dict = {name: meta.to_dict() for name, meta in self._metadata.items()}

        with open(self.metadata_file, "w", encoding="utf-8") as f:
            json.dump(metadata_dict, f, indent=2)

        with open(self.access_log_file, "w", encoding="utf-8") as f:
            json.dump(self._access_log[-1000:], f, indent=2)

    def store_secret(
        self,
        name: str,
        value: str,
        description: str = "",
        expires_in: Optional[int] = None,
        tags: Optional[List[str]] = None,
    ) -> bool:
        """存储密钥（桶模式）"""
        self._requireMode("bucket", "store_secret")
        with self._lock:
            try:
                # 更新密钥
                self._secrets[name] = value

                # 更新元数据
                now = time.time()
                expires_at = now + expires_in if expires_in else None

                if name in self._metadata:
                    # 更新现有元数据
                    metadata = self._metadata[name]
                    metadata.updated_at = now
                    metadata.description = description or metadata.description
                    metadata.expires_at = expires_at
                    metadata.tags = tags or metadata.tags
                    metadata.rotation_count += 1
                else:
                    # 创建新元数据
                    self._metadata[name] = SecretMetadata(
                        name=name,
                        description=description,
                        created_at=now,
                        updated_at=now,
                        expires_at=expires_at,
                        tags=tags or [],
                    )

                # 保存
                self._save_secrets()

                # 记录访问日志
                self._log_access(name, "store")

                logger.info("Stored secret: %s", name)
                return True

            except Exception as e:
                logger.error("Failed to store secret %s: %s", name, e)
                return False

    def get_secret(self, name: str) -> Optional[str]:
        """获取密钥（桶模式）"""
        self._requireMode("bucket", "get_secret")
        with self._lock:
            try:
                if name not in self._secrets:
                    return None

                # 检查是否过期
                metadata = self._metadata.get(name)
                if metadata and metadata.expires_at:
                    if time.time() > metadata.expires_at:
                        logger.warning("Secret %s has expired", name)
                        return None

                # 更新访问信息
                if metadata:
                    metadata.last_accessed = time.time()
                    metadata.access_count += 1
                    self._persistSideFiles()

                # 记录访问日志
                self._log_access(name, "get")

                return self._secrets[name]

            except Exception as e:
                logger.error("Failed to get secret %s: %s", name, e)
                return None

    def delete_secret(self, name: str) -> bool:
        """删除密钥（桶模式；读不懂的存量条目也必须删得掉，否则只剩盘上一团死密文）"""
        self._requireMode("bucket", "delete_secret")
        with self._lock:
            try:
                if name not in self._secrets and name not in self._unreadable:
                    return False

                self._secrets.pop(name, None)
                self._unreadable.pop(name, None)

                if name in self._metadata:
                    del self._metadata[name]

                self._save_secrets()

                # 记录访问日志
                self._log_access(name, "delete")

                logger.info("Deleted secret: %s", name)
                return True

            except Exception as e:
                logger.error("Failed to delete secret %s: %s", name, e)
                return False

    def rollback_secret(self, name: str, version: int = -1) -> bool:
        """回滚密钥（桶模式；简化实现，实际应支持版本管理）"""
        self._requireMode("bucket", "rollback_secret")
        logger.warning("Rollback not fully implemented for secret: %s", name)
        return False

    def list_secrets(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """列出密钥（桶模式）"""
        self._requireMode("bucket", "list_secrets")
        with self._lock:
            try:
                result = []
                now = time.time()

                for name, metadata in self._metadata.items():
                    # 检查是否过期
                    if not include_expired and metadata.expires_at:
                        if now > metadata.expires_at:
                            continue

                    result.append(
                        {
                            "name": name,
                            "description": metadata.description,
                            "created_at": metadata.created_at,
                            "updated_at": metadata.updated_at,
                            "expires_at": metadata.expires_at,
                            "rotation_count": metadata.rotation_count,
                            "last_accessed": metadata.last_accessed,
                            "access_count": metadata.access_count,
                            "tags": metadata.tags,
                            "is_expired": metadata.expires_at and now > metadata.expires_at,
                        }
                    )

                return result

            except Exception as e:
                logger.error("Failed to list secrets: %s", e)
                return []

    def _log_access(self, name: str, action: str):
        """记录访问日志（桶模式）"""
        try:
            log_entry = {
                "name": name,
                "action": action,
                "timestamp": time.time(),
                "datetime": datetime.datetime.now().isoformat(),
            }

            self._access_log.append(log_entry)

            # 限制日志大小
            if len(self._access_log) > 1000:
                self._access_log = self._access_log[-1000:]

        except Exception as e:
            logger.error("Failed to log access: %s", e)

    def get_access_log(self, name: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """获取访问日志（桶模式）"""
        self._requireMode("bucket", "get_access_log")
        with self._lock:
            try:
                logs = self._access_log

                if name:
                    logs = [log for log in logs if log.get("name") == name]

                # 按时间倒序排序
                logs.sort(key=lambda x: x.get("timestamp", 0), reverse=True)

                return logs[:limit]

            except Exception as e:
                logger.error("Failed to get access log: %s", e)
                return []

    def clear_access_log(self):
        """清除访问日志（桶模式）"""
        self._requireMode("bucket", "clear_access_log")
        with self._lock:
            self._access_log.clear()
            self._persistSideFiles()
            logger.info("Access log cleared")

    # ==================================================================
    # 单文件模式（全局密钥库）
    # ==================================================================

    def _load(self) -> None:
        """加载单文件密钥库"""
        self._requireMode("single_file", "_load")
        if self.storage_path is None or not self.storage_path.exists():
            return
        try:
            data = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._secrets = {}
            return
        except Exception as exc:
            logger.warning("Failed to load secrets from %s: %s", self.storage_path, exc)
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
        """单文件密钥库落盘"""
        self._requireMode("single_file", "_save")
        if self.storage_path is None:
            return
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            data: Dict[str, Any] = {}
            for k, v in self._secrets.items():
                meta = self._meta.get(k)
                if meta:
                    entry: Dict[str, Any] = dict(meta)
                    entry["value"] = v
                    data[k] = entry
                else:
                    data[k] = v
            self.storage_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning("Failed to save secrets to %s: %s", self.storage_path, exc)

    def set(self, key: str, value: str) -> None:
        """写入并加密一条密钥（单文件模式）"""
        self._requireMode("single_file", "set")
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
        """读取一条密钥（单文件模式）"""
        self._requireMode("single_file", "get")
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
        """删除一条密钥（单文件模式）"""
        self._requireMode("single_file", "delete")
        if not isinstance(key, str):
            return False
        with self._lock:
            existed = self._secrets.pop(key, None) is not None
            self._meta.pop(key, None)
            if existed:
                self._save()
            return existed

    def list_keys(self) -> List[str]:
        """列出全部密钥名（单文件模式）"""
        self._requireMode("single_file", "list_keys")
        with self._lock:
            return list(self._secrets.keys())

    def has(self, key: str) -> bool:
        """判断密钥是否存在（单文件模式）"""
        self._requireMode("single_file", "has")
        if not isinstance(key, str):
            return False
        with self._lock:
            return key in self._secrets

    def count(self) -> int:
        """密钥数量（单文件模式）"""
        self._requireMode("single_file", "count")
        with self._lock:
            return len(self._secrets)

    def clear(self) -> int:
        """清空密钥库（单文件模式）"""
        self._requireMode("single_file", "clear")
        with self._lock:
            n = len(self._secrets)
            self._secrets.clear()
            self._meta.clear()
            self._save()
            return n

    def to_dict(self) -> Dict[str, Optional[str]]:
        """导出全部明文密钥（单文件模式）"""
        self._requireMode("single_file", "to_dict")
        with self._lock:
            out: Dict[str, Optional[str]] = {}
            for k, v in self._secrets.items():
                try:
                    out[k] = decrypt_api_key(v, master_key=self._master_key)
                except Exception:
                    out[k] = None
            return out

    # ==================================================================
    # 两种模式同名但语义各异的共享方法（按模式分发）
    # ==================================================================

    def get_metadata(self, key: str) -> Optional[Dict[str, Any]]:
        """获取密钥元数据（两种模式各自实现）"""
        if self._mode == "bucket":
            with self._lock:
                metadata = self._metadata.get(key)
                if metadata:
                    return metadata.to_dict()
                return None
        self._requireMode("single_file", "get_metadata")
        if not isinstance(key, str):
            return None
        with self._lock:
            meta = self._meta.get(key)
            return dict(meta) if meta else None

    def update_metadata(self, key: str, **fields: Any) -> bool:
        """更新密钥元数据（两种模式各自实现）"""
        if self._mode == "bucket":
            with self._lock:
                try:
                    if key not in self._metadata:
                        return False

                    metadata = self._metadata[key]

                    # 更新允许的字段
                    allowed_fields = ["description", "expires_at", "tags"]
                    for field, value in fields.items():
                        if field in allowed_fields:
                            setattr(metadata, field, value)

                    metadata.updated_at = time.time()
                    self._persistSideFiles()

                    return True

                except Exception as e:
                    logger.error("Failed to update metadata for %s: %s", key, e)
                    return False
        self._requireMode("single_file", "update_metadata")
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
        """轮换密钥（两种模式各自实现）"""
        if self._mode == "bucket":
            with self._lock:
                try:
                    if key not in self._secrets:
                        return False

                    # 更新为新值
                    self._secrets[key] = new_value

                    # 更新元数据
                    if key in self._metadata:
                        metadata = self._metadata[key]
                        metadata.updated_at = time.time()
                        metadata.rotation_count += 1

                    self._save_secrets()

                    # 记录访问日志
                    self._log_access(key, "rotate")

                    logger.info("Rotated secret: %s", key)
                    return True

                except Exception as e:
                    logger.error("Failed to rotate secret %s: %s", key, e)
                    return False
        self._requireMode("single_file", "rotate_secret")
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
    """全局密钥库单例（单文件模式；密钥与路径均来自配置，绝不随机生成）"""
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
