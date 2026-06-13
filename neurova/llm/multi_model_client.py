"""
多模型 LLM 客户端管理器

职责:
1. 管理多个 LLM 客户端实例（按服务商和模型组织）
2. 支持运行时切换当前活跃模型
3. 支持按模型名称自动路由请求
4. 支持负载均衡策略
"""

import asyncio
import logging
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

logger = logging.getLogger(__name__)


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
    _lock = threading.Lock()

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
        if hasattr(self, "_initialized") and self._initialized:
            return
        self._initialized = True

        self._provider_manager = provider_manager or get_provider_manager()
        self._clients: Dict[str, ModelClient] = {}  # key: provider_id/model
        self._current_provider_id: Optional[str] = None
        self._current_model: Optional[str] = None
        self._round_robin_index = 0
        self._init_lock = threading.Lock()

        # 初始化默认客户端
        self._initialize_default_clients()

    def _initialize_default_clients(self) -> None:
        """初始化默认客户端"""
        default_provider = self._provider_manager.get_default_provider()
        if default_provider and default_provider.enabled and default_provider.api_key:
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

            config = LLMConfig(
                api_key=provider.api_key,
                base_url=provider.base_url,
                model=model,
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
    ) -> Dict[str, Any]:
        """发送聊天请求"""
        client = self._get_client_for_request(model, provider_id)
        if not client:
            logger.warning("No client available for chat")
            return {
                "success": False,
                "error": "No client available",
            }

        try:
            start_time = time.time()
            result = await asyncio.to_thread(client.client.chat, messages)
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
    ):
        """发送流式聊天请求"""
        client = self._get_client_for_request(model, provider_id)
        if not client:
            logger.warning("No client available for stream chat")
            yield {"error": "No client available"}
            return

        try:
            start_time = time.time()
            async for chunk in client.client.chat_stream(messages):
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
        """为请求获取客户端"""
        if provider_id and model:
            return self.get_client(provider_id, model)
        elif model:
            return self.get_client(model=model)
        else:
            return self.get_current_client()

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
