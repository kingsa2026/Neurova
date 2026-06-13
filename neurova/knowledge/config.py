"""
知识库配置模块
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class FlowKBConfig(BaseModel):
    """流程知识库配置"""

    enabled: bool = True
    max_flows: int = 1000
    flow_ttl_days: int = 365
    auto_cleanup: bool = True
    storage_backend: str = "sqlite"  # sqlite, postgres, memory
    connection_string: Optional[str] = None
    cache_size: int = 1000
    cache_ttl_seconds: int = 3600
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    max_versions_per_flow: int = 10
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True


class KnowledgeBaseConfig(BaseModel):
    """知识库配置"""

    # 基础配置
    enabled: bool = True
    name: str = "Neurova Knowledge Base"
    description: str = ""
    version: str = "1.0.0"

    # 存储配置
    storage_backend: str = "sqlite"  # sqlite, postgres, memory, file
    connection_string: Optional[str] = None
    data_dir: Optional[str] = None

    # 向量数据库配置
    vector_store_enabled: bool = True
    vector_store_backend: str = "faiss"  # faiss, chroma, memory
    vector_store_path: Optional[str] = None
    embedding_model: str = "all-MiniLM-L6-v2"
    embedding_dimension: int = 384

    # 缓存配置
    cache_enabled: bool = True
    cache_size: int = 10000
    cache_ttl_seconds: int = 3600

    # 备份配置
    backup_enabled: bool = True
    backup_interval_hours: int = 24
    backup_retention_days: int = 30
    backup_path: Optional[str] = None

    # 性能配置
    max_connections: int = 10
    query_timeout_seconds: int = 30
    batch_size: int = 100
    async_enabled: bool = True

    # 安全配置
    encryption_enabled: bool = False
    encryption_key: Optional[str] = None
    access_control_enabled: bool = True

    # 日志配置
    logging_enabled: bool = True
    log_level: str = "INFO"
    log_file: Optional[str] = None

    # 流程知识库配置
    flow_kb: FlowKBConfig = Field(default_factory=FlowKBConfig)

    # 扩展配置
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True

    def get_data_dir(self) -> Path:
        """获取数据目录"""
        if self.data_dir:
            return Path(self.data_dir)
        return Path("data/knowledge")

    def get_vector_store_path(self) -> Path:
        """获取向量存储路径"""
        if self.vector_store_path:
            return Path(self.vector_store_path)
        return self.get_data_dir() / "vector_store"

    def get_backup_path(self) -> Path:
        """获取备份路径"""
        if self.backup_path:
            return Path(self.backup_path)
        return self.get_data_dir() / "backups"

    def get_connection_string(self) -> str:
        """获取连接字符串"""
        if self.connection_string:
            return self.connection_string

        # 默认使用 SQLite
        if self.storage_backend == "sqlite":
            db_path = self.get_data_dir() / "knowledge.db"
            return f"sqlite:///{db_path}"

        return ""

    def validate_config(self) -> List[str]:
        """验证配置"""
        errors = []

        # 检查存储后端
        valid_backends = ["sqlite", "postgres", "memory", "file"]
        if self.storage_backend not in valid_backends:
            errors.append(f"Invalid storage backend: {self.storage_backend}")

        # 检查向量存储后端
        valid_vector_backends = ["faiss", "chroma", "memory"]
        if self.vector_store_backend not in valid_vector_backends:
            errors.append(f"Invalid vector store backend: {self.vector_store_backend}")

        # 检查缓存大小
        if self.cache_size < 0:
            errors.append("Cache size must be non-negative")

        # 检查连接数
        if self.max_connections < 1:
            errors.append("Max connections must be at least 1")

        # 检查超时时间
        if self.query_timeout_seconds < 0:
            errors.append("Query timeout must be non-negative")

        return errors


# 全局配置实例
_knowledge_config: Optional[KnowledgeBaseConfig] = None
_config_lock = threading.RLock()


def get_knowledge_config() -> KnowledgeBaseConfig:
    """
    获取知识库配置

    Returns:
        KnowledgeBaseConfig 实例
    """
    global _knowledge_config

    with _config_lock:
        if _knowledge_config is None:
            # 尝试从文件加载
            config_path = _find_config_file()
            if config_path and config_path.exists():
                try:
                    _knowledge_config = _load_config_from_file(config_path)
                    logger.info("Loaded knowledge config from %s", config_path)
                except Exception as e:
                    logger.warning("Failed to load config from %s: %s", config_path, e)
                    _knowledge_config = KnowledgeBaseConfig()
            else:
                _knowledge_config = KnowledgeBaseConfig()
                logger.info("Created default knowledge config")

        return _knowledge_config


def save_knowledge_config(config: KnowledgeBaseConfig, config_path: Optional[Path] = None) -> bool:
    """
    保存知识库配置

    Args:
        config: 配置对象
        config_path: 配置文件路径

    Returns:
        是否保存成功
    """
    global _knowledge_config

    with _config_lock:
        try:
            # 确定保存路径
            if config_path is None:
                config_path = _get_default_config_path()

            # 确保目录存在
            config_path.parent.mkdir(parents=True, exist_ok=True)

            # 验证配置
            errors = config.validate_config()
            if errors:
                logger.error("Config validation failed: %s", errors)
                return False

            # 保存到文件
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config.dict(), f, ensure_ascii=False, indent=2)

            # 更新全局配置
            _knowledge_config = config

            logger.info("Saved knowledge config to %s", config_path)
            return True

        except Exception as e:
            logger.error("Failed to save knowledge config: %s", e)
            return False


def _find_config_file() -> Optional[Path]:
    """查找配置文件"""
    # 检查环境变量
    env_path = os.environ.get("NEUROVA_KNOWLEDGE_CONFIG")
    if env_path:
        return Path(env_path)

    # 检查默认路径
    default_path = _get_default_config_path()
    if default_path.exists():
        return default_path

    # 检查当前目录
    current_dir = Path.cwd()
    for path in [current_dir / "knowledge_config.json", current_dir / "config" / "knowledge_config.json"]:
        if path.exists():
            return path

    return None


def _get_default_config_path() -> Path:
    """获取默认配置文件路径"""
    # 使用用户目录
    home_dir = Path.home()
    config_dir = home_dir / ".neurova" / "config"
    return config_dir / "knowledge_config.json"


def _load_config_from_file(config_path: Path) -> KnowledgeBaseConfig:
    """从文件加载配置"""
    with open(config_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return KnowledgeBaseConfig(**data)


def create_knowledge_config(**kwargs) -> KnowledgeBaseConfig:
    """
    创建知识库配置

    Args:
        **kwargs: 配置参数

    Returns:
        KnowledgeBaseConfig 实例
    """
    return KnowledgeBaseConfig(**kwargs)


def update_knowledge_config(updates: Dict[str, Any]) -> KnowledgeBaseConfig:
    """
    更新知识库配置

    Args:
        updates: 更新内容

    Returns:
        更新后的配置
    """
    config = get_knowledge_config()

    # 应用更新
    for key, value in updates.items():
        if hasattr(config, key):
            setattr(config, key, value)

    # 保存配置
    save_knowledge_config(config)

    return config


def reset_knowledge_config() -> None:
    """重置知识库配置（用于测试）"""
    global _knowledge_config

    with _config_lock:
        _knowledge_config = None


def get_config_summary() -> Dict[str, Any]:
    """获取配置摘要"""
    config = get_knowledge_config()

    return {
        "name": config.name,
        "version": config.version,
        "storage_backend": config.storage_backend,
        "vector_store_enabled": config.vector_store_enabled,
        "vector_store_backend": config.vector_store_backend,
        "cache_enabled": config.cache_enabled,
        "cache_size": config.cache_size,
        "backup_enabled": config.backup_enabled,
        "encryption_enabled": config.encryption_enabled,
        "flow_kb_enabled": config.flow_kb.enabled,
    }
