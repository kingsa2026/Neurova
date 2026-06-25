"""
Media Storage Configuration - 媒体存储配置管理

功能:
- 统一的媒体存储配置（不硬编码）
- 支持日期归档子目录
- 缓存失效配置
- 数据库记录配置

配置路径: agents/{agent_id}/workspace/media/config.json
"""

from __future__ import annotations

import datetime
import json
from neurova.core.logger import get_logger
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


@dataclass
class DateArchivalConfig:
    """日期归档配置"""

    enabled: bool = True
    format: str = "%Y/%m/%d"  # 日期格式
    create_subdirs: bool = True
    timezone: str = "UTC"

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "format": self.format,
            "create_subdirs": self.create_subdirs,
            "timezone": self.timezone,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DateArchivalConfig":
        """从字典创建"""
        return cls(
            enabled=data.get("enabled", True),
            format=data.get("format", "%Y/%m/%d"),
            create_subdirs=data.get("create_subdirs", True),
            timezone=data.get("timezone", "UTC"),
        )

    def get_date_path(self, date: Optional[datetime.datetime] = None) -> str:
        """获取日期路径"""
        if not self.enabled:
            return ""

        if date is None:
            date = datetime.datetime.now()

        return date.strftime(self.format)


@dataclass
class CacheConfig:
    """缓存配置"""

    enabled: bool = True
    max_size_mb: int = 100
    ttl_seconds: int = 3600
    cleanup_interval_seconds: int = 300
    max_items: int = 10000

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "max_size_mb": self.max_size_mb,
            "ttl_seconds": self.ttl_seconds,
            "cleanup_interval_seconds": self.cleanup_interval_seconds,
            "max_items": self.max_items,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CacheConfig":
        """从字典创建"""
        return cls(
            enabled=data.get("enabled", True),
            max_size_mb=data.get("max_size_mb", 100),
            ttl_seconds=data.get("ttl_seconds", 3600),
            cleanup_interval_seconds=data.get("cleanup_interval_seconds", 300),
            max_items=data.get("max_items", 10000),
        )


@dataclass
class DatabaseConfig:
    """数据库配置"""

    enabled: bool = True
    backend: str = "sqlite"  # sqlite, postgres, memory
    connection_string: Optional[str] = None
    table_prefix: str = "media_"
    auto_create_tables: bool = True
    pool_size: int = 5
    max_overflow: int = 10
    echo: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "connection_string": self.connection_string,
            "table_prefix": self.table_prefix,
            "auto_create_tables": self.auto_create_tables,
            "pool_size": self.pool_size,
            "max_overflow": self.max_overflow,
            "echo": self.echo,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DatabaseConfig":
        """从字典创建"""
        return cls(
            enabled=data.get("enabled", True),
            backend=data.get("backend", "sqlite"),
            connection_string=data.get("connection_string"),
            table_prefix=data.get("table_prefix", "media_"),
            auto_create_tables=data.get("auto_create_tables", True),
            pool_size=data.get("pool_size", 5),
            max_overflow=data.get("max_overflow", 10),
            echo=data.get("echo", False),
        )


