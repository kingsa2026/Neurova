from __future__ import annotations

"""
Ollama Provider

支持本地 Ollama 服务
"""

from neurova.core.logger import get_logger
import time
import typing

from neurova.llm.providers.base import BaseProvider
from neurova.llm.providers.types import ConnectionResult, ModelInfo, ProbeResult, ProviderCapability, ProviderType

try:
    import aiohttp
except ImportError:
    aiohttp = None

try:
    from langchain_ollama import ChatOllama
except ImportError:
    ChatOllama = None

try:
    import langchain_community.chat_models
except ImportError:
    langchain_community = None


logger = get_logger(__name__)


class OllamaProvider(BaseProvider):
    """
    Ollama API Provider

    支持本地 Ollama 服务，包括模型管理和推理
    """

    # 默认支持的模型列表（常用本地模型）
    _DEFAULT_MODELS = [
        ModelInfo(
            id="llama3.1",
            name="Llama 3.1",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=128000,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="llama3.1:8b",
            name="Llama 3.1 8B",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=128000,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="llama3.1:70b",
            name="Llama 3.1 70B",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=128000,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="mistral",
            name="Mistral",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=32768,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="mixtral",
            name="Mixtral",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=32768,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="phi3",
            name="Phi-3",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=128000,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="gemma2",
            name="Gemma 2",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=8192,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="qwen2",
            name="Qwen 2",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=32768,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="codellama",
            name="Code Llama",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT],
            max_tokens=4096,
            context_window=16384,
            pricing={"input": 0.0, "output": 0.0},
        ),
        ModelInfo(
            id="llava",
            name="LLaVA",
            provider="ollama",
            provider_type=ProviderType.OLLAMA,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION],
            max_tokens=4096,
            context_window=4096,
            pricing={"input": 0.0, "output": 0.0},
        ),
    ]

    def __init__(
        self, provider_id: str = "ollama", api_key: str = "", base_url: str = "http://localhost:11434", **kwargs
    ):
        """初始化 Ollama Provider

        Args:
            provider_id: Provider 唯一标识符
            api_key: API 密钥（Ollama 不需要）
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        super().__init__(
            provider_id=provider_id, provider_type=ProviderType.OLLAMA, api_key=api_key, base_url=base_url, **kwargs
        )
        self.logger.info("Ollama Provider 初始化完成: base_url=%s", self.base_url)

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
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{self.base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status == 200:
                        data = await response.json()
                        models = []
                        for model_data in data.get("models", []):
                            model_name = model_data.get("name", "")
                            if model_name:
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
        model_name = model_data.get("name", "")
        model_id = model_name.split(":")[0] if ":" in model_name else model_name
        capabilities = self._detect_capabilities(model_name)

        # 获取模型大小信息
        size = model_data.get("size", 0)
        size_gb = size / (1024**3) if size else 0

        return ModelInfo(
            id=model_name,
            name=model_id.replace("-", " ").title(),
            provider=self.provider_id,
            provider_type=ProviderType.OLLAMA,
            capabilities=capabilities,
            max_tokens=4096,  # 默认值
            context_window=self._estimate_context_window(model_name),
            metadata={
                "size": size,
                "size_gb": round(size_gb, 2),
                "modified_at": model_data.get("modified_at", ""),
                "digest": model_data.get("digest", ""),
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
        vision_keywords = ["llava", "vision", "multimodal"]
        if any(keyword in model_id_lower for keyword in vision_keywords):
            capabilities.append(ProviderCapability.VISION)

        # 工具使用能力检测（Llama 3.1、Mistral 等支持）
        tool_keywords = ["llama3", "llama-3", "mistral", "mixtral", "qwen2"]
        if any(keyword in model_id_lower for keyword in tool_keywords):
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
            "llama3.1": 128000,
            "llama3": 8192,
            "llama2": 4096,
            "mistral": 32768,
            "mixtral": 32768,
            "phi3": 128000,
            "gemma2": 8192,
            "qwen2": 32768,
            "codellama": 16384,
            "llava": 4096,
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
        return headers

    async def create_chat_model(self, model_id: str, **kwargs) -> typing.Any:
        """创建聊天模型实例

        Args:
            model_id: 模型ID
            **kwargs: 模型配置参数

        Returns:
            模型实例
        """
        if ChatOllama is None:
            raise ImportError("langchain_ollama 未安装，无法创建模型实例")

        # 构建配置
        config = self.get_llm_config(model_id)
        config.update(kwargs)

        # 创建 ChatOllama 实例
        model = ChatOllama(model=model_id, base_url=self.base_url, **config)

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
                    "provider": "ollama",
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
                    "provider": "ollama",
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
                "provider": "ollama",
                "detection_method": "name_heuristic",
            },
        )

    async def pull_model(self, model_name: str) -> bool:
        """拉取模型

        Args:
            model_name: 模型名称

        Returns:
            是否成功
        """
        if not aiohttp:
            self.logger.error("aiohttp 未安装，无法拉取模型")
            return False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{self.base_url}/api/pull",
                    json={"name": model_name, "stream": False},
                    timeout=aiohttp.ClientTimeout(total=300),  # 5分钟超时
                ) as response:
                    if response.status == 200:
                        self.logger.info("模型 %s 拉取成功", model_name)
                        # 清除缓存
                        self.invalidate_models_cache()
                        return True
                    else:
                        self.logger.error("模型 %s 拉取失败: HTTP %s", model_name, response.status)
                        return False
        except Exception as e:
            self.logger.error("模型 %s 拉取失败: %s", model_name, e)
            return False

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
                "provider": "ollama",
                "model": model_id,
            }
        )
        return config


# 便捷函数
def create_ollama_provider(base_url: str = "http://localhost:11434", **kwargs) -> OllamaProvider:
    """创建 Ollama Provider 实例

    Args:
        base_url: API 基础 URL
        **kwargs: 其他配置参数

    Returns:
        OllamaProvider 实例
    """
    return OllamaProvider(provider_id="ollama", base_url=base_url, **kwargs)
