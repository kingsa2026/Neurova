from __future__ import annotations

"""
Gemini Provider

支持 Google Gemini API
"""

import json
import logging
import sys
import time
import typing

from neurova.llm.providers.base import BaseProvider
from neurova.llm.providers.types import (
    ConnectionResult, ModelInfo, ProbeResult, ProviderCapability, ProviderType
)
from neurova.llm_client import LLMConfig
from typing import TYPE_CHECKING

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
except ImportError:
    ChatGoogleGenerativeAI = None

from neurova.llm.providers.multimodal_prober import _is_media_keyword_error


logger = logging.getLogger(__name__)


class GeminiProvider(BaseProvider):
    """
    Google Gemini API Provider
    
    支持 Gemini 系列模型，包括视觉和多模态能力
    """
    
    # 默认支持的模型列表
    _KNOWN_MODELS = [
        ModelInfo(
            id="gemini-1.5-pro",
            name="Gemini 1.5 Pro",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.AUDIO, ProviderCapability.VIDEO, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=1048576,
            pricing={"input": 3.5, "output": 10.5},
        ),
        ModelInfo(
            id="gemini-1.5-flash",
            name="Gemini 1.5 Flash",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.AUDIO, ProviderCapability.VIDEO, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=1048576,
            pricing={"input": 0.075, "output": 0.3},
        ),
        ModelInfo(
            id="gemini-1.5-pro-exp-0827",
            name="Gemini 1.5 Pro Exp",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.AUDIO, ProviderCapability.VIDEO, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=1048576,
            pricing={"input": 3.5, "output": 10.5},
        ),
        ModelInfo(
            id="gemini-1.0-pro",
            name="Gemini 1.0 Pro",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=32760,
            pricing={"input": 0.5, "output": 1.5},
        ),
        ModelInfo(
            id="gemini-1.0-pro-vision",
            name="Gemini 1.0 Pro Vision",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION],
            max_tokens=4096,
            context_window=16384,
            pricing={"input": 0.5, "output": 1.5},
        ),
        ModelInfo(
            id="gemini-pro-vision",
            name="Gemini Pro Vision",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION],
            max_tokens=4096,
            context_window=16384,
            pricing={"input": 0.5, "output": 1.5},
        ),
        ModelInfo(
            id="gemini-pro",
            name="Gemini Pro",
            provider="gemini",
            provider_type=ProviderType.GEMINI,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=8192,
            context_window=32760,
            pricing={"input": 0.5, "output": 1.5},
        ),
    ]
    
    def __init__(
        self,
        provider_id: str = "gemini",
        api_key: str = "",
        base_url: str = "https://generativelanguage.googleapis.com",
        **kwargs
    ):
        """初始化 Gemini Provider
        
        Args:
            provider_id: Provider 唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        super().__init__(
            provider_id=provider_id,
            provider_type=ProviderType.GEMINI,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )
        self.logger.info("Gemini Provider 初始化完成")
    
    async def get_available_models(self) -> typing.List[ModelInfo]:
        """获取可用的模型列表
        
        Returns:
            模型信息列表
        """
        # 尝试从 API 获取模型列表
        api_models = await self._fetch_models_from_api()
        if api_models:
            return api_models
        
        # 如果 API 获取失败，返回已知模型列表
        self.logger.info("使用已知模型列表")
        return self._get_known_models()
    
    async def _fetch_models_from_api(self) -> typing.List[ModelInfo]:
        """从 API 获取模型列表
        
        Returns:
            模型信息列表，失败返回空列表
        """
        if not aiohttp:
            self.logger.warning("aiohttp 未安装，无法从 API 获取模型列表")
            return []
        
        if not self.api_key:
            self.logger.warning("API 密钥未配置，无法获取模型列表")
            return []
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/v1beta/models?key={self.api_key}",
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        models = []
                        for model_data in data.get("models", []):
                            model_name = model_data.get("name", "")
                            if model_name:
                                # 提取模型 ID（去掉 "models/" 前缀）
                                model_id = model_name.replace("models/", "")
                                model_info = self._parse_api_model(model_data, model_id)
                                models.append(model_info)
                        self.logger.info(f"从 API 获取到 {len(models)} 个模型")
                        return models
                    else:
                        self.logger.warning(f"获取模型列表失败: HTTP {response.status}")
                        return []
        except Exception as e:
            self.logger.warning(f"从 API 获取模型列表失败: {e}")
            return []
    
    def _parse_api_model(self, model_data: Dict[str, Any], model_id: str) -> ModelInfo:
        """解析 API 返回的模型数据
        
        Args:
            model_data: API 返回的模型数据
            model_id: 模型ID
            
        Returns:
            ModelInfo 实例
        """
        capabilities = self._detect_capabilities(model_id)
        
        # 获取支持的生成方法
        supported_methods = model_data.get("supportedGenerationMethods", [])
        
        return ModelInfo(
            id=model_id,
            name=model_data.get("displayName", model_id),
            provider=self.provider_id,
            provider_type=ProviderType.GEMINI,
            capabilities=capabilities,
            max_tokens=8192,  # 默认值
            context_window=self._estimate_context_window(model_id),
            metadata={
                "description": model_data.get("description", ""),
                "supported_methods": supported_methods,
                "temperature": model_data.get("temperature"),
                "top_p": model_data.get("topP"),
            },
        )
    
    def _detect_capabilities(self, model_id: str) -> typing.List[ProviderCapability]:
        """检测模型能力
        
        Args:
            model_id: 模型ID
            
        Returns:
            能力列表
        """
        capabilities = [ProviderCapability.TEXT]
        model_id_lower = model_id.lower()
        
        # 视觉能力检测
        vision_keywords = ["vision", "pro-vision", "multimodal", "1.5", "1.0-pro"]
        if any(keyword in model_id_lower for keyword in vision_keywords):
            capabilities.append(ProviderCapability.VISION)
        
        # 音频能力检测（Gemini 1.5 支持音频）
        if "1.5" in model_id_lower:
            capabilities.append(ProviderCapability.AUDIO)
            capabilities.append(ProviderCapability.VIDEO)
            capabilities.append(ProviderCapability.TOOL_USE)
        
        # 工具使用能力检测
        if "pro" in model_id_lower and "vision" not in model_id_lower:
            capabilities.append(ProviderCapability.TOOL_USE)
        
        return capabilities
    
    def _estimate_context_window(self, model_id: str) -> int:
        """估算模型上下文窗口大小
        
        Args:
            model_id: 模型ID
            
        Returns:
            上下文窗口大小（tokens）
        """
        model_id_lower = model_id.lower()
        
        # 常见模型的上下文窗口
        context_windows = {
            "gemini-1.5-pro": 1048576,
            "gemini-1.5-flash": 1048576,
            "gemini-1.0-pro": 32760,
            "gemini-1.0-pro-vision": 16384,
            "gemini-pro-vision": 16384,
            "gemini-pro": 32760,
        }
        
        for pattern, window in context_windows.items():
            if pattern in model_id_lower:
                return window
        
        # 默认值
        return 32760
    
    def _get_known_models(self) -> typing.List[ModelInfo]:
        """获取已知模型列表
        
        Returns:
            已知模型列表
        """
        return self._KNOWN_MODELS.copy()
    
    def _get_default_pydantic_models(self) -> typing.List[ModelInfo]:
        """获取默认 Pydantic 模型列表
        
        Returns:
            默认模型列表
        """
        return self._KNOWN_MODELS.copy()
    
    def _make_headers(self) -> typing.Dict[str, str]:
        """构建请求头
        
        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json",
        }
        return headers
    
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
        if ChatGoogleGenerativeAI is None:
            raise ImportError("langchain_google_genai 未安装，无法创建模型实例")
        
        # 构建配置
        config = self.get_llm_config(model_id)
        config.update(kwargs)
        
        # 创建 ChatGoogleGenerativeAI 实例
        model = ChatGoogleGenerativeAI(
            model=model_id,
            google_api_key=self.api_key,
            **config
        )
        
        return model
    
    async def test_connection(self) -> ConnectionResult:
        """测试连接
        
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
            # 尝试获取模型列表
            models = await self.get_available_models()
            latency = (time.time() - start_time) * 1000
            
            return ConnectionResult(
                success=True,
                latency_ms=latency,
                models_available=len(models),
                metadata={
                    "provider": "gemini",
                    "base_url": self.base_url,
                }
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
                metadata={
                    "provider": "gemini",
                    "base_url": self.base_url,
                }
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
            # 尝试创建模型实例
            model = await self.create_chat_model(model_id)
            latency = (time.time() - start_time) * 1000
            
            return ConnectionResult(
                success=True,
                latency_ms=latency,
                metadata={"model_id": model_id}
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
                metadata={"model_id": model_id}
            )
    
    async def probe_model_multimodal(self, model_id: str) -> ProbeResult:
        """探测模型的多模态能力
        
        Args:
            model_id: 模型ID
            
        Returns:
            探测结果
        """
        start_time = time.time()
        
        # 基于模型名称推断能力
        capabilities = self._detect_capabilities(model_id)
        latency = (time.time() - start_time) * 1000
        
        return ProbeResult(
            model_id=model_id,
            supported=True,
            capabilities=capabilities,
            latency_ms=latency,
            metadata={
                "provider": "gemini",
                "detection_method": "name_heuristic",
            }
        )
    
    def get_llm_config(self, model_id: str) -> typing.Dict[str, typing.Any]:
        """获取 LLM 配置
        
        Args:
            model_id: 模型ID
            
        Returns:
            配置字典
        """
        config = super().get_llm_config(model_id)
        config.update({
            "provider": "gemini",
            "model": model_id,
        })
        return config


# 便捷函数
def create_gemini_provider(
    api_key: str,
    base_url: str = "https://generativelanguage.googleapis.com",
    **kwargs
) -> GeminiProvider:
    """创建 Gemini Provider 实例
    
    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        **kwargs: 其他配置参数
        
    Returns:
        GeminiProvider 实例
    """
    return GeminiProvider(
        provider_id="gemini",
        api_key=api_key,
        base_url=base_url,
        **kwargs
    )