@dataclass
class MediaStorageConfig:
    """媒体存储配置"""

    # 基础配置
    root_dir: str = "media"
    max_file_size_mb: int = 100
    allowed_extensions: List[str] = field(
        default_factory=lambda: [
            ".jpg",
            ".jpeg",
            ".png",
            ".gif",
            ".webp",
            ".svg",
            ".mp4",
            ".avi",
            ".mov",
            ".wmv",
            ".flv",
            ".webm",
            ".mp3",
            ".wav",
            ".ogg",
            ".aac",
            ".flac",
            ".pdf",
            ".doc",
            ".docx",
            ".xls",
            ".xlsx",
            ".ppt",
            ".pptx",
            ".txt",
            ".md",
            ".json",
            ".xml",
            ".csv",
        ]
    )

    # 日期归档配置
    date_archival: DateArchivalConfig = field(default_factory=DateArchivalConfig)

    # 缓存配置
    cache: CacheConfig = field(default_factory=CacheConfig)

    # 数据库配置
    database: DatabaseConfig = field(default_factory=DatabaseConfig)

    # 安全配置
    enable_checksum: bool = True
    checksum_algorithm: str = "sha256"
    enable_encryption: bool = False
    encryption_key: Optional[str] = None

    # 压缩配置
    enable_compression: bool = False
    compression_format: str = "gzip"
    compression_level: int = 6

    # 清理配置
    auto_cleanup_enabled: bool = True
    cleanup_interval_hours: int = 24
    max_age_days: int = 365

    # 扩展配置
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "root_dir": self.root_dir,
            "max_file_size_mb": self.max_file_size_mb,
            "allowed_extensions": self.allowed_extensions,
            "date_archival": self.date_archival.to_dict(),
            "cache": self.cache.to_dict(),
            "database": self.database.to_dict(),
            "enable_checksum": self.enable_checksum,
            "checksum_algorithm": self.checksum_algorithm,
            "enable_encryption": self.enable_encryption,
            "encryption_key": self.encryption_key,
            "enable_compression": self.enable_compression,
            "compression_format": self.compression_format,
            "compression_level": self.compression_level,
            "auto_cleanup_enabled": self.auto_cleanup_enabled,
            "cleanup_interval_hours": self.cleanup_interval_hours,
            "max_age_days": self.max_age_days,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MediaStorageConfig":
        """从字典创建"""
        return cls(
            root_dir=data.get("root_dir", "media"),
            max_file_size_mb=data.get("max_file_size_mb", 100),
            allowed_extensions=data.get(
                "allowed_extensions",
                [
                    ".jpg",
                    ".jpeg",
                    ".png",
                    ".gif",
                    ".webp",
                    ".svg",
                    ".mp4",
                    ".avi",
                    ".mov",
                    ".wmv",
                    ".flv",
                    ".webm",
                    ".mp3",
                    ".wav",
                    ".ogg",
                    ".aac",
                    ".flac",
                    ".pdf",
                    ".doc",
                    ".docx",
                    ".xls",
                    ".xlsx",
                    ".ppt",
                    ".pptx",
                    ".txt",
                    ".md",
                    ".json",
                    ".xml",
                    ".csv",
                ],
            ),
            date_archival=DateArchivalConfig.from_dict(data.get("date_archival", {})),
            cache=CacheConfig.from_dict(data.get("cache", {})),
            database=DatabaseConfig.from_dict(data.get("database", {})),
            enable_checksum=data.get("enable_checksum", True),
            checksum_algorithm=data.get("checksum_algorithm", "sha256"),
            enable_encryption=data.get("enable_encryption", False),
            encryption_key=data.get("encryption_key"),
            enable_compression=data.get("enable_compression", False),
            compression_format=data.get("compression_format", "gzip"),
            compression_level=data.get("compression_level", 6),
            auto_cleanup_enabled=data.get("auto_cleanup_enabled", True),
            cleanup_interval_hours=data.get("cleanup_interval_hours", 24),
            max_age_days=data.get("max_age_days", 365),
            metadata=data.get("metadata", {}),
        )

    def get_root_path(self, agent_id: Optional[str] = None) -> Path:
        """获取根路径"""
        if agent_id:
            return Path(f"agents/{agent_id}/workspace/{self.root_dir}")
        return Path(self.root_dir)

    def get_media_path(self, agent_id: str, filename: str, date: Optional[datetime.datetime] = None) -> Path:
        """获取媒体文件路径"""
        root = self.get_root_path(agent_id)

        # 添加日期归档路径
        if self.date_archival.enabled:
            date_path = self.date_archival.get_date_path(date)
            if date_path:
                root = root / date_path

        return root / filename

    def is_allowed_extension(self, filename: str) -> bool:
        """检查文件扩展名是否允许"""
        ext = Path(filename).suffix.lower()
        return ext in self.allowed_extensions

    def is_allowed_size(self, size_bytes: int) -> bool:
        """检查文件大小是否允许"""
        max_bytes = self.max_file_size_mb * 1024 * 1024
        return size_bytes <= max_bytes


