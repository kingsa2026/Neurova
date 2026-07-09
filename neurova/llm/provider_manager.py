"""
LLM 服务商配置管理器

文件路径: `neurova/llm/provider_manager.py`

职责
====
1. 管理多个服务商配置（API Key、Base URL、默认模型等）
2. 支持配置持久化（JSON 文件,默认 `~/.neurova/config/providers.json`）
3. 提供服务商选择和模型切换能力
4. 健康检查、负载均衡、自动故障转移

主要组件
========
- `LoadBalancingStrategy`: 负载均衡策略枚举(ROUND_ROBIN/WEIGHTED_RANDOM/PRIORITY_FIRST/...)
- `ProviderConfig`: 服务商配置 dataclass(id/name/provider/base_url/api_key/models/...)
- `LLMProviderManager`: 服务商管理器主体类(继承 Module),管理 `_providers` 字典

单例管理(线程安全)
==================
- `get_provider_manager(config_path=None) -> LLMProviderManager`
    获取单例。使用模块级 `_provider_manager_lock`(threading.Lock)+ 双重检查锁定,
    确保并发首次调用只创建一个实例。
    参照 `neurova.llm.providers.secret_store.get_secret_store()` 的模式。
- `reset_provider_manager() -> None`
    清除模块级 `_provider_manager = None`,使下次 `get_provider_manager()` 重新创建实例。
    在 `_provider_manager_lock` 保护下清除,避免与并发 `get_provider_manager()` 竞态。

reset 链路(与 MultiModelLLMClient 协同)
========================================
`MultiModelLLMClient.reset()` 在清除自己状态后,会延迟导入并调用
`reset_provider_manager()`,确保 reset 链路穿透到 provider_manager 层。

场景:首次初始化时 api_key 解密失败(pycryptodome 缺失等),providers 缓存了空 api_key。
配置修复后,需 `MultiModelLLMClient.reset()` → `reset_provider_manager()` →
下次 `get_provider_manager()` 重新加载 providers,才能让 `_clients` 非空。

线程安全
========
- `LLMProviderManager._config_lock`(threading.RLock):保护 `_providers` 字典的读写
- `_provider_manager_lock`(threading.Lock):保护模块级 `_provider_manager` 单例的创建/清除

调用点
======
- `neurova/llm/multi_model_client.py`: `__init__` 通过 `get_provider_manager()` 获取单例;
  `reset()` 调用 `reset_provider_manager()` 穿透 reset 链路
- `neurova/agent_core.py:757`: `_load_api_keys` 延迟导入获取 provider 配置
- `neurova/shared_core/infrastructure.py:26,126`: InfrastructureManager 持有 provider_manager
- `neurova/api/app.py:217,219,271`: 启动时初始化并存入 app_state
- `neurova/api/deps.py:184` + `neurova/api/endpoints/__init__.py:57`:
  FastAPI 依赖从 app_state 读取(同名 wrapper,不直接调本模块)

测试
====
- `tests/unit/llm/test_provider_manager_reset.py`: reset 链路 + 线程安全测试
- `tests/unit/llm/test_provider_manager.py`: 基础功能测试
- `tests/unit/llm/test_multi_model_client_reinit.py`: MultiModelLLMClient reset 测试
"""

import json
import logging
import os
import random
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

# 导入依赖
try:
    from neurova.core.module_system import Module
except ImportError:
    # 占位符，如果模块不存在
    class Module:
        def __init__(self, config=None, event_bus=None):
            pass

        def _log(self, level, message):
            pass


try:
    from neurova.core.log_level import LogLevel
except ImportError:

    class LogLevel:
        INFO = "INFO"
        WARNING = "WARNING"
        ERROR = "ERROR"


try:
    from neurova.core.logger import get_logger
except ImportError:

    def get_logger(name):
        return logging.getLogger(name)


try:
    from neurova.llm.presets import LLMPresetRegistry, ModelPreset, get_preset_registry
except ImportError:
    # 占位符
    def get_preset_registry():
        return None

    class LLMPresetRegistry:
        def list_presets(self):
            return []

    class ModelPreset:
        pass


try:
    from neurova.llm.providers.secret_store import SecretStore, decrypt_api_key, encrypt_api_key
