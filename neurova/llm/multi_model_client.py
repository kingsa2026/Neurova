"""
多模型 LLM 客户端管理器

文件路径: neurova/llm/multi_model_client.py

职责:
1. 管理多个 LLM 客户端实例（按服务商和模型组织）
2. 支持运行时切换当前活跃模型
3. 支持按模型名称自动路由请求
4. 支持负载均衡策略

单例初始化契约 (LLM-2 修复):
- `_initialized` 标志仅在 `_initialize_default_clients()` 成功后置位
- 首次初始化失败时（如 api_key 解密失败、provider 未就绪）:
  * `_initialized` 不被置位 → 下次 `__init__` 会重试
  * 异常被记录到日志后重新抛出（不吞掉错误）
- 正常路径（无异常）时 `_initialized = True`，防止重复初始化
- `reset()` 可手动清除单例和 `_initialized`，强制下次重新初始化
- `chat()` 检测 `_clients` 为空时会自动 `refresh_all_providers()` 自愈

历史修复:
- P0-3 (C6): `__init__` 的 `_initialized` 检查移入 `cls._lock` (RLock) 内，修复 TOCTOU
- LLM-2: `_initialized = True` 从 `_initialize_default_clients()` 之前移到之后，
         修复首次初始化失败后永久跳过重试的 bug
"""

import asyncio
from neurova.core.logger import get_logger
import threading
import time
from typing import Any, Dict, List, Optional

from neurova.llm.provider_manager import (
    LLMProviderManager,
    LoadBalancingStrategy,
    ProviderConfig,
    get_provider_manager,
)
from neurova.llm_client import LLMClient, LLMConfig

logger = get_logger(__name__)


class ModelClient:
    """单个模型的客户端封装"""

    def __init__(self, client: LLMClient, provider: ProviderConfig, model: str):
        self.client = client
        self.provider = provider
        self.model = model
        self.request_count = 0
        self.error_count = 0
        self.last_used = 0.0

    @property
    def success_rate(self) -> float:
        """成功率"""
        if self.request_count == 0:
            return 1.0
        return (self.request_count - self.error_count) / self.request_count

    def increment_request(self, success: bool) -> None:
        """增加请求计数"""
        self.request_count += 1
        self.last_used = time.time()
        if not success:
            self.error_count += 1


