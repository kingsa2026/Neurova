"""
密钥安全存储

实现密钥的加密存储、轮换和访问控制

注意：此版本完全不依赖 cryptography 库
"""

import base64
import datetime
import hashlib
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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


class SimpleCipher:
    """简单加密器（不依赖cryptography库）"""

    def __init__(self, key: Optional[str] = None):
        """
        初始化简单加密器

        Args:
            key: 加密密钥（如果为None则自动生成）
        """
        if key:
            self.key = key.encode("utf-8")
        else:
            self.key = self.generate_key()

        # 使用SHA256生成固定长度的密钥
        self.key_hash = hashlib.sha256(self.key).digest()

    def encrypt(self, plaintext: str) -> str:
        """
        加密文本

        Args:
            plaintext: 明文

        Returns:
            密文（Base64编码）
        """
        try:
            # 使用XOR加密
            plaintext_bytes = plaintext.encode("utf-8")
            encrypted_bytes = bytearray()

            for i, byte in enumerate(plaintext_bytes):
                key_byte = self.key_hash[i % len(self.key_hash)]
                encrypted_bytes.append(byte ^ key_byte)

            # Base64编码
            return base64.b64encode(encrypted_bytes).decode("ascii")

        except Exception as e:
            logger.error("Encryption failed: %s", e)
            raise

    def decrypt(self, ciphertext: str) -> str:
        """
        解密文本

        Args:
            ciphertext: 密文（Base64编码）

        Returns:
            明文
        """
        try:
            # Base64解码
            encrypted_bytes = base64.b64decode(ciphertext.encode("ascii"))
            decrypted_bytes = bytearray()

            for i, byte in enumerate(encrypted_bytes):
                key_byte = self.key_hash[i % len(self.key_hash)]
                decrypted_bytes.append(byte ^ key_byte)

            return decrypted_bytes.decode("utf-8")

        except Exception as e:
            logger.error("Decryption failed: %s", e)
            raise

    def generate_key(self) -> bytes:
        """
        生成随机密钥

        Returns:
            随机密钥
        """
        return secrets.token_bytes(32)


class SecretStore:
    """密钥安全存储"""

    def __init__(self, storage_path: Optional[str] = None, encryption_key: Optional[str] = None):
        """
        初始化密钥存储

        Args:
            storage_path: 存储路径
            encryption_key: 加密密钥
        """
        self.storage_path = Path(storage_path) if storage_path else self._get_default_storage_path()
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # 初始化加密器
        self.cipher = SimpleCipher(encryption_key)

        # 密钥存储
        self.secrets_file = self.storage_path / "secrets.json"
        self.metadata_file = self.storage_path / "metadata.json"
        self.access_log_file = self.storage_path / "access_log.json"

        # 线程锁
        self._lock = threading.RLock()

        # 加载数据
        self._secrets: Dict[str, str] = {}
        self._metadata: Dict[str, SecretMetadata] = {}
        self._access_log: List[Dict[str, Any]] = []

        self._load_secrets()

        logger.info("SecretStore initialized with storage_path=%s", self.storage_path)

    def _get_default_storage_path(self) -> Path:
        """获取默认存储路径"""
        return Path.home() / ".neurova" / "secrets"

    def _load_secrets(self):
        """加载密钥数据"""
        try:
            # 加载密钥
            if self.secrets_file.exists():
                with open(self.secrets_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for name, encrypted_value in data.items():
                        try:
                            self._secrets[name] = self.cipher.decrypt(encrypted_value)
                        except Exception as e:
                            logger.warning("Failed to decrypt secret %s: %s", name, e)

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

    def _save_secrets(self):
        """保存密钥数据"""
        try:
            # 保存密钥
            encrypted_secrets = {}
            for name, value in self._secrets.items():
                try:
                    encrypted_secrets[name] = self.cipher.encrypt(value)
                except Exception as e:
                    logger.warning("Failed to encrypt secret %s: %s", name, e)

            with open(self.secrets_file, "w", encoding="utf-8") as f:
                json.dump(encrypted_secrets, f, indent=2)

            # 保存元数据
            metadata_dict = {}
            for name, metadata in self._metadata.items():
                metadata_dict[name] = metadata.to_dict()

            with open(self.metadata_file, "w", encoding="utf-8") as f:
                json.dump(metadata_dict, f, indent=2)

            # 保存访问日志
            with open(self.access_log_file, "w", encoding="utf-8") as f:
                json.dump(self._access_log[-1000:], f, indent=2)  # 只保留最近1000条

            logger.debug("Secrets saved successfully")

        except Exception as e:
            logger.error("Failed to save secrets: %s", e)
            raise

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
                    self._save_secrets()

                # 记录访问日志
                self._log_access(name, "get")

                return self._secrets[name]

            except Exception as e:
                logger.error("Failed to get secret %s: %s", name, e)
                return None

    def delete_secret(self, name: str) -> bool:
        """
        删除密钥

        Args:
            name: 密钥名称

        Returns:
            是否成功
        """
        with self._lock:
            try:
                if name not in self._secrets:
                    return False

                del self._secrets[name]

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
                self._save_secrets()

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
            self._save_secrets()
            logger.info("Access log cleared")


# 全局实例
_secret_store: Optional[SecretStore] = None


def get_secret_store() -> SecretStore:
    """
    获取密钥存储实例（单例模式）

    Returns:
        SecretStore实例
    """
    global _secret_store
    if _secret_store is None:
        _secret_store = SecretStore()
    return _secret_store


def reset_secret_store():
    """
    重置密钥存储实例（用于测试）
    """
    global _secret_store
    _secret_store = None
