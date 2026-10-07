"""
密钥安全存储（web_reach 每用户凭据桶）

密码学口径**不在此模块**：写侧一律走仓内唯一认证加密实现
`neurova.llm.providers.secret_store`（`enc:v2:` = AES-256-GCM，per-record 随机
salt + nonce，机密性与完整性同时给）。本模块只负责持久层——按用户分桶的
`secrets.json` / `metadata.json` / `access_log.json` 三件套，签名与
`providers/secret_store.py` 的 `SecretStore(master_key=, storage_path=)` 不同，
两者服务不同存储结构，**不合并**（合并会把两套 JSON schema 搅成第三套）。

历史写格式（重复密钥流 XOR：base64(value XOR sha256(key))）只保留**只读**解码，
用于存量凭据读回；读回后的条目在下次落盘时自动升级为认证格式，弱密文不再留在盘上。

与 `providers/secret_store.py` 的构造签名差异（P2-2 审计发现）：
- 本模块 `SecretStore(storage_path=, encryption_key=)` —— web_reach/credentials 依赖
- `providers/secret_store.py` `SecretStore(master_key=, storage_path=)` —— provider_manager 使用
"""

import base64
import datetime
import hashlib
import json
from neurova.core.logger import get_logger
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from neurova.llm.providers.secret_store import decrypt_api_key, encrypt_api_key

logger = get_logger(__name__)

# 认证/遗留 `enc:` 族都交给单源实现分发；无前缀即本模块历史 XOR 格式
_ENCRYPTED_PREFIX = "enc:"


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
    """密钥安全存储（持久层；加密口径见模块 docstring 指向的单源实现）"""

    def __init__(self, storage_path: str, encryption_key: str):
        """
        初始化密钥存储

        Args:
            storage_path: 存储路径（每用户一桶，由 web_reach/credentials 传入）
            encryption_key: 加密密钥——**必填**。缺省曾是"自动生成随机密钥"，
                那意味着本次进程写出的密文下个进程永远解不开（且解不开时会被
                下一次保存静默抹掉），所以宁可当场拒绝构造。
        """
        if not storage_path:
            raise ValueError("storage_path 必填：默认落点曾是 Path.home()/.neurova，绕过数据根")
        if not encryption_key:
            raise ValueError(
                "encryption_key 必填：随机临时密钥写出的凭据重启后解不开，等同丢数据"
            )

        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._key = encryption_key

        self.secrets_file = self.storage_path / "secrets.json"
        self.metadata_file = self.storage_path / "metadata.json"
        self.access_log_file = self.storage_path / "access_log.json"

        # 线程锁
        self._lock = threading.RLock()

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
        """
        存储密钥

        Args:
            name: 密钥名称
            value: 密钥值
            description: 描述
            expires_in: 过期时间（秒）
            tags: 标签

        Returns:
            是否成功
        """
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
        """
        获取密钥

        Args:
            name: 密钥名称

        Returns:
            密钥值，如果不存在则返回None
        """
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
        """删除密钥（读不懂的存量条目也必须删得掉，否则只剩盘上一团死密文）"""
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

    def rotate_secret(self, name: str, new_value: str) -> bool:
        """
        轮换密钥

        Args:
            name: 密钥名称
            new_value: 新密钥值

        Returns:
            是否成功
        """
        with self._lock:
            try:
                if name not in self._secrets:
                    return False

                # 保存旧值到历史（这里简化处理，实际应该保存到历史表）
                self._secrets[name]

                # 更新为新值
                self._secrets[name] = new_value

                # 更新元数据
                if name in self._metadata:
                    metadata = self._metadata[name]
                    metadata.updated_at = time.time()
                    metadata.rotation_count += 1

                self._save_secrets()

                # 记录访问日志
                self._log_access(name, "rotate")

                logger.info("Rotated secret: %s", name)
                return True

            except Exception as e:
                logger.error("Failed to rotate secret %s: %s", name, e)
                return False

    def rollback_secret(self, name: str, version: int = -1) -> bool:
        """
        回滚密钥（简化版本，实际应该支持版本管理）

        Args:
            name: 密钥名称
            version: 版本号（-1表示上一个版本）

        Returns:
            是否成功
        """
        # 简化实现：实际应该支持版本管理
        logger.warning("Rollback not fully implemented for secret: %s", name)
        return False

    def list_secrets(self, include_expired: bool = False) -> List[Dict[str, Any]]:
        """
        列出密钥

        Args:
            include_expired: 是否包含过期的密钥

        Returns:
            密钥列表
        """
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

    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        """
        获取密钥元数据

        Args:
            name: 密钥名称

        Returns:
            元数据字典，如果不存在则返回None
        """
        with self._lock:
            metadata = self._metadata.get(name)
            if metadata:
                return metadata.to_dict()
            return None

    def update_metadata(self, name: str, **kwargs) -> bool:
        """
        更新密钥元数据

        Args:
            name: 密钥名称
            **kwargs: 要更新的字段

        Returns:
            是否成功
        """
        with self._lock:
            try:
                if name not in self._metadata:
                    return False

                metadata = self._metadata[name]

                # 更新允许的字段
                allowed_fields = ["description", "expires_at", "tags"]
                for field, value in kwargs.items():
                    if field in allowed_fields:
                        setattr(metadata, field, value)

                metadata.updated_at = time.time()
                self._persistSideFiles()

                return True

            except Exception as e:
                logger.error("Failed to update metadata for %s: %s", name, e)
                return False

    def _log_access(self, name: str, action: str):
        """
        记录访问日志

        Args:
            name: 密钥名称
            action: 操作类型
        """
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
        """
        获取访问日志

        Args:
            name: 密钥名称（可选）
            limit: 返回数量限制

        Returns:
            访问日志列表
        """
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
        """清除访问日志"""
        with self._lock:
            self._access_log.clear()
            self._persistSideFiles()
            logger.info("Access log cleared")
