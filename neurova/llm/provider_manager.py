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

import inspect
import json
import logging
import os
import random
import re
import shutil
import threading
import time
from dataclasses import asdict, dataclass, field, fields
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
    from neurova.llm.providers.types import (
        ConnectionResult,
        ModelInfo as PydanticModelInfo,
        ProbeResult,
        ProviderCapability,
        ProviderType,
    )
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

    class ProviderCapability:
        pass


logger = get_logger(__name__)

# 免 API Key 的服务商(免费网关内置定义):无 key 时发现/筛选仍须放行
KEYLESS_PROVIDER_IDS: frozenset = frozenset({"opencode", "kilo-code"})

# 内置服务商定义(与前端 ModelPage 种子卡片对齐;缺失时才补入,绝不覆盖用户配置)
_BUILTIN_PROVIDER_DEFS: tuple[dict, ...] = (
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "provider": "openrouter",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_prefix": "sk-or-v1-",
    },
    {
        "id": "opencode",
        "name": "OpenCode",
        "provider": "opencode",
        "base_url": "https://opencode.ai/zen/v1",
    },
    {
        "id": "kilo-code",
        "name": "Kilo Code",
        "provider": "kilo",
        "base_url": "https://api.kilo.ai/api/gateway",
    },
    {
        "id": "github-models",
        "name": "GitHub Models",
        "provider": "openai",
        "base_url": "https://models.github.ai/inference",
    },
    {
        # 商汤 LLM:真实端点 token.sensenova.cn/v1(OpenAI 兼容)。
        # 曾查实前端卡片写的是 api.sensetime.com/v1(不可用),用户须手动
        # 新建自定义 provider 才能用 —— 内置后填 key 即开箱。
        "id": "sensetime",
        "name": "商汤科技",
        "provider": "openai",
        "base_url": "https://token.sensenova.cn/v1",
        "api_key_prefix": "",
    },
)


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
    api_key_prefix: str = ""
    default_model: Optional[str] = None
    models: List[str] = field(default_factory=list)
    # 发现候选(与 models 分离):fetch 写入、merge 显式并入,持久化
    discovered_models: List[str] = field(default_factory=list)
    # 模型发现同步元数据(QwenPaw 对齐):成功时间戳/最后一次失败原因,持久化
    models_last_synced_at: Optional[str] = None
    models_last_sync_error: Optional[str] = None
    # 模型元数据:model_id -> 模型档案(dict,含 capabilities/context_window/pricing 等)。
    # models 保持字符串列表契约以兼容存量消费者;元数据仅承载增强信息。
    model_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    enabled: bool = True
    # P1-13 真账单采集开关（OpenClaw provider-usage 启发，默认关）：
    # 显式置 true 后 /stats/provider-usage 才会拉取该 provider 后台账单
    usage_collection: bool = False
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
        # 未知字段容错:旧版本/外部工具写出的配置可能带已废弃字段
        # (如 metadata/weight/health_check_interval)。一个未知键曾让整份
        # 配置加载炸进异常分支 → 内置种子覆盖(2026-09-05 事故原始触发点)。
        valid_fields = {f.name for f in fields(cls)}
        unknown = set(data) - valid_fields
        if unknown:
            logger.warning(
                "Ignoring unknown/legacy fields for provider %s: %s",
                data.get("id", "?"),
                sorted(unknown),
            )
            for key in unknown:
                data.pop(key)
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
        # config_path 显式传入时优先(scope 化配置路径由此派发)
        explicit_path = self._config.get("config_path")
        if explicit_path:
            self._config_path = Path(str(explicit_path))
        else:
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
            # 存量配置补内置定义(仅缺失 id;覆盖在用户保存时持久化)
            self._merge_builtin_providers_if_missing()
        except Exception as e:
            # 配置文件损坏(半截 JSON/格式漂移)时,先转存原始字节再重建。
            # 绝不允许无备份覆盖:2026-09-05 事故中此处曾用内置种子直接
            # 覆盖真实配置,用户全部服务商配置不可逆丢失。
            corrupt_backup = Path(
                str(self._config_path)
                + f".corrupt-{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak"
            )
            try:
                shutil.copy2(self._config_path, corrupt_backup)
                logger.error(
                    "Config file corrupted (%s); original preserved at %s",
                    e,
                    corrupt_backup,
                )
            except Exception as backup_err:
                logger.error(
                    "Config file corrupted (%s) AND backup failed: %s — refusing to overwrite",
                    e,
                    backup_err,
                )
                raise
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
        """保存配置(原子写:临时文件 + os.replace,杜绝并发读读到半截 JSON)"""
        with self._config_lock:
            data = {
                "providers": [p.to_dict(encrypt=True) for p in self._providers.values()],
                "default_provider_id": self._default_provider_id,
                "updated_at": datetime.now().isoformat(),
            }

            os.makedirs(self._config_path.parent, exist_ok=True)
            tmp_path = self._config_path.with_suffix(
                f".{datetime.now().strftime('%Y%m%d_%H%M%S%f')}.tmp"
            )
            try:
                with open(tmp_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, self._config_path)
            except BaseException:
                # 写失败/中断时清掉半截临时文件;原配置文件未被触碰
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

            logger.info("Saved config to %s", self._config_path)

    def _load_builtin_providers(self) -> None:
        """内置服务商种子:只补缺失 id,绝不覆盖用户已配置项。

        前端 ModelPage 的 BUILTIN_PROVIDERS 卡片(30+)本质是展示层;
        后端必须有对应实体才能让「配置/发现/筛选」工作 —— 这里提供与
        前端种子对齐的核心定义(openrouter/opencode/kilo/github-models)。
        无默认可配模型(models=[]):真实清单由发现流程填充。
        """
        for definition in _BUILTIN_PROVIDER_DEFS:
            if definition["id"] in self._providers:
                continue
            self._providers[definition["id"]] = ProviderConfig(
                id=definition["id"],
                name=definition["name"],
                provider=definition["provider"],
                base_url=definition["base_url"],
                api_key_prefix=definition.get("api_key_prefix", ""),
                models=[],
                is_builtin=True,
            )
        logger.info(
            "Merged built-in provider seeds: %s",
            ", ".join(
                d["id"]
                for d in _BUILTIN_PROVIDER_DEFS
                if d["id"] in self._providers
            ),
        )

    def _merge_builtin_providers_if_missing(self) -> None:
        """既有配置加载后补内置定义(内存层;下次保存时随配置持久化)。"""
        self._load_builtin_providers()

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
        usage_collection: Optional[bool] = None,
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
            # 同步清理已删除模型的元数据残留(defensive)
            metadata = dict(provider.model_metadata or {})
            remaining = set(models)
            pruned = {
                model_id: meta
                for model_id, meta in metadata.items()
                if model_id in remaining
            }
            if pruned != metadata:
                provider.model_metadata = pruned
        if enabled is not None:
            provider.enabled = enabled
        if priority is not None:
            provider.priority = priority
        if base_url is not None:
            provider.base_url = base_url
        if description is not None:
            provider.description = description
        # P1-13 断链修复: 真账单采集开关经 API 可达（复审断点②）
        if usage_collection is not None:
            provider.usage_collection = usage_collection

        provider.updated_at = datetime.now().isoformat()

        with self._config_lock:
            self._save_config()

        logger.info("Updated provider: %s", provider.name)
        return True

    def rename_model_entry(
        self,
        provider_id: str,
        old_id: str,
        new_id: Optional[str] = None,
        name: Optional[str] = None,
    ) -> bool:
        """编辑模型条目:改模型 ID 或显示名称(内置/发现的条目同样可编辑)。

        - 改 ID:models 列表替换、model_metadata 键迁移、default_model 同步
        - 改名称:写入 model_metadata[model_id]["name"];无元数据条目时补建
        条目归属用户配置的 provider 实体,不影响内置种子(种子只补缺失 id,
        models 恒为空,删除/改名不会被种子覆盖)。
        """
        provider = self._providers.get(provider_id)
        if provider is None or old_id not in (provider.models or []):
            return False

        new_id = (new_id or old_id).strip() or old_id
        if new_id == old_id and not name:
            return False

        metadata = dict(provider.model_metadata or {})
        new_models: Optional[List[str]] = None
        new_default: Optional[str] = None

        if new_id != old_id:
            if old_id in metadata:
                meta = dict(metadata.pop(old_id))
                meta["id"] = new_id
                metadata.setdefault(new_id, meta)
            new_models = [new_id if m == old_id else m for m in provider.models]
            if provider.default_model == old_id:
                new_default = new_id

        if name:
            meta = metadata.get(new_id) or {"id": new_id}
            meta["name"] = name
            metadata[new_id] = meta

        provider.model_metadata = metadata
        return self.update_provider(
            provider_id,
            models=new_models,
            default_model=new_default,
        )

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
        # QwenPaw 对齐:激活后对未探测过的模型调度后台多模态探测
        self.maybe_probe_multimodal(provider_id, model_id)
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

    @staticmethod
    def _generic_filter_models(
        models: List[PydanticModelInfo],
        providers: Optional[List[str]] = None,
        input_modalities: Optional[List[str]] = None,
        output_modalities: Optional[List[str]] = None,
        max_prompt_price: Optional[float] = None,
        is_free: Optional[bool] = None,
    ) -> List[PydanticModelInfo]:
        """通用四维过滤(不依赖 provider 特化 filter_models)。

        系列取自 model_id 前缀(openai/gpt-4o → openai),无前缀回退 provider 字段;
        modality 按 ProviderCapability 值匹配(OR 语义);价格为每 1M tokens 的 prompt 上限。
        """
        capability_index = {
            "text": "text",
            "image": "vision",
            "audio": "audio",
            "video": "video",
        }
        result = list(models)

        if providers:
            providers_lower = [p.lower() for p in providers]
            result = [
                m
                for m in result
                if (
                    (m.id.split("/", 1)[0].lower() in providers_lower
                     if "/" in m.id
                     else False)
                    or (not m.id.split("/", 1)[0] and (m.provider or "").lower() in providers_lower)
                )
            ]

        if input_modalities:
            wanted = {
                capability_index[mod]
                for mod in input_modalities
                if mod in capability_index
            }
            if wanted:
                result = [
                    m
                    for m in result
                    if any(
                        (getattr(cap, "value", cap) in wanted)
                        for cap in (m.capabilities or [])
                    )
                ]

        if max_prompt_price is not None:
            result = [
                m
                for m in result
                if (m.pricing or {}).get("input") is not None
                and (m.pricing or {}).get("input") <= max_prompt_price
            ]

        if is_free is True:
            result = [m for m in result if m.is_free]
        return result

    async def filter_provider_models(
        self,
        provider_id: str,
        providers: Optional[List[str]] = None,
        input_modalities: Optional[List[str]] = None,
        output_modalities: Optional[List[str]] = None,
        max_prompt_price: Optional[float] = None,
        is_free: Optional[bool] = None,
    ) -> List[PydanticModelInfo]:
        """按 QwenPaw 四维语义筛选服务商模型列表。

        优先复用 provider 特化的 filter_models(如 OpenRouter 的系列多态);
        无特化实现的实例(OpenCode/OpenAI 兼容等)走通用过滤。
        """
        provider = self.get_provider(provider_id)
        if provider is None:
            return []
        instance = self._get_provider_instance(provider_id)
        if instance is None:
            return []
        models = await instance.fetch_models()
        filter_models = getattr(instance, "filter_models", None)
        if filter_models is not None:
            return filter_models(
                models,
                providers=providers,
                input_modalities=input_modalities,
                output_modalities=output_modalities,
                max_prompt_price=max_prompt_price,
                is_free=is_free,
            )
        return self._generic_filter_models(
            models,
            providers=providers,
            input_modalities=input_modalities,
            output_modalities=output_modalities,
            max_prompt_price=max_prompt_price,
            is_free=is_free,
        )

    def get_all_models(self) -> List[PydanticModelInfo]:
        """获取所有服务商的模型列表(聚合,携带模型元数据)

        兜底:元数据缺 capabilities/context_window/max_tokens 时,即时推断能力、
        按预埋目录(model_limits 精确表优先)补限额 —— 检测尚未显式执行过也能在
        /models、/models/by-capability 响应中拿到完整模型档案。
        """
        from neurova.llm.capability_detector import (
            apply_preset_defaults,
            detect_model_capabilities,
        )

        all_models: List[PydanticModelInfo] = []
        for provider in self.list_providers():
            model_ids = list(getattr(provider, "models", None) or [])
            if provider.default_model and provider.default_model not in model_ids:
                model_ids.append(provider.default_model)
            for model_id in model_ids:
                meta = dict((provider.model_metadata or {}).get(model_id, {}) or {})
                if not (meta.get("capabilities") or []):
                    meta["capabilities"] = detect_model_capabilities(
                        model_id,
                        display_name=str(meta.get("name") or ""),
                    )
                # 三元组兜底合并（服务商已有值首选，仅补缺）
                meta = apply_preset_defaults(model_id, meta)
                view = self._build_model_view(provider, model_id)
                if view.context_window in (None, 0, 4096) and meta.get("context_window") not in (None, 0, 4096):
                    view.context_window = int(meta["context_window"])
                if view.max_tokens in (None, 0, 4096) and meta.get("max_tokens") not in (None, 0, 4096):
                    view.max_tokens = int(meta["max_tokens"])
                if not (view.capabilities or []):
                    view.capabilities = list(meta.get("capabilities") or [])
                all_models.append(view)
        return all_models

    @staticmethod
    def _build_model_view(
        provider: ProviderConfig,
        model_id: str,
    ) -> PydanticModelInfo:
        """构建 ModelInfo 视图:元数据优先,缺失时退回 id-as-name。"""
        meta = (provider.model_metadata or {}).get(model_id, {}) or {}
        try:
            provider_type = ProviderType(provider.provider)
        except ValueError:
            provider_type = ProviderType.OPENAI
        capabilities = meta.get("capabilities") or []
        return PydanticModelInfo(
            id=model_id,
            name=meta.get("name") or model_id,
            provider=provider.provider,
            provider_type=provider_type,
            capabilities=capabilities,
            max_tokens=int(meta.get("max_tokens", 4096) or 4096),
            context_window=int(meta.get("context_window", 4096) or 4096),
            pricing=dict(meta.get("pricing") or {}),
            metadata=dict(meta.get("metadata") or {}),
            owned_by=provider.id,
            is_free=bool(meta.get("is_free", False)),
        )

    def _resolve_provider(
        self,
        model_id: str,
        provider_id: Optional[str] = None,
    ) -> Optional[ProviderConfig]:
        """按 model_id 定位服务商;显式 provider_id 优先但需归属一致。"""
        model_id = model_id.strip()
        if provider_id:
            provider = self.get_provider(provider_id)
            if provider is not None:
                if (
                    model_id in (provider.models or [])
                    or model_id == provider.default_model
                    or provider_id == provider.id
                ):
                    return provider
        for provider in self.list_providers():
            if model_id in (provider.models or []) or model_id == provider.default_model:
                return provider
        return None

    async def discover_provider_models(
        self,
        provider_id: str,
        merge: bool = True,
    ) -> Dict[str, Any]:
        """结构化模型发现（QwenPaw discover_provider_models 对齐）。

        Returns:
            {"success", "models", "discovered_count", "last_synced_at",
             "used_static_fallback", "error_kind", "message"}
        - 失败不再静默空列表：error_kind 分类 + used_static_fallback
          （回退配置存量视图）；错误分类单一事实源为 error_mapping 五类。
        - 成功时 last_synced_at 持久化到 ProviderConfig.models_last_synced_at。
        - discovered_count = 本次新进入配置/候选的模型数。
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return {
                "success": False,
                "models": [],
                "discovered_count": 0,
                "last_synced_at": None,
                "used_static_fallback": False,
                "error_kind": "provider_not_found",
                "message": f"Provider {provider_id} not found",
            }

        def _static_view() -> List[PydanticModelInfo]:
            return [
                self._build_model_view(provider, model_id)
                for model_id in getattr(provider, "models", [])
            ]

        instance = self._get_provider_instance(provider_id)
        if instance is None:
            return {
                "success": False,
                "models": _static_view(),
                "discovered_count": 0,
                "last_synced_at": provider.models_last_synced_at,
                "used_static_fallback": True,
                "error_kind": "configuration",
                "message": "Provider instance unavailable, showing configured models",
            }

        try:
            models = await instance.fetch_models()
        except Exception as e:
            from neurova.llm.providers.error_mapping import normalize_provider_error

            normalized = normalize_provider_error(e)
            kind_map = {
                "auth_failed": "authentication",
                "connection_failed": "network",
                "service_unavailable": "provider_unavailable",
                "rate_limited": "rate_limited",
                "bad_request": "invalid_response",
            }
            error_kind = kind_map.get(normalized.category.value, "provider_unavailable")
            with self._config_lock:
                provider.models_last_sync_error = str(e)[:300]
                self._save_config()
            return {
                "success": False,
                "models": _static_view(),
                "discovered_count": 0,
                "last_synced_at": provider.models_last_synced_at,
                "used_static_fallback": True,
                "error_kind": error_kind,
                "message": str(e),
            }

        if not models:
            # 空结果消歧（QwenPaw _probe_discovery_failure_reason）：
            # 可能是真没有模型，也可能是请求失败被底层吞掉 — 拉连通性区分
            check = await self.check_provider_connection(provider_id)
            if not check.success:
                with self._config_lock:
                    provider.models_last_sync_error = check.error or "provider unreachable"
                    self._save_config()
                return {
                    "success": False,
                    "models": _static_view(),
                    "discovered_count": 0,
                    "last_synced_at": provider.models_last_synced_at,
                    "used_static_fallback": True,
                    "error_kind": "provider_unavailable",
                    "message": check.error or "Provider unreachable",
                }

        from neurova.llm.capability_detector import (
            apply_preset_defaults,
            detect_model_capabilities,
        )

        with self._config_lock:
            metadata = dict(provider.model_metadata or {})
            for model in models:
                entry = model.to_dict()
                entry["owned_by"] = provider_id
                # 自动检测能力标记:发现链路写入时缺 capabilities 则推断补齐并持久化
                if not (entry.get("capabilities") or []):
                    old_entry = metadata.get(model.id, {}) or {}
                    entry["capabilities"] = detect_model_capabilities(
                        model.id,
                        existing=old_entry.get("capabilities") or [],
                        display_name=str(model.name or ""),
                    )
                # 限额三元组兜底:服务商返回的真实值首选,缺省(或 4096 占位)才按预埋补
                entry = apply_preset_defaults(model.id, entry)
                metadata[model.id] = entry
            current_ids = set(provider.models or [])
            if merge:
                # 发现结果持久化:新模型追加进配置列表(前端"发现模型"刷新不丢失);
                # 已配置模型保持原有顺序,不重复追加。
                added_ids = [
                    model.id for model in models if model.id not in current_ids
                ]
                if added_ids:
                    provider.models = [*(provider.models or []), *added_ids]
                provider.discovered_models = []
                discovered_count = len(added_ids)
            else:
                provider.discovered_models = [
                    model.id for model in models if model.id not in current_ids
                ]
                discovered_count = len(provider.discovered_models)
            provider.model_metadata = metadata
            synced_at = datetime.now().isoformat()
            provider.models_last_synced_at = synced_at
            provider.models_last_sync_error = None
            self._save_config()

        return {
            "success": True,
            "models": list(models),
            "discovered_count": discovered_count,
            "last_synced_at": synced_at,
            "used_static_fallback": False,
            "error_kind": None,
            "message": "",
        }

    async def fetch_provider_models(
        self,
        provider_id: str,
        merge: bool = True,
    ) -> List[PydanticModelInfo]:
        """发现服务商模型列表（薄壳：委托 discover_provider_models，
        保持旧 List 契约供 multi_model_client 404 重连等消费方使用）。"""
        result = await self.discover_provider_models(provider_id, merge=merge)
        return result["models"]

    def merge_discovered_models(
        self,
        provider_id: str,
        model_ids: Optional[List[str]] = None,
    ) -> int:
        """把发现候选并入配置列表(幂等),返回实际并入数量。

        - ``model_ids=None``:并入全部候选;否则仅并入选中 id。
        - 已在配置中的 id、不在候选中的 id 均被忽略。
        - 已选中的候选从 discovered_models 移除,未选中的保留。
        """
        provider = self.get_provider(provider_id)
        if provider is None:
            return 0
        configured = set(provider.models or [])
        candidates = [
            model_id
            for model_id in (provider.discovered_models or [])
            if model_id not in configured
        ]
        if model_ids is not None:
            chosen = [model_id for model_id in model_ids if model_id in candidates]
        else:
            chosen = candidates
        if not chosen:
            return 0
        with self._config_lock:
            provider.models = [*(provider.models or []), *chosen]
            chosen_set = set(chosen)
            configured = set(provider.models or [])
            provider.discovered_models = [
                model_id
                for model_id in (provider.discovered_models or [])
                if model_id not in chosen_set and model_id not in configured
            ]
            self._save_config()
        logger.info(
            "Merged %s discovered models into provider %s",
            len(chosen),
            provider.name,
        )
        return len(chosen)

    # ------------------------------------------------------------------
    # 模型能力自动检测与持久化(2026-09-03)
    # ------------------------------------------------------------------
    def set_model_capabilities(
        self,
        provider_id: str,
        model_id: str,
        capabilities: List[str],
    ) -> bool:
        """写入单个模型的显式能力标记并持久化(合并进 model_metadata,限额随预埋兜底)。"""
        from neurova.llm.capability_detector import (
            apply_preset_defaults,
            detect_model_capabilities,
        )

        provider = self.get_provider(provider_id)
        if provider is None:
            logger.warning("set_model_capabilities: provider %s not found", provider_id)
            return False

        canonical = detect_model_capabilities(model_id, existing=capabilities)
        with self._config_lock:
            metadata = dict(provider.model_metadata or {})
            entry = dict(metadata.get(model_id, {}) or {})
            entry["capabilities"] = canonical
            entry = apply_preset_defaults(model_id, entry)
            metadata[model_id] = entry
            provider.model_metadata = metadata
            self._save_config()
        return True

    def detect_and_persist_capabilities(
        self,
        provider_id: Optional[str] = None,
        model_id: Optional[str] = None,
        force: bool = False,
    ) -> Dict[str, Any]:
        """批量检测模型能力并持久化。

        - ``provider_id`` 缺省 → 全部服务商;``model_id`` 缺省 → 该商全部模型。
        - ``force=False``(默认)跳过已有显式 capabilities 的模型(幂等);
          ``force=True`` 强制重检。
        - 检测顺序:显式元数据 > 已知模型目录 > 名称启发式(见 capability_detector)。

        Returns:
            {"detected": 实际检测并持久化的模型数,
             "results": [{"provider_id", "provider_name", "model_id", "capabilities"}]}
        """
        from neurova.llm.capability_detector import (
            apply_preset_defaults,
            detect_model_capabilities,
        )

        results: List[Dict[str, Any]] = []
        with self._config_lock:
            for pid, provider in self._providers.items():
                if provider_id is not None and pid != provider_id:
                    continue
                model_ids = list(getattr(provider, "models", None) or [])
                if provider.default_model and provider.default_model not in model_ids:
                    model_ids.append(provider.default_model)
                if model_id is not None:
                    model_ids = [m for m in model_ids if m == model_id]

                metadata = dict(provider.model_metadata or {})
                changed = False
                for mid in model_ids:
                    entry = dict(metadata.get(mid, {}) or {})
                    existing = entry.get("capabilities") or []
                    if existing and not force:
                        results.append(
                            {
                                "provider_id": pid,
                                "provider_name": provider.name,
                                "model_id": mid,
                                "capabilities": list(existing),
                            }
                        )
                        continue
                    caps = detect_model_capabilities(
                        mid,
                        existing=existing,
                        display_name=str(entry.get("name") or ""),
                    )
                    entry["capabilities"] = caps
                    # 三元组兜底(服务商自有值首选):能力外同时补缺 context_window/max_tokens
                    entry = apply_preset_defaults(mid, entry)
                    metadata[mid] = entry
                    changed = True
                    results.append(
                        {
                            "provider_id": pid,
                            "provider_name": provider.name,
                            "model_id": mid,
                            "capabilities": caps,
                            "context_window": entry.get("context_window"),
                            "max_tokens": entry.get("max_tokens"),
                        }
                    )
                if changed:
                    provider.model_metadata = metadata
            self._save_config()

        logger.info("Capability detection persisted for %s models", len(results))
        return {"detected": len(results), "results": results}

    async def probe_model_multimodal(
        self,
        model_id: str,
        provider_id: Optional[str] = None,
        force: bool = False,
    ) -> ProbeResult:
        """探测模型多模态能力。

        - ``force=False``(默认):元数据优先,其次 provider 实例,名称启发式兜底
          (兼容既有消费方)。
        - ``force=True``:跳过元数据直发真实探测(QwenPaw 语义),结果写回
          model_metadata(capabilities 合并 vision + probe_source)。
        """
        provider = self._resolve_provider(model_id, provider_id)
        if provider is None:
            return ProbeResult(
                model_id=model_id,
                supported=False,
                capabilities=[],
                metadata={"detection_method": "none"},
            )

        meta = (provider.model_metadata or {}).get(model_id, {}) or {}
        metadata_caps = meta.get("capabilities") or []
        if metadata_caps and not force:
            return ProbeResult(
                model_id=model_id,
                supported=bool(metadata_caps),
                capabilities=list(metadata_caps),
                metadata={
                    "detection_method": "metadata",
                    "provider_id": provider.id,
                },
            )

        if force:
            result = await self._probe_model_multimodal_real(provider.id, model_id)
            probe_source = result.metadata.get("probe_source") if isinstance(result.metadata, dict) else None
            if probe_source == "probed":
                self._persist_probe_result(provider, model_id, result)
            return result

        instance = self._get_provider_instance(provider.id)
        if instance is not None:
            try:
                return await instance.probe_model_multimodal(model_id)
            except Exception as e:
                logger.warning(
                    "Probe failed for %s/%s: %s", provider.id, model_id, e,
                )
        return ProbeResult(
            model_id=model_id,
            supported=False,
            capabilities=[],
            metadata={
                "detection_method": "name_heuristic",
                "provider_id": provider.id,
            },
        )

    async def _probe_model_multimodal_real(
        self, provider_id: str, model_id: str,
    ) -> ProbeResult:
        """真实多模态探测:委托 provider 实例(OpenAI 兼容路径发图像请求)。"""
        instance = self._get_provider_instance(provider_id)
        if instance is None:
            return ProbeResult(
                model_id=model_id,
                supported=False,
                capabilities=[],
                metadata={"probe_source": "inconclusive"},
            )
        try:
            return await instance.probe_model_multimodal(model_id)
        except Exception as e:
            logger.warning("Real probe failed for %s/%s: %s", provider_id, model_id, e)
            return ProbeResult(
                model_id=model_id,
                supported=False,
                capabilities=[],
                metadata={"probe_source": "inconclusive", "probe_detail": str(e)[:300]},
            )

    def _persist_probe_result(
        self,
        provider: ProviderConfig,
        model_id: str,
        result: ProbeResult,
    ) -> None:
        """把真实探测结果写回 model_metadata(幂等,探测失败不覆盖既有标记)。"""
        try:
            from datetime import datetime as _dt

            with self._config_lock:
                metadata = dict(provider.model_metadata or {})
                entry = dict(metadata.get(model_id, {}) or {})
                caps = [str(c) for c in (entry.get("capabilities") or [])]
                result_caps = [str(c) for c in (result.capabilities or [])]
                vision = "vision" in result_caps
                if vision and "vision" not in caps:
                    caps = [*caps, "vision"]
                elif not vision and "vision" in caps and result.metadata.get("probe_detail") == "media_rejected":
                    caps = [c for c in caps if c != "vision"]
                entry["capabilities"] = caps
                entry["probe_source"] = "probed"
                entry["probed_at"] = _dt.now().isoformat()
                metadata[model_id] = entry
                provider.model_metadata = metadata
                self._save_config()
        except Exception as e:  # noqa: BLE001 — 持久化失败不影响探测结果返回
            logger.warning("Persist probe result failed for %s: %s", model_id, e)

    def maybe_probe_multimodal(self, provider_id: str, model_id: str) -> None:
        """激活模型时的自动后台探测(QwenPaw maybe_probe_multimodal 对齐)。

        仅对该模型无任何能力标记时调度 fire-and-forget 线程,
        不阻塞激活流程;探测结果经 _persist_probe_result 写回。
        """
        try:
            provider = self.get_provider(provider_id)
            if provider is None:
                return
            meta = (provider.model_metadata or {}).get(model_id, {}) or {}
            if meta.get("capabilities"):
                return  # 已有标记(含探针/文档来源),不重复探测
            if meta.get("probe_source") == "probed":
                return

            def _run() -> None:
                try:
                    import asyncio as _asyncio

                    result = _asyncio.run(
                        self._probe_model_multimodal_real(provider_id, model_id),
                    )
                    if isinstance(result.metadata, dict) and result.metadata.get("probe_source") == "probed":
                        self._persist_probe_result(provider, model_id, result)
                except Exception as e:  # noqa: BLE001 — 后台任务失败仅记录
                    logger.warning("Auto probe failed for %s/%s: %s", provider_id, model_id, e)

            import threading

            threading.Thread(target=_run, name=f"probe-{model_id}", daemon=True).start()
        except Exception as e:  # noqa: BLE001 — 调度失败不影响激活
            logger.warning("maybe_probe_multimodal failed: %s", e)

    async def check_model_connection(
        self,
        model_id: str,
        provider_id: Optional[str] = None,
    ) -> ConnectionResult:
        """检查模型连接:按 model_id 定位服务商并调用实例检查。

        QwenPaw 对齐:管理器层统一填 checked_at 并派生可用性七态,
        检查结果持久化进 model_metadata[model_id]["availability"]。
        """
        from datetime import timezone

        provider = self._resolve_provider(model_id, provider_id)
        if provider is None:
            return ConnectionResult(success=False, error="Model not found")

        instance = self._get_provider_instance(provider.id)
        if instance is None:
            return ConnectionResult(success=False, error="Provider instance unavailable")
        try:
            result = await instance.check_model_connection(model_id)
        except Exception as e:
            return ConnectionResult(success=False, error=str(e))

        result.checked_at = datetime.now(timezone.utc).isoformat()
        if result.retryable is None:
            category = result.error_category
            result.retryable = (
                False
                if result.success
                else category in ("connection_failed", "service_unavailable", "rate_limited")
            )
        if result.verification == "unverified" and result.success:
            result.verification = "live"

        try:
            from neurova.llm.providers.error_mapping import availability_status_of

            status = availability_status_of(
                success=result.success,
                error_category=result.error_category,
                message=result.error,
                http_status=result.http_status,
            )
            with self._config_lock:
                metadata = dict(provider.model_metadata or {})
                entry = dict(metadata.get(model_id, {}) or {})
                entry["availability"] = {
                    "status": status,
                    "checked_at": result.checked_at,
                    "http_status": result.http_status,
                    "verification": result.verification,
                    "message": (result.error or "")[:300],
                }
                metadata[model_id] = entry
                provider.model_metadata = metadata
                self._save_config()
        except Exception as e:  # noqa: BLE001 — 持久化失败不影响检查结果返回
            logger.warning("Persist model availability failed for %s: %s", model_id, e)

        return result

    async def check_provider_connection(self, provider_id: str) -> ConnectionResult:
        """真实现:调用 provider 实例的 check_connection,并如实更新健康状态。"""
        provider = self.get_provider(provider_id)
        if not provider:
            logger.error("Provider %s not found", provider_id)
            return ConnectionResult(success=False, error="Provider not found")

        instance = self._get_provider_instance(provider_id)
        if instance is None:
            provider.health_status = "unhealthy"
            return ConnectionResult(success=False, error="Provider instance unavailable")
        try:
            result = await instance.check_connection()
            provider.health_status = "healthy" if result.success else "unhealthy"
            provider.last_health_check = datetime.now().isoformat()
            return result
        except Exception as e:
            provider.health_status = "unhealthy"
            provider.last_health_check = datetime.now().isoformat()
            logger.error("Connection check failed for %s: %s", provider.name, e)
            return ConnectionResult(success=False, error=str(e))

    async def health_check_provider(self, provider_id: str) -> bool:
        """健康检查:委托给真连接检查,失败置 unhealthy(不再恒 healthy)。"""
        result = await self.check_provider_connection(provider_id)
        return result.success

    def detect_model_capabilities(self, provider_id: str, model: str, use_cache: bool = True) -> Dict[str, Any]:
        """检测模型能力:元数据优先,缺失时使用名称启发式兜底。"""
        provider = self.get_provider(provider_id)
        if not provider:
            logger.warning("Provider %s not found", provider_id)
            return {}

        meta = (provider.model_metadata or {}).get(model, {}) or {}
        caps = [str(c) for c in meta.get("capabilities", [])]
        if caps:
            return {
                "vision": "vision" in caps,
                "audio": "audio" in caps,
                "video": "video" in caps,
                "tool_use": "tool_use" in caps,
            }

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

    def _get_provider_instance(self, provider_id: str):
        """获取服务商实例(用于实际 API 调用),按 provider_id 缓存。

        注意:ProviderConfig 需拆解为实例构造参数 — 早期实现把配置对象
        直接作为位置参数传入,导致实例拿不到 api_key/base_url。
        """
        provider = self.get_provider(provider_id)
        if not provider:
            return None

        cache = getattr(self, "_provider_instances", None)
        if cache is None:
            cache = self._provider_instances = {}
        if provider_id in cache:
            return cache[provider_id]

        def _build(cls):
            try:
                provider_type = ProviderType(provider.provider)
            except ValueError:
                provider_type = ProviderType.OPENAI
            # 各具体 Provider 的 __init__ 签名为硬编码 provider_type
            # (OpenAI/OpenRouter 等不接收该 kwarg,传入会落入 **kwargs 与
            # super() 调用重复,抛 "multiple values for provider_type")。
            # 因此按类签名决定是否传,不靠异常吞掉(防掩盖真实参数错误)。
            if "provider_type" in inspect.signature(cls).parameters:
                return cls(
                    provider_id=provider.id,
                    provider_type=provider_type,
                    api_key=provider.api_key or "",
                    base_url=provider.base_url or "",
                )
            return cls(
                provider_id=provider.id,
                api_key=provider.api_key or "",
                base_url=provider.base_url or "",
            )

        try:
            from neurova.llm.providers import (
                AnthropicProvider,
                GeminiProvider,
                OllamaProvider,
                OpenAIProvider,
                OpenCodeProvider,
                OpenRouterProvider,
            )

            type_map = {
                "openai": OpenAIProvider,
                "anthropic": AnthropicProvider,
                "gemini": GeminiProvider,
                "ollama": OllamaProvider,
                "openrouter": OpenRouterProvider,
                "opencode": OpenCodeProvider,
            }
            cls = type_map.get(provider.provider, OpenAIProvider)
            instance = _build(cls)
        except ImportError as e:
            logger.warning("Could not import provider %s: %s", provider.provider, e)
            return None

        cache[provider_id] = instance
        return instance


_provider_manager: Optional[LLMProviderManager] = None
# scope → 实例 的隔离注册表(admin 走 _provider_manager,保持存量引用兼容)
_provider_managers: Dict[str, LLMProviderManager] = {}
_provider_manager_lock = threading.Lock()

_SCOPE_PART_RE = re.compile(r"[^A-Za-z0-9_-]")


def _sanitize_scope_part(value: str) -> str:
    """把 user_id 净化成安全的文件名片段(防路径穿越/特殊字符)。"""
    return _SCOPE_PART_RE.sub("-", value)


def _default_config_dir() -> Path:
    home = Path.home()
    config_dir = home / ".neurova" / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def _config_path_for_scope(scope: str) -> Path:
    """scope → 配置文件路径。

    - scope=="admin":沿用存量全局 providers.json(升级不丢配置)
    - 其它 scope(如 "user:alice"):providers.user-alice.json
      (整个 scope 净化后作文件名,保留前缀信息,防不同 scope 撞出同路径)
    """
    if scope == "admin":
        return _default_config_dir() / "providers.json"
    scope_part = scope.split(":", 1)[-1] if ":" in scope else scope
    prefix = scope.split(":", 1)[0] if ":" in scope else "scope"
    return _default_config_dir() / f"providers.{prefix}-{_sanitize_scope_part(scope_part)}.json"


def list_available_scopes(config_dir: Optional[Path] = None) -> List[str]:
    """列出所有非 admin 的已配置 scope(用于 admin 查看用户配置入口)。

    通过扫描 providers.<prefix>-<part>.json 反解 scope 字符串。
    全局 providers.json、临时文件(.bak/.tmp 等)一律排除。
    """
    directory = Path(config_dir) if config_dir is not None else _default_config_dir()
    if not directory.is_dir():
        return []
    scopes: List[str] = []
    for path in sorted(directory.glob("providers.*.json")):
        name = path.name[len("providers."):-len(".json")]
        if not name or name == "json":
            continue
        if "-" in name:
            prefix, part = name.split("-", 1)
            if prefix and part:
                scopes.append(f"{prefix}:{part}")
    return scopes


def get_provider_manager_for_user(current_user: Dict[str, Any]) -> LLMProviderManager:
    """按用户身份选择 scope 的 provider manager(端点统一入口)。

    - admin 角色 → 全局 admin scope(最高权限)
    - 普通用户 → user:<user_id> scope(仅自己的配置)
    - 无 user_id(异常状态)→ 全局(不会把配置误挂到空用户)
    """
    role = (current_user.get("role") or "user").lower()
    user_id = (current_user.get("user_id") or "").strip()
    if role == "admin" or not user_id:
        return get_provider_manager(scope="admin")
    return get_provider_manager(scope=f"user:{user_id}")


def get_provider_manager(config_path: Optional[str] = None, scope: Optional[str] = None) -> LLMProviderManager:
    """获取 LLMProviderManager 单例(线程安全,双重检查锁定)

    隔离模型:
    - 无参调用(或 scope=="admin"):返回全局 admin 单例(存量行为,向后兼容)
    - scope=="user:<user_id>":返回该用户独立单例(独立配置文件、独立内存状态)

    参数:
        config_path: 可选的配置文件路径(显式给定时优先于 scope 派发)
        scope: 可选作用域("admin" 或 "user:<user_id>")

    返回:
        LLMProviderManager 单例(按 scope 隔离)
    """
    # 默认作用域 = admin(向后兼容无参调用)
    if scope is None and config_path is None:
        scope = "admin"
    if config_path is None:
        config_path = str(_config_path_for_scope(scope or "admin"))

    global _provider_manager
    # 第一次检查(无锁,快速路径)
    if scope == "admin":
        if _provider_manager is None:
            with _provider_manager_lock:
                if _provider_manager is None:
                    _provider_manager = LLMProviderManager(
                        config={"config_path": config_path},
                    )
        return _provider_manager

    key = f"scope:{scope}"
    cached = _provider_managers.get(key)
    if cached is None:
        with _provider_manager_lock:
            cached = _provider_managers.get(key)
            if cached is None:
                cached = LLMProviderManager(config={"config_path": config_path})
                _provider_managers[key] = cached
    return cached


def reset_provider_manager() -> None:
    """重置全部 LLMProviderManager 单例(线程安全)

    清除全局 admin 单例与所有 scope 单例,使下次 get_provider_manager()
    重新加载配置。用于与 MultiModelLLMClient.reset() 协同。

    线程安全:
    - 在 _provider_manager_lock 保护下清除,避免与并发 get_provider_manager() 竞态
    """
    global _provider_manager
    with _provider_manager_lock:
        _provider_manager = None
        _provider_managers.clear()


__all__ = [
    "LoadBalancingStrategy",
    "ProviderConfig",
    "LLMProviderManager",
    "get_provider_manager",
    "reset_provider_manager",
]
