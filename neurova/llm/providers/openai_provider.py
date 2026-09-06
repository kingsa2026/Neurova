from __future__ import annotations

"""
OpenAI Provider

Support OpenAI API compatible providers
"""

from neurova.core.logger import get_logger
import time
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


logger = get_logger(__name__)


class OpenAIProvider(BaseProvider):
    """
    OpenAI API Compatible Provider

    支持 OpenAI 官方 API 以及兼容的第三方服务（如 DeepSeek、Qwen 等）
    """

    # 默认支持的模型列表
    _DEFAULT_MODELS = [
        ModelInfo(
            id="gpt-4o",
            name="GPT-4o",
            provider="openai",
            provider_type=ProviderType.OPENAI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=16384,
            context_window=128000,
            pricing={"input": 2.5, "output": 10.0},
        ),
        ModelInfo(
            id="gpt-4o-mini",
            name="GPT-4o Mini",
            provider="openai",
            provider_type=ProviderType.OPENAI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=16384,
            context_window=128000,
            pricing={"input": 0.15, "output": 0.6},
        ),
        ModelInfo(
            id="gpt-4-turbo",
            name="GPT-4 Turbo",
            provider="openai",
            provider_type=ProviderType.OPENAI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.VISION, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=128000,
            pricing={"input": 10.0, "output": 30.0},
        ),
        ModelInfo(
            id="gpt-3.5-turbo",
            name="GPT-3.5 Turbo",
            provider="openai",
            provider_type=ProviderType.OPENAI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=4096,
            context_window=16385,
            pricing={"input": 0.5, "output": 1.5},
        ),
        ModelInfo(
            id="gpt-4",
            name="GPT-4",
            provider="openai",
            provider_type=ProviderType.OPENAI,
            capabilities=[ProviderCapability.TEXT, ProviderCapability.TOOL_USE],
            max_tokens=8192,
            context_window=8192,
            pricing={"input": 30.0, "output": 60.0},
        ),
    ]

    # 平台检测关键词
    _PLATFORM_KEYWORDS = {
        "dashscope": "DashScope",
        "deepseek": "DeepSeek",
        "qwen": "Qwen",
        "siliconflow": "SiliconFlow",
        "moonshot": "Moonshot",
        "zhipu": "Zhipu",
        "baichuan": "Baichuan",
        "minimax": "MiniMax",
        "stepfun": "StepFun",
        "yi": "Yi",
        "spark": "Spark",
    }

    def __init__(
        self, provider_id: str = "openai", api_key: str = "", base_url: str = "https://api.openai.com/v1", **kwargs
    ):
        """初始化 OpenAI Provider

        Args:
            provider_id: Provider 唯一标识符
            api_key: API 密钥
            base_url: API 基础 URL
            **kwargs: 其他配置参数
        """
        super().__init__(
            provider_id=provider_id, provider_type=ProviderType.OPENAI, api_key=api_key, base_url=base_url, **kwargs
        )
        self._platform_name = self._detect_platform()
        self.logger.info("OpenAI Provider 初始化完成: platform=%s", self._platform_name)

    def _detect_platform(self) -> str:
        """检测平台类型"""
        base_url_lower = self.base_url.lower()
        for keyword, platform_name in self._PLATFORM_KEYWORDS.items():
            if keyword in base_url_lower:
                return platform_name
        return "OpenAI"

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

        return ModelInfo(
            id=model_id,
            name=model_data.get("id", "").replace("-", " ").title(),
            provider=self.provider_id,
            provider_type=ProviderType.OPENAI,
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
        vision_keywords = ["vision", "gpt-4v", "gpt-4-v", "image", "multimodal", "llava", "vl-"]
        if any(keyword in model_id_lower for keyword in vision_keywords):
            capabilities.append(ProviderCapability.VISION)

        # 工具使用能力检测
        if any(keyword in model_id_lower for keyword in ["gpt-4", "gpt-3.5-turbo", "gpt-4o"]):
            capabilities.append(ProviderCapability.TOOL_USE)

        # 音频能力检测
        audio_keywords = ["whisper", "audio", "asr", "tts", "speech", "voice"]
        if any(keyword in model_id_lower for keyword in audio_keywords):
            capabilities.append(ProviderCapability.AUDIO)

        # 图像生成能力检测
        image_gen_keywords = ["dall-e", "image-generation", "img-gen"]
        if any(keyword in model_id_lower for keyword in image_gen_keywords):
            capabilities.append(ProviderCapability.IMAGE_GENERATION)

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
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 16385,
            "gpt-3.5-turbo-16k": 16385,
            "gpt-4-32k": 32768,
            "gpt-4-vision-preview": 128000,
            "dall-e": 0,  # 图像生成模型
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

        # 创建 ChatOpenAI 实例
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
                    "platform": self._platform_name,
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
                    "platform": self._platform_name,
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

    def _get_default_pydantic_models(self) -> typing.List[ModelInfo]:
        """获取默认 Pydantic 模型列表

        Returns:
            默认模型列表
        """
        return self._DEFAULT_MODELS.copy()

    async def check_model_connection(self, model_id: str) -> ConnectionResult:
        """检查特定模型的连接状态（QwenPaw 对齐：真实 chat 探测）。

        对该模型发一次受限 max_tokens 的 chat 请求（live 验证）；
        非对话模型（embedding/tts/whisper/rerank）无法走 chat 端点，
        降级为 provider 级连通验证（provider_only）。
        """
        from neurova.llm.providers.error_mapping import normalize_provider_error

        start_time = time.time()
        model_id = (model_id or "").strip()

        if self._is_non_chat_model(model_id):
            result = await self.check_connection()
            result.metadata = {**result.metadata, "model_id": model_id, "verification": "provider_only"}
            return result

        try:
            await self._chat_probe(model_id)
            latency = (time.time() - start_time) * 1000
            return ConnectionResult(
                success=True,
                latency_ms=latency,
                verification="live",
                http_status=200,
                metadata={"model_id": model_id},
            )
        except Exception as e:  # noqa: BLE001 — 探测必须吞掉一切异常并归一返回
            latency = (time.time() - start_time) * 1000
            normalized = normalize_provider_error(e)
            http_status = getattr(e, "status_code", None)
            if not isinstance(http_status, int):
                http_status = getattr(getattr(e, "response", None), "status_code", None)
            return ConnectionResult(
                success=False,
                latency_ms=latency,
                error=str(e),
                error_category=normalized.category.value,
                error_hint=normalized.user_hint,
                verification="live",
                http_status=http_status if isinstance(http_status, int) else None,
                retryable=normalized.retryable,
                metadata={"model_id": model_id},
            )

    # 非对话模型关键词：chat 端点必然拒绝，走 provider 级降级验证
    _NON_CHAT_HINTS = ("embedding", "tts", "whisper", "rerank", "moderation", "dall-e", "dalle", "speech")

    @classmethod
    def _is_non_chat_model(cls, model_id: str) -> bool:
        lower = (model_id or "").lower()
        return any(hint in lower for hint in cls._NON_CHAT_HINTS)

    async def _chat_probe(self, model_id: str, timeout_seconds: float = 12.0) -> None:
        """对该模型发一次最小 chat 请求验证可用性；任何失败以异常抛出。"""
        if not aiohttp:
            raise RuntimeError("aiohttp 未安装，无法进行模型级连接探测")
        headers = self._make_headers()
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 16,
            "stream": False,
        }
        timeout = aiohttp.ClientTimeout(total=timeout_seconds) if hasattr(aiohttp, "ClientTimeout") else None
        async with aiohttp.ClientSession() as session:
            kwargs = {"headers": headers, "json": payload}
            if timeout is not None:
                kwargs["timeout"] = timeout
            async with session.post(url, **kwargs) as response:
                if response.status >= 400:
                    exc = RuntimeError(f"HTTP {response.status}: probe rejected")
                    exc.status_code = response.status
                    try:
                        body = await response.json()
                        detail = str(body.get("error", {}).get("message", body))
                        exc = RuntimeError(f"HTTP {response.status}: {detail}")
                        exc.status_code = response.status
                    except Exception:  # noqa: BLE001 — body 解析失败保留状态码信息
                        pass
                    raise exc
                await response.json()

    async def probe_model_multimodal(self, model_id: str) -> ProbeResult:
        """探测模型的多模态能力（QwenPaw 对齐：真实图像探测）。

        发送 32x32 纯红 PNG data URL + 主色调提问（受限 max_tokens），
        语义校验答案含红色系关键词才判 vision 支持（防纯文本模型静默
        忽略图片造成假阳性）。请求被媒体关键词拒绝 → 判不支持；
        其他 API 错误 → inconclusive。失败回退名称启发式。
        """
        start_time = time.time()
        capabilities = self._detect_capabilities(model_id)

        try:
            answer = await self._image_probe_request(model_id)
        except Exception as e:  # noqa: BLE001 — 探测失败必须归一返回而非炸链
            message = str(e).lower()
            if self._is_media_keyword_error(message):
                return ProbeResult(
                    model_id=model_id,
                    supported=False,
                    capabilities=self._detect_capabilities(model_id),
                    latency_ms=(time.time() - start_time) * 1000,
                    metadata={
                        "platform": self._platform_name,
                        "probe_source": "probed",
                        "probe_detail": "media_rejected",
                    },
                )
            # 其他 API 错误（限频/网络等）无法下结论 → inconclusive
            return ProbeResult(
                model_id=model_id,
                supported=False,
                capabilities=[],
                latency_ms=(time.time() - start_time) * 1000,
                metadata={
                    "platform": self._platform_name,
                    "probe_source": "inconclusive",
                    "probe_detail": str(e)[:300],
                },
            )

        from neurova.llm.providers.multimodal_prober import evaluate_image_probe_answer

        evaluation = evaluate_image_probe_answer(answer)
        # QwenPaw 语义校验：探测图为纯红，答案含红色系关键词才算真支持
        # （防纯文本模型静默忽略图片答非所问造成假阳性）
        _red_keywords = ("red", "scarlet", "crimson", "红", "赤")
        answer_text = str(answer or "").lower()
        saw_red = any(k in answer_text for k in _red_keywords)
        if evaluation.get("supports_vision") or saw_red:
            if ProviderCapability.VISION not in capabilities:
                capabilities = [*capabilities, ProviderCapability.VISION]
            supported = True
            probe_source = "probed"
        elif evaluation.get("confidence", 0) >= 0.5:
            # 明确的否定（negative_marker）→ 文本模型
            supported = False
            probe_source = "probed"
            capabilities = [c for c in capabilities if c != ProviderCapability.VISION]
        else:
            # 答非所问（no_marker/empty）→ 无法下结论
            supported = False
            probe_source = "inconclusive"

        return ProbeResult(
            model_id=model_id,
            supported=supported,
            capabilities=capabilities,
            latency_ms=(time.time() - start_time) * 1000,
            metadata={
                "platform": self._platform_name,
                "probe_source": probe_source,
                "probe_answer": str(answer)[:200],
            },
        )

    # 32x32 纯红 PNG（约 96 字节，探测成本可忽略）
    _IMAGE_PROBE_PNG_BASE64 = (
        "iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GOqjAAAAAXNSR0IArs4c6QAAABxpRE9YAAAAAgAAAAAAAACw"
        "AAAAAQAAAADtDZoWAAAAAmJLR0QA/v2C1wAAABl0RVh0U29mdHdhcmUAdXBzY2FsZSBpbWFnZccAaPAAAAAZdEVY"
        "dENyZWF0aW9uIFRpbWUAMjAvMDEvMDbT2hveAAAAHHRFWHRTb2Z0d2FyZQBSYXN0ZXJiYW5rIHNjb3BlyhR3FwAA"
        "AABJRU5ErkJggg=="
    )
    _IMAGE_PROBE_PROMPT = "What is the single dominant color of this image? Reply with ONLY the color name."

    # 媒体拒绝关键词（请求被明确拒绝 → 判不支持）
    _MEDIA_REJECT_KEYWORDS = (
        "image", "vision", "multimodal", "photo", "picture",
        "media", "video", "audio", "input_image", "base64",
    )

    @classmethod
    def _is_media_keyword_error(cls, message: str) -> bool:
        text = (message or "").lower()
        if "does not support" in text or "unsupported" in text or "not supported" in text:
            return any(k in text for k in cls._MEDIA_REJECT_KEYWORDS)
        return "no image" in text or "image_url" in text

    async def _image_probe_request(self, model_id: str, timeout_seconds: float = 20.0) -> str:
        """发图像探测请求，返回模型文本答案；HTTP >= 400 抛异常。"""
        if not aiohttp:
            raise RuntimeError("aiohttp 未安装，无法进行图像探测")
        data_url = f"data:image/png;base64,{self._IMAGE_PROBE_PNG_BASE64}"
        payload = {
            "model": model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": data_url}},
                        {"type": "text", "text": self._IMAGE_PROBE_PROMPT},
                    ],
                }
            ],
            "max_tokens": 200,
            "stream": False,
        }
        timeout = aiohttp.ClientTimeout(total=timeout_seconds) if hasattr(aiohttp, "ClientTimeout") else None
        async with aiohttp.ClientSession() as session:
            kwargs = {"headers": self._make_headers(), "json": payload}
            if timeout is not None:
                kwargs["timeout"] = timeout
            async with session.post(f"{self.base_url}/chat/completions", **kwargs) as response:
                if response.status >= 400:
                    detail = ""
                    try:
                        body = await response.json()
                        detail = str(body.get("error", {}).get("message", body))
                    except Exception:  # noqa: BLE001 — body 解析失败保留状态码
                        detail = await response.text() if hasattr(response, "text") else ""
                    exc = RuntimeError(f"HTTP {response.status}: {detail or 'probe rejected'}")
                    exc.status_code = response.status
                    raise exc
                data = await response.json()
                choices = data.get("choices") or [{}]
                message = choices[0].get("message") or {}
                return str(message.get("content") or message.get("reasoning_content") or "")

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
                "platform": self._platform_name,
                "model": model_id,
            }
        )
        return config


# 便捷函数
def create_openai_provider(api_key: str, base_url: str = "https://api.openai.com/v1", **kwargs) -> OpenAIProvider:
    """创建 OpenAI Provider 实例

    Args:
        api_key: API 密钥
        base_url: API 基础 URL
        **kwargs: 其他配置参数

    Returns:
        OpenAIProvider 实例
    """
    return OpenAIProvider(provider_id="openai", api_key=api_key, base_url=base_url, **kwargs)