class MultiModelLLMClient:
    """
    多模型 LLM 客户端管理器

    职责:
    1. 管理多个 LLM 客户端实例（按服务商和模型组织）
    2. 支持运行时切换当前活跃模型
    3. 支持按模型名称自动路由请求
    4. 支持负载均衡策略
    """

    _instance = None
    # 使用 RLock（可重入锁）：__new__ 持锁后 __init__ 重入调用，Lock 会永久阻塞
    # 修复 P0-3 (C6): 原 threading.Lock() 不可重入，__init__ 内重入会死锁
    _lock = threading.RLock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    def __init__(
        self,
        provider_manager: Optional[LLMProviderManager] = None,
        strategy: LoadBalancingStrategy = LoadBalancingStrategy.PRIORITY_FIRST,
    ):
        # 修复 P0-3 (C6): __init__ 的 _initialized 检查必须在锁内，
        # 否则两线程可同时通过 hasattr 检查（TOCTOU）
        # 注：__init__ 是实例方法，无 cls 参数，用 type(self) 获取类引用
        with type(self)._lock:
            if hasattr(self, "_initialized") and self._initialized:
                return

            self._provider_manager = provider_manager or get_provider_manager()
            self._clients: Dict[str, ModelClient] = {}  # key: provider_id/model
            self._current_provider_id: Optional[str] = None
            self._current_model: Optional[str] = None
            self._round_robin_index = 0
            # 使用 RLock：refresh_provider() 持锁后调用 _initialize_provider_clients()
            # 后者也获取 _init_lock，Lock 会死锁；RLock 可重入避免死锁
            self._init_lock = threading.RLock()

            # 初始化默认客户端
            # 修复 LLM-2: _initialized = True 原位于 _initialize_default_clients() 之前 (line 87),
            # 导致首次初始化失败后 _initialized 已为 True，下次 __init__ 直接 return 永久跳过重试。
            # 现仅在 _initialize_default_clients() 成功后置位，失败时不置位以允许下次 __init__ 重试。
            # 不吞掉异常：记录日志后重新抛出（遵循"不抹除报错信息"原则）。
            try:
                self._initialize_default_clients()
                self._initialized = True
            except Exception as e:
                logger.error("Failed to initialize default clients: %s", e)
                raise

    @classmethod
    def reset(cls) -> None:
        """重置单例，允许重新初始化。

        用途：当首次初始化因配置缺失（如 api_key 解密失败、provider 未就绪）
        导致 _clients 为空时，配置修复后调用 reset() 可让下次 get_multi_model_client()
        重新初始化。

        线程安全：在 cls._lock（RLock）保护下清除 _instance 和模块级单例。

        reset 链路穿透：同时调用 reset_provider_manager()，清除 provider_manager 单例。
        否则下次 __init__ → get_provider_manager() 仍返回旧的 _provider_manager
        （已缓存了空 api_key 的 providers），reset 链路在 provider_manager 处断裂。
        """
        with cls._lock:
            # 清除实例级 _initialized 标志（防止已存在的实例阻止重新初始化）
            instance = cls._instance
            if instance is not None and hasattr(instance, "_initialized"):
                instance._initialized = False
            # 清除类级单例
            cls._instance = None
        # 清除模块级单例（在锁外，因为 get_multi_model_client 自己会加锁）
        global _multi_model_client
        _multi_model_client = None

        # 清除 provider_manager 单例，确保 reset 链路穿透到 provider_manager 层
        # 延迟导入避免循环依赖（multi_model_client 顶部已 import provider_manager，
        # 但为保持 reset() 自包含与可测试性，这里显式延迟导入）
        try:
            from neurova.llm.provider_manager import reset_provider_manager
            reset_provider_manager()
        except ImportError as e:
            logger.warning("Could not reset provider_manager: %s", e)

    def _initialize_default_clients(self) -> None:
        """初始化默认客户端

        三重门控诊断日志 (修复 antipattern: 原 `if A and B and C:` 失败时无任何分支日志):
        - 三条件各自独立 return, 每个分支打 WARNING 指明具体失败原因
        - 三条件都满足时, 保持原逻辑 (调 _initialize_provider_clients + 设当前模型)
        - 关键诊断点: api_key 为空通常是 pycryptodome 缺失导致解密失败, 必须显式日志
        """
        default_provider = self._provider_manager.get_default_provider()
        if not default_provider:
            logger.warning("Skip init default clients: no default provider configured")
            return
        if not default_provider.enabled:
            logger.warning("Skip init default clients: default provider %s is disabled", default_provider.id)
            return
        if not default_provider.api_key:
            logger.warning("Skip init default clients: default provider %s has empty api_key (decrypt failed?)", default_provider.id)
            return
        self._initialize_provider_clients(default_provider)
        if default_provider.default_model:
            self._current_provider_id = default_provider.id
            self._current_model = default_provider.default_model
            logger.info("Initialized default client: %s/%s", default_provider.id, default_provider.default_model)

    def _initialize_provider_clients(self, provider: ProviderConfig) -> None:
        """为服务商初始化客户端"""
        with self._init_lock:
            for model in provider.models:
                self._create_model_client(provider, model)
            if provider.default_model and provider.default_model not in provider.models:
                self._create_model_client(provider, provider.default_model)

    def _create_model_client(self, provider: ProviderConfig, model: str) -> Optional[ModelClient]:
        """创建模型客户端"""
        client_key = f"{provider.id}/{model}"
        if client_key in self._clients:
            return self._clients[client_key]

        try:
            if not provider.api_key:
                logger.warning("No API key for provider %s", provider.id)
                return None

            from neurova.llm.model_limits import get_model_max_tokens

            config = LLMConfig(
                api_key=provider.api_key,
                base_url=provider.base_url,
                model=model,
                max_tokens=get_model_max_tokens(model),
            )
            client = LLMClient(config)
            model_client = ModelClient(client=client, provider=provider, model=model)
            self._clients[client_key] = model_client
            return model_client
        except Exception as e:
            logger.error("Failed to create client for %s/%s: %s", provider.id, model, e)
            return None

    def get_client(
        self,
        provider_id: Optional[str] = None,
        model: Optional[str] = None,
    ) -> Optional[ModelClient]:
        """获取客户端"""
        if provider_id and model:
            client_key = f"{provider_id}/{model}"
            return self._clients.get(client_key)

        # 按模型名称查找
        if model:
            for client in self._clients.values():
                if client.model == model or client.model.endswith(model):
                    return client

        # 返回当前客户端
        return self.get_current_client()

    def get_current_client(self) -> Optional[ModelClient]:
        """获取当前活跃客户端"""
        if self._current_provider_id and self._current_model:
            client_key = f"{self._current_provider_id}/{self._current_model}"
            client = self._clients.get(client_key)
            if client:
                return client

        # 如果没有当前客户端，返回第一个可用的
        if self._clients:
            return next(iter(self._clients.values()))

        logger.warning("No clients available")
        return None

    def set_active_model(self, provider_id: str, model: str) -> bool:
        """设置活跃模型"""
        client = self.get_client(provider_id, model)
        if not client:
            # 尝试创建客户端
            provider = self._provider_manager.get_provider(provider_id)
            if not provider:
                logger.warning("Provider %s not found", provider_id)
                return False
            client = self._create_model_client(provider, model)
            if not client:
                return False

        self._current_provider_id = provider_id
        self._current_model = model
        logger.info("Active model set to %s/%s", provider_id, model)
        return True

    def switch_to_next_model(self) -> bool:
        """切换到下一个模型"""
        if not self._clients:
            return False

        # 获取所有可用模型
        models = list(self._clients.values())
        if len(models) <= 1:
            return False

        # 查找当前模型的索引
        current_index = -1
        for i, client in enumerate(models):
            if client.provider.id == self._current_provider_id and client.model == self._current_model:
                current_index = i
                break

        # 切换到下一个
        next_index = (current_index + 1) % len(models)
        next_client = models[next_index]

        self._current_provider_id = next_client.provider.id
        self._current_model = next_client.model
        logger.info("Switched to model %s/%s", self._current_provider_id, self._current_model)
        return True

    def list_available_models(self) -> List[Dict[str, Any]]:
        """列出所有可用模型"""
        models = []
        for client in self._clients.values():
            models.append(
                {
                    "provider_id": client.provider.id,
                    "provider_name": client.provider.name,
                    "model": client.model,
                    "is_current": (
                        client.provider.id == self._current_provider_id and client.model == self._current_model
                    ),
                    "request_count": client.request_count,
                    "success_rate": client.success_rate,
                }
            )
        return models

    def refresh_provider(self, provider_id: str) -> bool:
        """刷新服务商客户端"""
        provider = self._provider_manager.get_provider(provider_id)
        if not provider:
            logger.warning("Provider %s not found", provider_id)
            return False

        # 移除旧客户端
        with self._init_lock:
            keys_to_remove = [k for k in self._clients.keys() if k.startswith(f"{provider_id}/")]
            for key in keys_to_remove:
                del self._clients[key]

            # 重新初始化
            if provider.enabled and provider.api_key:
                self._initialize_provider_clients(provider)
                logger.info("Refreshed provider %s", provider_id)
                return True

        return False

    def refresh_all_providers(self) -> None:
        """刷新所有服务商"""
        providers = self._provider_manager.list_providers()
        for provider in providers:
            self.refresh_provider(provider.id)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """发送聊天请求"""
        # [METRICS] 结构化日志：记录 LLM 调用的消息结构和模型信息
        client = self._get_client_for_request(model, provider_id)

        # 自愈：_clients 为空时尝试 refresh_all_providers()
        # 场景：首次初始化时 api_key 解密失败/pycryptodome 缺失 → _clients 空
        # 后续配置修复后（如 pycryptodome 安装），refresh 可恢复 clients
        if not client and not self._clients:
            logger.info("Auto-refreshing providers due to empty _clients")
            try:
                self.refresh_all_providers()
                client = self._get_client_for_request(model, provider_id)
            except Exception as e:
                logger.warning("Auto-refresh failed: %s", e, exc_info=True)

        _role_counts: Dict[str, int] = {}
        for m in messages:
            _r = m.get("role", "unknown")
            _role_counts[_r] = _role_counts.get(_r, 0) + 1
        _sys_count = _role_counts.get("system", 0)
        _total_msgs = len(messages)
        _model_name = model or (client.model if client else "unknown")
        logger.info(
            "[LLM-REQ] model=%s, messages=%s, system=%s, roles=%s",
            _model_name, _total_msgs, _sys_count, _role_counts,
        )
        if not client:
            logger.warning("No client available for chat")
            return {
                "success": False,
                "error": "No client available",
            }

        try:
            start_time = time.time()
            result = await asyncio.to_thread(client.client.chat, messages, **kwargs)
            duration = time.time() - start_time

            client.increment_request(success=True)
            return {
                "success": True,
                "response": result,
                "duration": duration,
                "model": client.model,
                "provider": client.provider.id,
            }
        except Exception as e:
            client.increment_request(success=False)
            return {
                "success": False,
                "error": str(e),
                "model": client.model,
                "provider": client.provider.id,
            }

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
        **kwargs,
    ):
        """发送流式聊天请求"""
        client = self._get_client_for_request(model, provider_id)
        if not client:
            logger.warning("No client available for stream chat")
            yield {"error": "No client available"}
            return

        try:
            start_time = time.time()
            async for chunk in client.client.chat_stream(messages, **kwargs):
                yield chunk
            time.time() - start_time
            client.increment_request(success=True)
        except Exception as e:
            client.increment_request(success=False)
            yield {"error": str(e)}

    def _get_client_for_request(
        self,
        model: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> Optional[ModelClient]:
        """为请求获取客户端（支持懒加载非默认服务商）"""
        if provider_id and model:
            client = self.get_client(provider_id, model)
            if client:
                return client
            # 懒加载：尝试为指定的 provider/model 创建客户端
            return self._try_lazy_init(provider_id, model)
        elif model:
            client = self.get_client(model=model)
            if client:
                return client
            # 按模型名查找所有服务商
            for provider in self._provider_manager.list_providers():
                if model in provider.models:
                    return self._try_lazy_init(provider.id, model)
            return None
        else:
            return self.get_current_client()

    def _try_lazy_init(self, provider_id: str, model: str) -> Optional[ModelClient]:
        """尝试懒加载客户端 — 为非默认服务商动态创建"""
        provider = self._provider_manager.get_provider(provider_id)
        if not provider:
            logger.warning("Provider %s not found for lazy init", provider_id)
            return None
        if not provider.enabled:
            logger.warning("Provider %s is disabled", provider_id)
            return None
        if not provider.api_key:
            logger.warning("Provider %s has no API key, cannot create client", provider_id)
            return None
        client = self._create_model_client(provider, model)
        if client:
            logger.info("Lazily initialized client for %s/%s", provider_id, model)
        return client

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        total_requests = sum(c.request_count for c in self._clients.values())
        total_errors = sum(c.error_count for c in self._clients.values())

        return {
            "total_clients": len(self._clients),
            "current_provider": self._current_provider_id,
            "current_model": self._current_model,
            "total_requests": total_requests,
            "total_errors": total_errors,
            "models": self.list_available_models(),
        }


_multi_model_client: Optional[MultiModelLLMClient] = None


def get_multi_model_client() -> MultiModelLLMClient:
    """获取 MultiModelLLMClient 单例"""
    global _multi_model_client
    if _multi_model_client is None:
        _multi_model_client = MultiModelLLMClient()
    return _multi_model_client


__all__ = [
    "MultiModelLLMClient",
    "get_multi_model_client",
]
