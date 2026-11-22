from __future__ import annotations

"""
Anthropic Provider

支持 Anthropic Claude API
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
    from langchain_anthropic import ChatAnthropic
except ImportError:
    ChatAnthropic = None


logger = get_logger(__name__)


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
            模型信息列表（真实为空时即空）

        2026-11-17 根治假成功：/v1/models 真实探测取代"返回已知模型静态清单"
        ——静态清单让 check_connection 一个网络包都不发就报成功。静态清单保留
        为素材（_get_known_models），不再用于判活。
        """
        return await self._fetch_models_from_api()

    async def _fetch_models_from_api(self) -> typing.List[ModelInfo]:
        """从 /v1/models 获取真实模型列表

        Returns:
            模型信息列表（无 key 时为空——管理器预检已拦截该场景）

        Raises:
            非 200/网络失败 — 带 status_code 的异常上抛（吞错返回空列表会让
            连接测试误判成功）。
        """
        if not aiohttp:
            self.logger.warning("aiohttp 未安装，无法从 API 获取模型列表")
            return []

        if not self.api_key:
            self.logger.warning("API 密钥未配置，无法获取模型列表")
            return []

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.base_url}/v1/models",
                headers=self._make_headers(),
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    exc = RuntimeError(f"获取模型列表失败: HTTP {response.status}")
                    exc.status_code = response.status
                    raise exc
                data = await response.json()
                models = []
                for model_data in data.get("data", []):
                    model_id = model_data.get("id", "")
                    if model_id:
                        models.append(self._parse_api_model(model_data, model_id))
                self.logger.info("从 API 获取到 %s 个模型", len(models))
                return models

    def _parse_api_model(self, model_data: typing.Dict[str, typing.Any], model_id: str) -> ModelInfo:
        """解析 /v1/models 返回的模型数据（静态素材可按 id 丰富元信息）"""
        known = next((m for m in self._KNOWN_MODELS if m.id == model_id), None)
        return ModelInfo(
            id=model_id,
            name=model_data.get("display_name", model_id),
            provider=self.provider_id,
            provider_type=ProviderType.ANTHROPIC,
            capabilities=list(known.capabilities) if known else [ProviderCapability.TEXT],
            max_tokens=known.max_tokens if known else 8192,
            context_window=known.context_window if known else 200000,
            metadata=model_data,
        )

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

        # ChatAnthropic 的 anthropic_api_key/anthropic_api_url 接受 api_key/base_url
        # 作为别名，model 按字段名填充（populate_by_name=True）→ base 的中性装配够用
        return ChatAnthropic(**self.get_llm_config(model_id, **kwargs))

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

        2026-11-17 同根因扫平（审计 3.2-1）：旧实现仅本地构造模型实例、不触网，
        对死服务/错 key 恒报成功；现改为对真实 /v1/models 清单做 found 判定
        （provider_only 形态，与 base 默认实现对齐）。

        Args:
            model_id: 模型ID

        Returns:
            连接测试结果
        """
        start_time = time.time()

        try:
            models = await self._fetch_models_from_api()
            latency = (time.time() - start_time) * 1000
            found = any(m.id == model_id for m in models)
            return ConnectionResult(
                success=found,
                latency_ms=latency,
                error="" if found else f"Model '{model_id}' not found in provider's model list",
                models_available=len(models),
                verification="provider_only",
                metadata={"model_id": model_id, "retryable": False},
            )
        except Exception as e:
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
                verification="provider_only",
                metadata={"model_id": model_id},
            )

    async def probe_model_multimodal(self, model_id: str) -> ProbeResult:
        """探测模型的多模态能力：真图探测（红图 + 主色调提问，anthropic 原生形态）。

        M7 遗留收口（2026-11-22）：原实现仅名称启发式且恒 ``supported=True``——
        声明与实测无从对齐。现走 `multimodal_prober.probeProviderVision` 探测
        矩阵（HTTP 层可桩化进 CI，真 Key 手动档同入口）；探测下不了结论时如实
        透传 inconclusive，不再拿名称启发式冒充实测。
        """
        from neurova.llm.providers.multimodal_prober import probeProviderVision

        probed = await probeProviderVision("anthropic", model_id, self.base_url, self.api_key)
        if probed.metadata.get("probe_source") != "probed":
            return probed

        capabilities = self._detect_capabilities(model_id)
        if probed.supported:
            if ProviderCapability.VISION not in capabilities:
                capabilities = [*capabilities, ProviderCapability.VISION]
        else:
            capabilities = [c for c in capabilities if c != ProviderCapability.VISION]
        return ProbeResult(
            model_id=model_id,
            supported=probed.supported,
            capabilities=capabilities,
            latency_ms=probed.latency_ms,
            metadata={**probed.metadata, "provider": "anthropic"},
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

    # get_llm_config 不在此覆盖：base 的中性装配已满足 ChatAnthropic 的字段别名，
    # 原覆盖多塞的 provider/model 属服务商元数据与重复键（见 base.get_llm_config）。


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
