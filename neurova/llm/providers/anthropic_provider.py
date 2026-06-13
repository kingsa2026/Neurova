from __future__ import annotations

"""
Anthropic Provider

支持 Anthropic Claude API
"""

import logging
import time
import typing

from neurova.llm.providers.base import BaseProvider
from neurova.llm.providers.types import ConnectionResult, ModelInfo, ProbeResult, ProviderCapability, ProviderType

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None


logger = logging.getLogger(__name__)


class AnthropicProvider(BaseProvider):
    """
    Anthropic Claude API Provider

    支持 Claude 系列模型，包括视觉和工具使用能力
    """

    # 默认支持的模型列表
    _KNOWN_MODELS = [
        ModelInfo(
            id="claude-3-5-sonnet-20241022",
            name="Claude 3.5 Sonnet",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=200000,
            pricing={"input": 3.0, "output": 15.0},
        ),
        ModelInfo(
            id="claude-3-5-haiku-20241022",
            name="Claude 3.5 Haiku",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=200000,
            pricing={"input": 0.25, "output": 1.25},
        ),
        ModelInfo(
            id="claude-3-opus-20240229",
            name="Claude 3 Opus",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=200000,
            pricing={"input": 15.0, "output": 75.0},
        ),
        ModelInfo(
            id="claude-3-sonnet-20240229",
            name="Claude 3 Sonnet",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=200000,
            pricing={"input": 3.0, "output": 15.0},
        ),
        ModelInfo(
            id="claude-3-haiku-20240307",
            name="Claude 3 Haiku",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=200000,
            pricing={"input": 0.25, "output": 1.25},
        ),
        ModelInfo(
            id="claude-2.1",
            name="Claude 2.1",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=200000,
            pricing={"input": 8.0, "output": 24.0},
        ),
        ModelInfo(
            id="claude-2.0",
            name="Claude 2.0",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=100000,
            pricing={"input": 8.0, "output": 24.0},
        ),
        ModelInfo(
            id="claude-instant-1.2",
            name="Claude Instant 1.2",
            provider="anthropic",
            provider_type=ProviderType.ANTHROPIC,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=100000,
            pricing={"input": 0.8, "output": 2.4},
        ),
    ]

    def __init__(
        self, provider_id: str = "anthropic", api_key: str = "", base_url: str = "https://api.anthropic.com", **kwargs
    ):
        """初始化 Anthropic Provider

        Args:
            provider_id: Provider 唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        super().__init__(
            provider_id=provider_id, provider_type=ProviderType.ANTHROPIC, api_key=api_key, base_url=base_url, **kwargs
        )
        self.logger.info("Anthropic Provider 初始化完成")

    async def get_available_models(self) -> typing.List[ModelInfo]:
        """获取可用的模型列表

        Returns:
            模型信息列表
        """
        # Anthropic 没有公开的模型列表 API
        # 返回已知的模型列表
        return self._get_known_models()

    def _get_known_models(self) -> typing.List[ModelInfo]:
        """获取已知模型列表

        Returns:
            已知模型列表
        """
        return self._KNOWN_MODELS.copy()

    def _get_known_pydantic_models(self) -> typing.List[ModelInfo]:
        """获取已知 Pydantic 模型列表

        Returns:
            已知模型列表
        """
        return self._KNOWN_MODELS.copy()

    def _make_headers(self) -> typing.Dict[str, str]:
        """构建请求头

        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers

    async def create_chat_model(self, model_id: str, **kwargs) -> typing.Any:
        """创建聊天模型实例

        Args:
            model_id: 模型ID
            **kwargs: 模型配置参数

        Returns:
            模型实例
        """
        if ChatAnthropic is None:
            raise ImportError("langchain_anthropic 未安装，无法创建模型实例")

        # 构建配置
        config = self.get_llm_config(model_id)
        config.update(kwargs)

        # 创建 ChatAnthropic 实例
        model = ChatAnthropic(model=model_id, anthropic_api_key=self.api_key, **config)

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
                    "provider": "anthropic",
                    "base_url": self.base_url,
                },
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
                metadata={
                    "provider": "anthropic",
                    "base_url": self.base_url,
                },
            )

    async def fetch_models(self) -> typing.List[ModelInfo]:
        """获取模型列表（带缓存）

        Returns:
            模型信息列表
        """
        current_time = time.time()
        if self._models_cache and current_time - self._models_cache_time < self._cache_ttl:
            return self._models_cache + self._extra_models

        try:
            models = await self.get_available_models()
            self._models_cache = models
            self._models_cache_time = current_time
            return models + self._extra_models
        except Exception as e:
            self.logger.error("获取模型列表失败: %s", e)
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
            await self.create_chat_model(model_id)
            latency = (time.time() - start_time) * 1000

            return ConnectionResult(success=True, latency_ms=latency, metadata={"model_id": model_id})
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(success=False, latency_ms=latency, error=str(e), metadata={"model_id": model_id})

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
                "provider": "anthropic",
                "detection_method": "name_heuristic",
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

        # Claude 3 系列支持视觉和工具使用
        if "claude-3" in model_id_lower:
            capabilities.append(ProviderCapability.VISION)
            capabilities.append(ProviderCapability.TOOL_USE)

        # Claude 3.5 系列支持更强的视觉能力
        if "claude-3-5" in model_id_lower or "claude-3.5" in model_id_lower:
            capabilities.append(ProviderCapability.MULTIMODAL)

        return capabilities

    def get_llm_config(self, model_id: str) -> typing.Dict[str, typing.Any]:
        """获取 LLM 配置

        Args:
            model_id: 模型ID

        Returns:
            配置字典
        """
        config = super().get_llm_config(model_id)
        config.update(
            {
                "provider": "anthropic",
                "model": model_id,
            }
        )
        return config


# 便捷函数
def create_anthropic_provider(api_key: str, base_url: str = "https://api.anthropic.com", **kwargs) -> AnthropicProvider:
    """创建 Anthropic Provider 实例

    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        **kwargs: 其他配置参数

    Returns:
        AnthropicProvider 实例
    """
    return AnthropicProvider(provider_id="anthropic", api_key=api_key, base_url=base_url, **kwargs)
