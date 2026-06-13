from __future__ import annotations

"""
OpenRouter Provider

支持 OpenRouter API（访问多个模型）
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
    from langchain_openai import ChatOpenAI
except ImportError:
    ChatOpenAI = None


logger = logging.getLogger(__name__)


class OpenRouterProvider(BaseProvider):
    """
    OpenRouter API Provider

    支持通过 OpenRouter 访问多个模型提供商
    """

    # 默认支持的模型列表（OpenRouter 热门模型）
    _DEFAULT_MODELS = [
        ModelInfo(
            id="openai/gpt-4o",
            name="GPT-4o (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=16384,
            context_window=128000,
            pricing={"input": 2.5, "output": 10.0},
        ),
        ModelInfo(
            id="openai/gpt-4o-mini",
            name="GPT-4o Mini (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=16384,
            context_window=128000,
            pricing={"input": 0.15, "output": 0.6},
        ),
        ModelInfo(
            id="anthropic/claude-3.5-sonnet",
            name="Claude 3.5 Sonnet (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=200000,
            pricing={"input": 3.0, "output": 15.0},
        ),
        ModelInfo(
            id="anthropic/claude-3-haiku",
            name="Claude 3 Haiku (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=200000,
            pricing={"input": 0.25, "output": 1.25},
        ),
        ModelInfo(
            id="google/gemini-1.5-pro",
            name="Gemini 1.5 Pro (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[
                ProviderCapability.TEXT,
                ProviderCapability.VISION,
                ProviderCapability.AUDIO,
                ProviderCapability.VIDEO,
                ProviderCapability.TOOL_USE,
            ],
            max_tokens=8192,
            context_window=1048576,
            pricing={"input": 3.5, "output": 10.5},
        ),
        ModelInfo(
            id="google/gemini-1.5-flash",
            name="Gemini 1.5 Flash (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[
                ProviderCapability.TEXT,
                ProviderCapability.VISION,
                ProviderCapability.AUDIO,
                ProviderCapability.VIDEO,
                ProviderCapability.TOOL_USE,
            ],
            max_tokens=8192,
            context_window=1048576,
            pricing={"input": 0.075, "output": 0.3},
        ),
        ModelInfo(
            id="meta-llama/llama-3.1-70b-instruct",
            name="Llama 3.1 70B (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=128000,
            pricing={"input": 0.52, "output": 0.75},
        ),
        ModelInfo(
            id="mistralai/mixtral-8x7b-instruct",
            name="Mixtral 8x7B (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=32768,
            pricing={"input": 0.24, "output": 0.24},
        ),
        ModelInfo(
            id="deepseek/deepseek-chat",
            name="DeepSeek Chat (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=32768,
            pricing={"input": 0.14, "output": 0.28},
        ),
        ModelInfo(
            id="qwen/qwen-2-72b-instruct",
            name="Qwen 2 72B (OpenRouter)",
            provider="openrouter",
            provider_type=ProviderType.OPENROUTER,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=32768,
            pricing={"input": 0.9, "output": 0.9},
        ),
    ]

    def __init__(
        self,
        provider_id: str = "openrouter",
        api_key: str = "",
        base_url: str = "https://openrouter.ai/api/v1",
        **kwargs,
    ):
        """初始化 OpenRouter Provider

        Args:
            provider_id: Provider 唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        super().__init__(
            provider_id=provider_id, provider_type=ProviderType.OPENROUTER, api_key=api_key, base_url=base_url, **kwargs
        )
        self.logger.info("OpenRouter Provider 初始化完成")

    async def get_available_models(self) -> typing.List[ModelInfo]:
        """获取可用的模型列表

        Returns:
            模型信息列表
        """
        # 尝试从 API 获取模型列表
        api_models = await self._fetch_models_from_api()
        if api_models:
            return api_models

        # 如果 API 获取失败，返回默认模型列表
        self.logger.info("使用默认模型列表")
        return self._get_default_models()

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
            headers = self._make_headers()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/models", headers=headers, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        models = []
                        for model_data in data.get("data", []):
                            model_id = model_data.get("id", "")
                            if model_id:
                                model_info = self._parse_api_model(model_data)
                                models.append(model_info)
                        self.logger.info("从 API 获取到 %s 个模型", len(models))
                        return models
                    else:
                        self.logger.warning("获取模型列表失败: HTTP %s", response.status)
                        return []
        except Exception as e:
            self.logger.warning("从 API 获取模型列表失败: %s", e)
            return []

    def _parse_api_model(self, model_data: Dict[str, Any]) -> ModelInfo:
        """解析 API 返回的模型数据

        Args:
            model_data: API 返回的模型数据

        Returns:
            ModelInfo 实例
        """
        model_id = model_data.get("id", "")
        capabilities = self._detect_capabilities(model_id)

        # 提取定价信息
        pricing = {}
        pricing_data = model_data.get("pricing", {})
        if pricing_data:
            # OpenRouter 定价格式：prompt 和 completion 价格（每 1M tokens）
            prompt_price = pricing_data.get("prompt", "0")
            completion_price = pricing_data.get("completion", "0")
            try:
                pricing = {
                    "input": float(prompt_price) * 1000000,
                    "output": float(completion_price) * 1000000,
                }
            except (ValueError, TypeError):
                pricing = {}

        # 获取上下文窗口
        context_length = model_data.get("context_length", 4096)

        return ModelInfo(
            id=model_id,
            name=model_data.get("name", model_id),
            provider=self.provider_id,
            provider_type=ProviderType.OPENROUTER,
            capabilities=capabilities,
            max_tokens=model_data.get("top_provider", {}).get("max_completion_tokens", 4096),
            context_window=context_length,
            pricing=pricing,
            metadata={
                "description": model_data.get("description", ""),
                "architecture": model_data.get("architecture", {}),
                "top_provider": model_data.get("top_provider", {}),
                "per_request_limits": model_data.get("per_request_limits"),
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
        vision_keywords = ["vision", "gpt-4v", "gpt-4-v", "image", "multimodal", "llava", "vl-"]
        if any(keyword in model_id_lower for keyword in vision_keywords):
            capabilities.append(ProviderCapability.VISION)

        # 工具使用能力检测
        tool_keywords = ["gpt-4", "gpt-3.5-turbo", "claude-3", "gemini", "llama-3", "mistral", "mixtral"]
        if any(keyword in model_id_lower for keyword in tool_keywords):
            capabilities.append(ProviderCapability.TOOL_USE)

        # 音频能力检测
        audio_keywords = ["whisper", "audio", "asr", "tts", "speech", "voice"]
        if any(keyword in model_id_lower for keyword in audio_keywords):
            capabilities.append(ProviderCapability.AUDIO)

        # 图像生成能力检测
        image_gen_keywords = ["dall-e", "stable-diffusion", "midjourney", "image-generation"]
        if any(keyword in model_id_lower for keyword in image_gen_keywords):
            capabilities.append(ProviderCapability.IMAGE_GENERATION)

        return capabilities

    def _get_default_models(self) -> typing.List[ModelInfo]:
        """获取默认模型列表

        Returns:
            默认模型列表
        """
        return self._DEFAULT_MODELS.copy()

    def _get_default_pydantic_models(self) -> typing.List[ModelInfo]:
        """获取默认 Pydantic 模型列表

        Returns:
            默认模型列表
        """
        return self._DEFAULT_MODELS.copy()

    def _make_headers(self) -> typing.Dict[str, str]:
        """构建请求头

        Returns:
            请求头字典
        """
        headers = {
            "Content-Type": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def create_chat_model(self, model_id: str, **kwargs) -> typing.Any:
        """创建聊天模型实例

        Args:
            model_id: 模型ID
            **kwargs: 模型配置参数

        Returns:
            模型实例
        """
        if ChatOpenAI is None:
            raise ImportError("langchain_openai 未安装，无法创建模型实例")

        # 构建配置
        config = self.get_llm_config(model_id)
        config.update(kwargs)

        # 创建 ChatOpenAI 实例（OpenRouter 使用 OpenAI 兼容 API）
        model = ChatOpenAI(model=model_id, api_key=self.api_key, base_url=self.base_url, **config)

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
                    "provider": "openrouter",
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
                    "provider": "openrouter",
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
                "provider": "openrouter",
                "detection_method": "name_heuristic",
            },
        )

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
                "provider": "openrouter",
                "model": model_id,
            }
        )
        return config


# 便捷函数
def create_openrouter_provider(
    api_key: str, base_url: str = "https://openrouter.ai/api/v1", **kwargs
) -> OpenRouterProvider:
    """创建 OpenRouter Provider 实例

    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        **kwargs: 其他配置参数

    Returns:
        OpenRouterProvider 实例
    """
    return OpenRouterProvider(provider_id="openrouter", api_key=api_key, base_url=base_url, **kwargs)