class MediaStorageConfigManager:
    """
    媒体存储配置管理器

    功能：
    1. 加载和保存配置
    2. 配置验证
    3. 配置更新
    """

    def __init__(self, config_dir: Optional[Path] = None):
        """
        初始化配置管理器

        Args:
            config_dir: 配置目录路径
        """
        self.config_dir = config_dir or Path("config/media")

        # 线程锁
        self._lock = threading.RLock()

        # 配置缓存
        self._configs: Dict[str, MediaStorageConfig] = {}

        # 确保配置目录存在
        self.config_dir.mkdir(parents=True, exist_ok=True)

        logger.info("MediaStorageConfigManager initialized: %s", self.config_dir)

    def get_config(self, agent_id: str) -> MediaStorageConfig:
        """
        获取媒体存储配置

        Args:
            agent_id: Agent ID

        Returns:
            MediaStorageConfig 实例
        """
        with self._lock:
            if agent_id not in self._configs:
                self._configs[agent_id] = self._load_config(agent_id)

            return self._configs[agent_id]

    def save_config(self, agent_id: str, config: MediaStorageConfig) -> bool:
        """
        保存媒体存储配置

        Args:
            agent_id: Agent ID
            config: 配置对象

        Returns:
            是否保存成功
        """
        with self._lock:
            try:
                config_path = self._get_config_path(agent_id)

                # 确保目录存在
                config_path.parent.mkdir(parents=True, exist_ok=True)

                # 保存配置
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config.to_dict(), f, ensure_ascii=False, indent=2)

                # 更新缓存
                self._configs[agent_id] = config

                logger.info("Saved media config for agent %s", agent_id)
                return True

            except Exception as e:
                logger.error("Failed to save media config for agent %s: %s", agent_id, e)
                return False

    def update_config(self, agent_id: str, updates: Dict[str, Any]) -> Optional[MediaStorageConfig]:
        """
        更新媒体存储配置

        Args:
            agent_id: Agent ID
            updates: 更新内容

        Returns:
            更新后的配置
        """
        with self._lock:
            config = self.get_config(agent_id)

            # 应用更新
            for key, value in updates.items():
                if hasattr(config, key):
                    setattr(config, key, value)

            # 保存配置
            if self.save_config(agent_id, config):
                return config

            return None

    def delete_config(self, agent_id: str) -> bool:
        """
        删除媒体存储配置

        Args:
            agent_id: Agent ID

        Returns:
            是否删除成功
        """
        with self._lock:
            try:
                config_path = self._get_config_path(agent_id)

                if config_path.exists():
                    config_path.unlink()

                # 从缓存中移除
                if agent_id in self._configs:
                    del self._configs[agent_id]

                logger.info("Deleted media config for agent %s", agent_id)
                return True

            except Exception as e:
                logger.error("Failed to delete media config for agent %s: %s", agent_id, e)
                return False

    def list_configs(self) -> List[str]:
        """
        列出所有配置

        Returns:
            Agent ID 列表
        """
        configs = []

        for config_file in self.config_dir.glob("*.json"):
            agent_id = config_file.stem
            configs.append(agent_id)

        return configs

    def _load_config(self, agent_id: str) -> MediaStorageConfig:
        """加载配置"""
        config_path = self._get_config_path(agent_id)

        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                return MediaStorageConfig.from_dict(data)

            except Exception as e:
                logger.warning("Failed to load config for agent %s: %s", agent_id, e)

        # 返回默认配置
        return MediaStorageConfig()

    def _get_config_path(self, agent_id: str) -> Path:
        """获取配置文件路径"""
        return self.config_dir / f"{agent_id}.json"


# 全局实例
_config_manager: Optional[MediaStorageConfigManager] = None


def get_media_storage_config(agent_id: str) -> MediaStorageConfig:
    """
    获取媒体存储配置的便捷函数

    Args:
        agent_id: Agent ID

    Returns:
        MediaStorageConfig 实例
    """
    global _config_manager

    if _config_manager is None:
        _config_manager = MediaStorageConfigManager()

    return _config_manager.get_config(agent_id)


def get_media_storage_config_manager() -> MediaStorageConfigManager:
    """获取媒体存储配置管理器"""
    global _config_manager

    if _config_manager is None:
        _config_manager = MediaStorageConfigManager()

    return _config_manager


def reset_media_storage_config_manager() -> None:
    """重置媒体存储配置管理器（用于测试）"""
    global _config_manager
    _config_manager = None
