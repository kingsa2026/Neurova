"""
LM Studio Provider

支持本地 LM Studio 服务
"""

import logging
import typing
from typing import Any, Dict

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


class LMStudioProvider(BaseProvider):
    """
    LM Studio API Provider

    支持本地 LM Studio 服务，提供 OpenAI 兼容的 API
    """

    # 默认支持的模型列表（LM Studio 本地模型）
    _DEFAULT_MODELS = [
        ModelInfo(
            id="local-model",
            name="Local Model",
            provider="lm_studio",
            provider_type=ProviderType.CUSTOM,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=4096,
            pricing={"input": 0.0, "output": 0.0},
        ),
    ]

    def __init__(
        self,
        provider_id: str = "lm_studio",
        api_key: str = "lm-studio",
        base_url: str = "http://localhost:1234/v1",
        **kwargs,
    ):
        """初始化 LM Studio Provider

        Args:
            provider_id: Provider 唯一标识符
            api_key: API 密钥（LM Studio 不需要，使用默认值）
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        super().__init__(
            provider_id=provider_id, provider_type=ProviderType.CUSTOM, api_key=api_key, base_url=base_url, **kwargs
        )
        self.logger.info("LM Studio Provider 初始化完成: base_url=%s", self.base_url)

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

        try:
            headers = self._make_headers()
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/models", headers=headers, timeout=aiohttp.ClientTimeout(total=5)
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

        return ModelInfo(
            id=model_id,
            name=model_data.get("id", "").replace("-", " ").title(),
            provider=self.provider_id,
            provider_type=ProviderType.CUSTOM,
            capabilities=capabilities,
            max_tokens=4096,  # 默认值
            context_window=self._estimate_context_window(model_id),
            metadata=model_data,
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
        vision_keywords = ["vision", "llava", "multimodal", "vl-"]
        if any(keyword in model_id_lower for keyword in vision_keywords):
            capabilities.append(ProviderCapability.VISION)

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
            "llama": 4096,
            "mistral": 32768,
            "mixtral": 32768,
            "phi": 2048,
            "gemma": 8192,
            "qwen": 32768,
            "codellama": 16384,
            "vicuna": 4096,
            "wizard": 4096,
            "openchat": 4096,
            "starling": 4096,
            "yi": 4096,
            "deepseek": 16384,
            "solar": 4096,
            "command": 4096,
        }

        for pattern, window in context_windows.items():
            if pattern in model_id_lower:
                return window

        # 默认值
        return 4096

    def _get_default_models(self) -> typing.List[ModelInfo]:
        """获取默认模型列表

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

        # 创建 ChatOpenAI 实例（LM Studio 使用 OpenAI 兼容 API）
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
                    "provider": "lm_studio",
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
                    "provider": "lm_studio",
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
                "provider": "lm_studio",
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
                "provider": "lm_studio",
                "model": model_id,
            }
        )
        return config


# 便捷函数
def create_lm_studio_provider(base_url: str = "http://localhost:1234/v1", **kwargs) -> LMStudioProvider:
    """创建 LM Studio Provider 实例

    Args:
        base_url: API 基础 URL
        **kwargs: 其他配置参数

    Returns:
        LMStudioProvider 实例
    """
    return LMStudioProvider(provider_id="lm_studio", base_url=base_url, **kwargs)