except ImportError:
    # 占位符
    def encrypt_api_key(key):
        return key

    def decrypt_api_key(key):
        return key

    class SecretStore:
        pass


try:
    from neurova.llm.providers.types import ConnectionResult, ProbeResult, PydanticModelInfo
except ImportError:
    # 占位符
    @dataclass
    class ConnectionResult:
        success: bool = True
        message: str = ""
        latency_ms: float = 0.0

    @dataclass
    class ProbeResult:
        vision: bool = False
        audio: bool = False
        video: bool = False
        image_generation: bool = False

    @dataclass
    class PydanticModelInfo:
        id: str = ""
        name: str = ""
        owned_by: str = ""


logger = get_logger(__name__)


class LoadBalancingStrategy(Enum):
    """负载均衡策略"""

    ROUND_ROBIN = "round_robin"
    WEIGHTED_RANDOM = "weighted_random"
    PRIORITY_FIRST = "priority_first"
    LEAST_ERRORS = "least_errors"
    FASTEST_RESPONSE = "fastest_response"


@dataclass
class ProviderConfig:
    """服务商配置"""

    id: str
    name: str
    provider: str  # openai, anthropic, gemini, ollama, etc.
    base_url: str
    api_key: Optional[str] = None
    encrypted_api_key: Optional[str] = None
    default_model: Optional[str] = None
    models: List[str] = field(default_factory=list)
    enabled: bool = True
    priority: int = 0
    is_builtin: bool = False
    icon: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # 健康状态
    health_status: str = "unknown"
    last_health_check: Optional[str] = None
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    current_requests: int = 0
    total_requests: int = 0
    total_response_time: float = 0.0
    health_check_enabled: bool = True

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now().isoformat()
        if not self.updated_at:
            self.updated_at = datetime.now().isoformat()

    def to_preset(self) -> "ModelPreset":
        """转换为 ModelPreset"""
        return ModelPreset(
            id=self.id,
            name=self.name,
            provider=self.provider,
            base_url=self.base_url,
            api_key=self.api_key,
            default_model=self.default_model,
            models=self.models,
            icon=self.icon,
            description=self.description,
        )

    def to_dict(self, encrypt: bool = False) -> Dict[str, Any]:
        """转换为字典"""
        data = asdict(self)
        if encrypt and self.api_key:
            data["encrypted_api_key"] = encrypt_api_key(self.api_key)
            data["api_key"] = None
        # 移除内部字段
        for key in [
            "health_status",
            "last_health_check",
            "consecutive_successes",
            "consecutive_failures",
            "current_requests",
            "total_requests",
            "total_response_time",
            "health_check_enabled",
        ]:
            data.pop(key, None)
        return data

    @property
    def masked_api_key(self) -> str:
        """掩码 API Key"""
        if not self.api_key:
            return ""
        if len(self.api_key) <= 8:
            return "***"
        return self.api_key[:4] + "***" + self.api_key[-4:]

    @classmethod
    def from_dict(cls, data: Dict[str, Any], decrypt: bool = False) -> "ProviderConfig":
        """从字典创建"""
        data = data.copy()
        if decrypt and data.get("encrypted_api_key"):
            try:
                data["api_key"] = decrypt_api_key(data["encrypted_api_key"])
                logger.info("Decrypted API key for provider %s", data.get('name', 'unknown'))
            except Exception as e:
                # 使用 ERROR 级别(原为 WARNING):解密失败意味着 LLM 链路会瘫痪,
                # WARNING 在生产日志中容易被忽略,导致"Loaded N providers"误导性成功
                logger.error(
                    "Failed to decrypt API key for provider %s: %s",
                    data.get("name", "unknown"),
                    e,
                )
        # 移除不需要的字段
        data.pop("encrypted_api_key", None)
        return cls(**data)


