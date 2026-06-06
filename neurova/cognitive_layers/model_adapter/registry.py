"""
ModelAdapterRegistry — 模型适配器注册表

全局单例，根据模型名自动匹配最佳适配器。
所有用户/Agent 共享同一套适配器池（无状态路由）。
"""

import logging
import re
import typing

from pydantic import BaseModel
from typing import Type

# llm_client imports
from neurova.llm_client import LLMClient, LLMConfig, LLMResponse

logger = logging.getLogger(__name__)


class ModelAdapter(BaseModel):
    """模型适配器基类"""
    name: str
    model_pattern: str  # 正则表达式模式
    priority: int = 0  # 优先级，越高越优先
    description: str = ""
    
    class Config:
        arbitrary_types_allowed = True
    
    def match_model(self, model_name: str) -> bool:
        """检查模型名是否匹配"""
        try:
            return bool(re.search(self.model_pattern, model_name, re.IGNORECASE))
        except re.error:
            return False
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成回复（子类实现）"""
        raise NotImplementedError
    
    async def stream_generate(self, prompt: str, **kwargs) -> typing.AsyncIterator[str]:
        """流式生成（子类实现）"""
        raise NotImplementedError
        yield  # 使函数成为生成器


class GenericAdapter(ModelAdapter):
    """通用适配器 - 使用 LLMClient"""
    name: str = "generic"
    model_pattern: str = ".*"  # 匹配所有模型
    priority: int = -100  # 最低优先级
    description: str = "通用 LLM 适配器"
    
    def __init__(self, **data):
        super().__init__(**data)
        self._clients: typing.Dict[str, LLMClient] = {}
    
    def _get_client(self, model_name: str) -> LLMClient:
        """获取或创建 LLM 客户端"""
        if model_name not in self._clients:
            config = LLMConfig(model=model_name)
            self._clients[model_name] = LLMClient(config)
        return self._clients[model_name]
    
    async def generate(self, prompt: str, **kwargs) -> str:
        """生成回复"""
        model_name = kwargs.get("model", "gpt-4")
        client = self._get_client(model_name)
        
        try:
            response = await client.generate(prompt, **kwargs)
            return response.content
        except Exception as e:
            logger.error(f"GenericAdapter 生成失败: {e}")
            raise
    
    async def stream_generate(self, prompt: str, **kwargs) -> typing.AsyncIterator[str]:
        """流式生成"""
        model_name = kwargs.get("model", "gpt-4")
        client = self._get_client(model_name)
        
        try:
            async for chunk in client.stream_generate(prompt, **kwargs):
                yield chunk
        except Exception as e:
            logger.error(f"GenericAdapter 流式生成失败: {e}")
            raise


class ModelAdapterRegistry:
    """
    模型适配器注册表
    
    单例模式，管理所有模型适配器。
    """
    _instance: typing.Optional['ModelAdapterRegistry'] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._adapters: typing.List[ModelAdapter] = []
        self._generic_adapter = GenericAdapter()
        
        # 注册通用适配器
        self.register_adapter(self._generic_adapter)
        
        self._initialized = True
        logger.info("ModelAdapterRegistry 初始化完成")
    
    def register_adapter(self, adapter: ModelAdapter) -> None:
        """注册适配器"""
        self._adapters.append(adapter)
        # 按优先级排序（降序）
        self._adapters.sort(key=lambda x: x.priority, reverse=True)
        logger.debug(f"适配器已注册: {adapter.name}, 优先级: {adapter.priority}")
    
    def unregister_adapter(self, adapter_name: str) -> bool:
        """取消注册适配器"""
        for i, adapter in enumerate(self._adapters):
            if adapter.name == adapter_name:
                self._adapters.pop(i)
                logger.debug(f"适配器已取消注册: {adapter_name}")
                return True
        return False
    
    def find_adapter(self, model_name: str) -> ModelAdapter:
        """查找匹配的适配器"""
        for adapter in self._adapters:
            if adapter.match_model(model_name):
                logger.debug(f"找到适配器: {adapter.name} 用于模型: {model_name}")
                return adapter
        
        # 如果没有匹配的适配器，返回通用适配器
        logger.debug(f"使用通用适配器用于模型: {model_name}")
        return self._generic_adapter
    
    def list_adapters(self) -> typing.List[typing.Dict[str, typing.Any]]:
        """列出所有适配器"""
        return [
            {
                "name": adapter.name,
                "model_pattern": adapter.model_pattern,
                "priority": adapter.priority,
                "description": adapter.description
            }
            for adapter in self._adapters
        ]
    
    async def generate(self, model_name: str, prompt: str, **kwargs) -> str:
        """使用匹配的适配器生成回复"""
        adapter = self.find_adapter(model_name)
        return await adapter.generate(prompt, model=model_name, **kwargs)
    
    async def stream_generate(self, model_name: str, prompt: str, **kwargs) -> typing.AsyncIterator[str]:
        """使用匹配的适配器流式生成"""
        adapter = self.find_adapter(model_name)
        async for chunk in adapter.stream_generate(prompt, model=model_name, **kwargs):
            yield chunk


# 工厂函数
_registry: typing.Optional[ModelAdapterRegistry] = None


def get_model_adapter_registry() -> ModelAdapterRegistry:
    """获取模型适配器注册表单例"""
    global _registry
    if _registry is None:
        _registry = ModelAdapterRegistry()
    return _registry


def reset_model_adapter_registry() -> None:
    """重置模型适配器注册表（用于测试）"""
    global _registry
    _registry = None


# 便捷函数
async def _generate_with_litellm(model_name: str, prompt: str, **kwargs) -> str:
    """通过 LLMClient 生成回复"""
    registry = get_model_adapter_registry()
    return await registry.generate(model_name, prompt, **kwargs)


async def _stream_with_litellm(model_name: str, prompt: str, **kwargs) -> typing.AsyncIterator[str]:
    """通过 LLMClient 流式生成"""
    registry = get_model_adapter_registry()
    async for chunk in registry.stream_generate(model_name, prompt, **kwargs):
        yield chunk