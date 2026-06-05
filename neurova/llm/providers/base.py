from __future__ import annotations

"""
LLM Provider 基类

定义统一的 Provider 接口，用于与不同的 LLM 服务进行交互。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
import datetime
import enum
import logging
import time
import typing

from neurova.llm.providers.types import (
    ConnectionResult, ModelInfo, ProbeResult, ProviderCapability, ProviderType
)
from enum import Enum
from typing import TYPE_CHECKING
import http
import time

# llm imports
import neurova.llm.providers.types

# llm_client imports
import neurova.llm_client

# Types are imported from neurova.llm.providers.types
# ProviderType, ProviderCapability, ModelInfo are already defined there

class BaseProvider(ABC):
    """
    LLM Provider 抽象基类
    
    定义统一的 Provider 接口，用于与不同的 LLM 服务进行交互。
    所有具体的 Provider 实现都必须继承此类。
    """
    
    def __init__(
        self,
        provider_id: str,
        provider_type: ProviderType,
        api_key: str = "",
        base_url: str = "",
        **kwargs
    ):
        """初始化 Provider
        
        Args:
            provider_id: Provider 唯一标识符
            provider_type: Provider 类型
            api_key: API 密钥
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        self.provider_id = provider_id
        self.provider_type = provider_type
        self.api_key = api_key
        self.base_url = base_url
        self.logger = logging.getLogger(f"{__name__}.{provider_id}")
        self._models_cache: typing.List[ModelInfo] = []
        self._models_cache_time: float = 0
        self._cache_ttl: float = 300  # 5分钟缓存
        self._extra_models: typing.List[ModelInfo] = []
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency_ms": 0.0,
        }
        self._config = kwargs
    
    @abstractmethod
    async def get_available_models(self) -> typing.List[ModelInfo]:
        """获取可用的模型列表
        
        Returns:
            模型信息列表
        """
        pass
    
    @abstractmethod
    async def create_chat_model(
        self,
        model_id: str,
        **kwargs
    ) -> typing.Any:
        """创建聊天模型实例
        
        Args:
            model_id: 模型ID
            **kwargs: 模型配置参数
            
        Returns:
            模型实例
        """
        pass
    
    async def test_connection(self) -> ConnectionResult:
        """测试连接（兼容旧接口）
        
        Returns:
            连接测试结果
        """
        return await self.check_connection()
    
    async def check_connection(self) -> ConnectionResult:
        """检查连接状态
        
        Returns:
            连接测试结果
        """
        start_time = time.time()
        try:
            models = await self.get_available_models()
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=True,
                latency_ms=latency,
                models_available=len(models),
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
            )
    
    async def fetch_models(self) -> typing.List[ModelInfo]:
        """获取模型列表（带缓存）
        
        Returns:
            模型信息列表
        """
        current_time = time.time()
        if (self._models_cache and 
            current_time - self._models_cache_time < self._cache_ttl):
            return self._models_cache + self._extra_models
        
        try:
            models = await self.get_available_models()
            self._models_cache = models
            self._models_cache_time = current_time
            return models + self._extra_models
        except Exception as e:
            self.logger.error(f"获取模型列表失败: {e}")
            return self._extra_models
    
    async def check_model_connection(self, model_id: str) -> ConnectionResult:
        """检查特定模型的连接状态
        
        Args:
            model_id: 模型ID
            
        Returns:
            连接测试结果
        """
        start_time = time.time()
        try:
            model = await self.create_chat_model(model_id)
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=True,
                latency_ms=latency,
                metadata={"model_id": model_id},
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
                metadata={"model_id": model_id},
            )
    
    async def probe_model_multimodal(self, model_id: str) -> ProbeResult:
        """探测模型的多模态能力
        
        Args:
            model_id: 模型ID
            
        Returns:
            探测结果
        """
        # 默认实现，子类可以覆盖
        return ProbeResult(
            model_id=model_id,
            supported=False,
            capabilities=[],
        )
    
    def get_llm_config(self, model_id: str) -> typing.Dict[str, typing.Any]:
        """获取 LLM 配置
        
        Args:
            model_id: 模型ID
            
        Returns:
            配置字典
        """
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type.value,
            "model_id": model_id,
            "api_key": self.api_key,
            "base_url": self.base_url,
        }
    
    async def get_all_models(self) -> typing.List[ModelInfo]:
        """获取所有模型（包括额外模型）
        
        Returns:
            模型信息列表
        """
        models = await self.fetch_models()
        return models + self._extra_models
    
    def add_extra_model(self, model: ModelInfo) -> None:
        """添加额外模型
        
        Args:
            model: 模型信息
        """
        self._extra_models.append(model)
    
    def remove_extra_model(self, model_id: str) -> bool:
        """移除额外模型
        
        Args:
            model_id: 模型ID
            
        Returns:
            是否移除成功
        """
        for i, model in enumerate(self._extra_models):
            if model.id == model_id:
                self._extra_models.pop(i)
                return True
        return False
    
    def get_health_status(self) -> typing.Dict[str, typing.Any]:
        """获取健康状态
        
        Returns:
            健康状态字典
        """
        return {
            "provider_id": self.provider_id,
            "provider_type": self.provider_type.value,
            "status": "healthy",
            "stats": self.get_stats(),
        }
    
    def get_effective_generate_kwargs(self, **kwargs) -> typing.Dict[str, typing.Any]:
        """获取有效的生成参数
        
        Args:
            **kwargs: 原始参数
            
        Returns:
            有效的生成参数
        """
        effective_kwargs = self._config.copy()
        effective_kwargs.update(kwargs)
        return effective_kwargs
    
    def _legacy_to_pydantic_model(self, model_data: typing.Dict[str, typing.Any]) -> ModelInfo:
        """将旧格式模型数据转换为 Pydantic 模型
        
        Args:
            model_data: 旧格式模型数据
            
        Returns:
            ModelInfo 实例
        """
        return ModelInfo.from_dict(model_data)
    
    async def get_models(self) -> typing.List[ModelInfo]:
        """获取模型列表（别名）
        
        Returns:
            模型信息列表
        """
        return await self.fetch_models()
    
    def invalidate_models_cache(self) -> None:
        """清除模型缓存"""
        self._models_cache = []
        self._models_cache_time = 0
    
    def set_cache_ttl(self, ttl: float) -> None:
        """设置缓存TTL
        
        Args:
            ttl: 缓存时间（秒）
        """
        self._cache_ttl = ttl
    
    async def probe_capabilities(self, model_id: str) -> typing.List[ProviderCapability]:
        """探测模型能力
        
        Args:
            model_id: 模型ID
            
        Returns:
            能力列表
        """
        result = await self.probe_model_multimodal(model_id)
        return result.capabilities
    
    def supports_capability(self, capability: ProviderCapability) -> bool:
        """检查是否支持特定能力
        
        Args:
            capability: 能力
            
        Returns:
            是否支持
        """
        # 默认实现，子类可以覆盖
        return False
    
    def update_config(self, **kwargs) -> None:
        """更新配置
        
        Args:
            **kwargs: 配置参数
        """
        self._config.update(kwargs)
    
    def get_config(self) -> typing.Dict[str, typing.Any]:
        """获取配置
        
        Returns:
            配置字典
        """
        return self._config.copy()
    
    def record_request(self, success: bool, latency_ms: float) -> None:
        """记录请求统计
        
        Args:
            success: 是否成功
            latency_ms: 延迟（毫秒）
        """
        self._stats["total_requests"] += 1
        self._stats["total_latency_ms"] += latency_ms
        if success:
            self._stats["successful_requests"] += 1
        else:
            self._stats["failed_requests"] += 1
    
    def get_stats(self) -> typing.Dict[str, typing.Any]:
        """获取统计信息
        
        Returns:
            统计信息字典
        """
        return self._stats.copy()
    
    def reset_stats(self) -> None:
        """重置统计信息"""
        self._stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "total_latency_ms": 0.0,
        }
    
    def _make_headers(self, extra_headers: typing.Optional[typing.Dict[str, str]] = None) -> typing.Dict[str, str]:
        """构建请求头
        
        Args:
            extra_headers: 额外的请求头
            
        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Neurova/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if extra_headers:
            headers.update(extra_headers)
        return headers
    
    def _handle_error(self, error: Exception, context: str = "") -> None:
        """处理错误
        
        Args:
            error: 异常
            context: 错误上下文
        """
        self.logger.error(f"Provider 错误 ({context}): {error}")
    
    def __str__(self) -> str:
        return f"{self.__class__.__name__}(provider_id={self.provider_id})"
    
    def __repr__(self) -> str:
        return self.__str__()