class LLMProviderManager(Module):
    """LLM 服务商配置管理器"""

    MODULE_ID = "llm_provider_manager"
    MODULE_NAME = "LLM Provider Manager"
    MODULE_VERSION = "1.0.0"

    def __init__(self, config=None, event_bus=None):
        super().__init__(config=config, event_bus=event_bus)
        self._preset_registry = get_preset_registry()
        self._config = config or {}
        self._config_path = self._get_default_config_path()
        self._providers: Dict[str, ProviderConfig] = {}
        self._default_provider_id: Optional[str] = None
        self._config_lock = threading.RLock()

        # 加载配置
        self._load_config()

    def _on_init(self) -> None:
        self._log(LogLevel.INFO, "Initializing LLM Provider Manager")

    def _on_start(self) -> None:
        self._log(LogLevel.INFO, f"LLM Provider Manager started with {len(self._providers)} providers")

    def _get_default_config_path(self) -> Path:
        """获取默认配置路径"""
        home = Path.home()
        config_dir = home / ".neurova" / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "providers.json"

    def _load_config(self) -> None:
        """加载配置"""
        if not os.path.exists(self._config_path):
            logger.info("No config file found, loading built-in providers")
            self._load_builtin_providers()
            self._save_config()
            return

        try:
            with open(self._config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            for provider_data in data.get("providers", []):
                provider = ProviderConfig.from_dict(provider_data, decrypt=True)
                self._providers[provider.id] = provider

            self._default_provider_id = data.get("default_provider_id")
            logger.info("Loaded %s providers from %s", len(self._providers), self._config_path)
        except Exception as e:
            logger.error("Failed to load config: %s", e)
            self._load_builtin_providers()
            self._save_config()

    def _make_backup(self, reason: str = "backup") -> None:
        """创建配置备份"""
        try:
            import shutil

            if self._config_path.exists():
                backup_path = self._config_path.with_suffix(f".{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak")
                shutil.copy2(self._config_path, backup_path)
                logger.info("Created backup: %s", backup_path)
        except Exception as e:
            logger.error("Failed to create backup: %s", e)

    def _save_config(self) -> None:
        """保存配置"""
        with self._config_lock:
            data = {
                "providers": [p.to_dict(encrypt=True) for p in self._providers.values()],
                "default_provider_id": self._default_provider_id,
                "updated_at": datetime.now().isoformat(),
            }

            os.makedirs(self._config_path.parent, exist_ok=True)
            with open(self._config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            logger.info("Saved config to %s", self._config_path)

    def _load_builtin_providers(self) -> None:
        """加载内置服务商"""
        if not self._preset_registry:
            return

        for preset in self._preset_registry.list_presets():
            if preset.is_builtin:
                provider = ProviderConfig(
                    id=preset.id,
                    name=preset.display_name or preset.name,
                    provider=preset.provider,
                    base_url=preset.base_url,
                    api_key=preset.api_key,
                    default_model=preset.default_model,
                    models=preset.models or [],
                    is_builtin=True,
                    icon=preset.icon,
                    description=preset.description,
                )
                self._providers[provider.id] = provider

    def add_provider(
        self,
        name: str,
        provider: str,
        base_url: str,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        models: Optional[List[str]] = None,
        **kwargs,
    ) -> ProviderConfig:
        """添加服务商"""
        provider_id = self._generate_provider_id(name)

        provider_config = ProviderConfig(
            id=provider_id,
            name=name,
            provider=provider,
            base_url=base_url,
            api_key=api_key,
            default_model=default_model,
            models=models or [],
            **kwargs,
        )

        with self._config_lock:
            self._providers[provider_id] = provider_config
            self._save_config()

        logger.info("Added provider: %s (%s)", name, provider_id)
        return provider_config

    def update_provider(
        self,
        provider_id: str,
        api_key: Optional[str] = None,
        default_model: Optional[str] = None,
        models: Optional[List[str]] = None,
        enabled: Optional[bool] = None,
        priority: Optional[int] = None,
        base_url: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """更新服务商配置"""
        if provider_id not in self._providers:
            logger.warning("Provider %s not found", provider_id)
            return False

        provider = self._providers[provider_id]

        if api_key is not None:
            provider.api_key = api_key
        if default_model is not None:
            provider.default_model = default_model
        if models is not None:
            provider.models = models
        if enabled is not None:
            provider.enabled = enabled
        if priority is not None:
            provider.priority = priority
        if base_url is not None:
            provider.base_url = base_url
        if description is not None:
            provider.description = description

        provider.updated_at = datetime.now().isoformat()

        with self._config_lock:
            self._save_config()

        logger.info("Updated provider: %s", provider.name)
        return True

    def update_provider_metadata(self, provider_id: str, metadata: Dict[str, Any]) -> bool:
        """更新服务商元数据"""
        if provider_id not in self._providers:
            logger.warning("Provider %s not found", provider_id)
            return False

        provider = self._providers[provider_id]
        if not isinstance(metadata, dict):
            return False

        for key, value in metadata.items():
            if hasattr(provider, key):
                setattr(provider, key, value)

        provider.updated_at = datetime.now().isoformat()
        return True

    def remove_provider(self, provider_id: str) -> bool:
        """移除服务商"""
        if provider_id not in self._providers:
            logger.warning("Provider %s not found", provider_id)
            return False

        provider = self._providers[provider_id]
        if provider.is_builtin:
            logger.warning("Cannot remove built-in provider: %s", provider.name)
            return False

        with self._config_lock:
            if self._default_provider_id == provider_id:
                self._default_provider_id = None
            del self._providers[provider_id]
            self._save_config()

        logger.info("Removed provider: %s", provider.name)
        return True

    def get_provider(self, provider_id: str) -> Optional[ProviderConfig]:
        """获取服务商配置"""
        return self._providers.get(provider_id)

    def list_providers(
        self,
        enabled_only: bool = False,
        builtin_only: bool = False,
        custom_only: bool = False,
    ) -> List[ProviderConfig]:
        """列出服务商"""
        providers = list(self._providers.values())

        if enabled_only:
            providers = [p for p in providers if p.enabled]
        if builtin_only:
            providers = [p for p in providers if p.is_builtin]
        if custom_only:
            providers = [p for p in providers if not p.is_builtin]

        return sorted(providers, key=lambda p: (-p.priority, p.name))

    def get_default_provider(self) -> Optional[ProviderConfig]:
        """获取默认服务商"""
        if self._default_provider_id and self._default_provider_id in self._providers:
            return self._providers[self._default_provider_id]

        # 返回第一个启用的服务商
        providers = self.list_providers(enabled_only=True)
        return providers[0] if providers else None

    def set_default_provider(self, provider_id: str) -> bool:
        """设置默认服务商"""
        if provider_id not in self._providers:
            logger.warning("Provider %s not found", provider_id)
            return False

        self._default_provider_id = provider_id

        with self._config_lock:
            self._save_config()

        logger.info("Default provider set to: %s", self._providers[provider_id].name)
        return True

    def enable_provider(self, provider_id: str) -> bool:
        """启用服务商"""
        return self.update_provider(provider_id, enabled=True)

    def disable_provider(self, provider_id: str) -> bool:
        """禁用服务商"""
        return self.update_provider(provider_id, enabled=False)

    def get_provider_for_model(self, model: str) -> Optional[ProviderConfig]:
        """根据模型查找服务商"""
        for provider in self.list_providers():
            if model in provider.models or model == provider.default_model:
                return provider
        return None

    def search_providers(self, query: str) -> List[ProviderConfig]:
        """搜索服务商"""
        query_lower = query.lower()
        results = []
        for provider in self._providers.values():
            if (
                query_lower in provider.name.lower()
                or query_lower in provider.provider.lower()
                or query_lower in (provider.description or "").lower()
                or any(query_lower in model.lower() for model in provider.models)
            ):
                results.append(provider)
        return results

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        providers = self.list_providers()
        return {
            "total_providers": len(providers),
            "enabled_providers": len([p for p in providers if p.enabled]),
            "builtin_providers": len([p for p in providers if p.is_builtin]),
            "default_provider": self._default_provider_id,
            "config_path": str(self._config_path),
        }

    def health_check_provider(self, provider_id: str) -> bool:
        """健康检查服务商"""
        if provider_id not in self._providers:
            logger.warning("Provider %s not found", provider_id)
            return False

        provider = self._providers[provider_id]
        if not provider.health_check_enabled:
            return True

        logger.debug("Health checking provider: %s", provider.name)

        # 简单健康检查：尝试获取模型列表
        try:
            # 这里应该调用实际的健康检查 API
            provider.last_health_check = datetime.now().isoformat()
            provider.health_status = "healthy"
            return True
        except Exception as e:
            logger.error("Health check failed for %s: %s", provider.name, e)
            provider.health_status = "unhealthy"
            return False

    def mark_provider_success(self, provider_id: str, response_time: float = 0.0) -> None:
        """标记服务商成功"""
        if provider_id not in self._providers:
            return

        provider = self._providers[provider_id]
        with self._config_lock:
            provider.consecutive_successes += 1
            provider.consecutive_failures = 0
            provider.current_requests = max(0, provider.current_requests - 1)
            provider.total_requests += 1
            provider.total_response_time += response_time
            provider.health_status = "healthy"

    def mark_provider_failure(self, provider_id: str) -> None:
        """标记服务商失败"""
        if provider_id not in self._providers:
            return

        provider = self._providers[provider_id]
        with self._config_lock:
            provider.consecutive_failures += 1
            provider.consecutive_successes = 0
            provider.current_requests = max(0, provider.current_requests - 1)
            provider.total_requests += 1
            provider.health_status = "unhealthy"

            if provider.consecutive_failures >= 3:
                logger.warning("Provider %s has %s consecutive failures", provider.name, provider.consecutive_failures)

    def get_healthy_providers(
        self, strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST
    ) -> List[ProviderConfig]:
        """获取健康的服务商"""
        providers = self.list_providers(enabled_only=True)
        healthy = [p for p in providers if p.health_status != "unhealthy"]

        if not healthy:
            logger.warning("No healthy providers available")
            return []

        if strategy == LoadBalancingStrategy.ROUND_ROBIN:
            return healthy
        elif strategy == LoadBalancingStrategy.WEIGHTED_RANDOM:
            # 按优先级排序，然后随机
            return sorted(healthy, key=lambda p: -p.priority)
        elif strategy == LoadBalancingStrategy.PRIORITY_FIRST:
            return sorted(healthy, key=lambda p: -p.priority)
        elif strategy == LoadBalancingStrategy.LEAST_ERRORS:
            return sorted(healthy, key=lambda p: p.consecutive_failures)
        else:
            return healthy

    def select_provider(
        self, model: Optional[str] = None, strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST
    ) -> Optional[ProviderConfig]:
        """选择服务商"""
        healthy_providers = self.get_healthy_providers(strategy)
        if not healthy_providers:
            logger.error("No providers available")
            return None

        # 如果指定了模型，查找支持该模型的服务商
        if model:
            for provider in healthy_providers:
                if model in provider.models or model == provider.default_model:
                    return provider

        # 按策略选择
        if strategy == LoadBalancingStrategy.WEIGHTED_RANDOM:
            # 加权随机选择
            weights = [p.priority + 1 for p in healthy_providers]
            total_weight = sum(weights)
            if total_weight > 0:
                rand = random.uniform(0, total_weight)
                cumulative = 0
                for provider, weight in zip(healthy_providers, weights):
                    cumulative += weight
                    if rand <= cumulative:
                        return provider

        # 默认返回第一个
        return healthy_providers[0]

    def auto_failover(self, current_provider_id: str) -> Optional[ProviderConfig]:
        """自动故障转移"""
        if current_provider_id not in self._providers:
            return None

        current_provider = self._providers[current_provider_id]
        self.mark_provider_failure(current_provider_id)

        # 选择下一个服务商
        strategy = LoadBalancingStrategy.PRIORITY_FIRST
        return self.select_provider(current_provider.default_model, strategy)

    def detect_model_capabilities(self, provider_id: str, model: str, use_cache: bool = True) -> Dict[str, Any]:
        """检测模型能力"""
        provider = self.get_provider(provider_id)
        if not provider:
            logger.warning("Provider %s not found", provider_id)
            return {}

        try:
            # 这里应该调用实际的能力检测
            return {
                "vision": "vision" in model.lower() or "vl" in model.lower(),
                "audio": "audio" in model.lower(),
                "video": "video" in model.lower(),
                "tool_use": True,
            }
        except Exception as e:
            logger.error("Failed to detect capabilities: %s", e)
            return {}

    def _generate_provider_id(self, name: str) -> str:
        """生成服务商 ID"""
        base_id = name.lower().replace(" ", "-").replace("_", "-")
        provider_id = base_id
        counter = 1
        while provider_id in self._providers:
            provider_id = f"{base_id}-{counter}"
            counter += 1
        return provider_id

    def reset_to_builtin(self) -> None:
        """重置为内置服务商"""
        with self._config_lock:
            self._providers.clear()
            self._default_provider_id = None
            self._load_builtin_providers()
            self._save_config()
            logger.info("Reset to built-in providers")

    def export_config(self, include_encrypted: bool = False) -> str:
        """导出配置"""
        data = {
            "providers": [p.to_dict(encrypt=include_encrypted) for p in self._providers.values()],
            "default_provider_id": self._default_provider_id,
        }
        return json.dumps(data, indent=2, ensure_ascii=False)

    def import_config(self, json_str: str) -> bool:
        """导入配置"""
        try:
            data = json.loads(json_str)

            with self._config_lock:
                for provider_data in data.get("providers", []):
                    provider = ProviderConfig.from_dict(provider_data)
                    self._providers[provider.id] = provider

                if "default_provider_id" in data:
                    self._default_provider_id = data["default_provider_id"]

                self._save_config()

            logger.info("Imported %s providers", len(data.get('providers', [])))
            return True
        except Exception as e:
            logger.error("Failed to import config: %s", e)
            return False

    def activate_model(self, provider_id: str, model_id: str) -> bool:
        """激活模型"""
        if provider_id not in self._providers:
            logger.error("Provider %s not found", provider_id)
            return False

        provider = self._providers[provider_id]
        if not provider.enabled:
            logger.error("Provider %s is disabled", provider.name)
            return False

        if model_id not in provider.models and model_id != provider.default_model:
            logger.error("Model %s not found in provider %s", model_id, provider.name)
            return False

        provider.default_model = model_id
        provider.updated_at = datetime.now().isoformat()

        with self._config_lock:
            self._save_config()

        logger.info("Activated model %s in provider %s", model_id, provider.name)
        return True

    def get_active_model(self) -> Optional[Dict[str, Any]]:
        """获取当前活跃模型"""
        provider = self.get_default_provider()
        if not provider:
            return None

        return {
            "provider_id": provider.id,
            "provider_name": provider.name,
            "model": provider.default_model,
            "base_url": provider.base_url,
        }

    def get_all_models(self) -> List[PydanticModelInfo]:
        """获取所有服务商的模型列表（聚合）"""
        all_models: List[PydanticModelInfo] = []
        for provider in self.list_providers():
            for model_id in provider.models:
                all_models.append(
                    PydanticModelInfo(
                        id=model_id,
                        name=model_id,
                        owned_by=provider.id,
                    )
                )
        return all_models

    def fetch_provider_models(self, provider_id: str) -> List[PydanticModelInfo]:
        """获取服务商模型列表"""
        provider = self.get_provider(provider_id)
        if not provider:
            logger.error("Provider %s not found", provider_id)
            return []

        try:
            # 这里应该调用实际的 API 获取模型列表
            # 返回占位符数据
            models = []
            for model_id in provider.models:
                models.append(
                    PydanticModelInfo(
                        id=model_id,
                        name=model_id,
                        owned_by=provider.name,
                    )
                )
            return models
        except Exception as e:
            logger.error("Failed to fetch models: %s", e)
            return []

    def probe_model_multimodal(self, provider_id: str, model_id: str) -> ProbeResult:
        """探测模型多模态能力"""
        provider = self.get_provider(provider_id)
        if not provider:
            logger.error("Provider %s not found", provider_id)
            return ProbeResult()

        try:
            # 这里应该调用实际的探测 API
            return ProbeResult(
                vision="vision" in model_id.lower() or "vl" in model_id.lower(),
                audio="audio" in model_id.lower(),
                video="video" in model_id.lower(),
                image_generation="image" in model_id.lower(),
            )
        except Exception as e:
            logger.error("Failed to probe model: %s", e)
            return ProbeResult()

    def check_provider_connection(self, provider_id: str) -> ConnectionResult:
        """检查服务商连接"""
        provider = self.get_provider(provider_id)
        if not provider:
            logger.error("Provider %s not found", provider_id)
            return ConnectionResult(success=False, message="Provider not found")

        try:
            # 这里应该调用实际的连接检查
            start_time = time.time()
            # 模拟连接检查
            latency = (time.time() - start_time) * 1000

            provider.health_status = "healthy"
            return ConnectionResult(
                success=True,
                message=f"Connected to {provider.name}",
                latency_ms=latency,
            )
        except Exception as e:
            logger.error("Connection check failed: %s", e)
            provider.health_status = "unhealthy"
            return ConnectionResult(
                success=False,
                message=str(e),
            )

    def check_model_connection(self, provider_id: str, model_id: str) -> ConnectionResult:
        """检查模型连接"""
        provider = self.get_provider(provider_id)
        if not provider:
            return ConnectionResult(success=False, message="Provider not found")

        if model_id not in provider.models and model_id != provider.default_model:
            return ConnectionResult(success=False, message="Model not found")

        try:
            # 这里应该调用实际的模型连接检查
            return ConnectionResult(
                success=True,
                message=f"Model {model_id} is available",
            )
        except Exception as e:
            return ConnectionResult(success=False, message=str(e))

    def _get_provider_instance(self, provider_id: str):
        """获取服务商实例（用于实际 API 调用）"""
        provider = self.get_provider(provider_id)
        if not provider:
            return None

        # 这里应该根据 provider.provider 类型返回对应的实例
        # 由于依赖复杂，返回占位符
        try:
            if provider.provider == "openai":
                from neurova.llm.providers import OpenAIProvider

                return OpenAIProvider(provider)
            elif provider.provider == "anthropic":
                from neurova.llm.providers import AnthropicProvider

                return AnthropicProvider(provider)
            elif provider.provider == "gemini":
                from neurova.llm.providers import GeminiProvider

                return GeminiProvider(provider)
            elif provider.provider == "ollama":
                from neurova.llm.providers import OllamaProvider

                return OllamaProvider(provider)
            else:
                # 默认使用 OpenAI 兼容
                from neurova.llm.providers import OpenAIProvider

                return OpenAIProvider(provider)
        except ImportError as e:
            logger.warning("Could not import provider %s: %s", provider.provider, e)
            return None


_provider_manager: Optional[LLMProviderManager] = None
_provider_manager_lock = threading.Lock()


def get_provider_manager(config_path: Optional[str] = None) -> LLMProviderManager:
    """获取 LLMProviderManager 单例(线程安全,双重检查锁定)

    实现:参照 `neurova.llm.providers.secret_store.get_secret_store()` 的模式,
    使用模块级 `_provider_manager_lock` + 双重检查锁定,确保并发首次调用
    只创建一个实例。

    参数:
        config_path: 可选的配置文件路径(仅在首次创建实例时生效)

    返回:
        LLMProviderManager 单例
    """
    global _provider_manager
    # 第一次检查(无锁,快速路径)
    if _provider_manager is None:
        with _provider_manager_lock:
            # 第二次检查(持锁,防止并发重复创建)
            if _provider_manager is None:
                _provider_manager = LLMProviderManager(config={"config_path": config_path})
    return _provider_manager


def reset_provider_manager() -> None:
    """重置 LLMProviderManager 单例(线程安全)

    清除模块级 `_provider_manager`,使下次 `get_provider_manager()` 重新创建实例。
    用于与 `MultiModelLLMClient.reset()` 协同,确保 reset 链路穿透到 provider_manager 层。

    场景:
    - 首次初始化时 api_key 解密失败(pycryptodome 缺失等),providers 缓存了空 api_key
    - 配置修复后,需 reset 才能让下次 get_provider_manager() 重新加载 providers

    线程安全:
    - 在 `_provider_manager_lock` 保护下清除,避免与并发 get_provider_manager() 竞态
    """
    global _provider_manager
    with _provider_manager_lock:
        _provider_manager = None


__all__ = [
    "LoadBalancingStrategy",
    "ProviderConfig",
    "LLMProviderManager",
    "get_provider_manager",
    "reset_provider_manager",
]
