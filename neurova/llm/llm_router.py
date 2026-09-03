from __future__ import annotations

"""
LLM Router - 多模态自适应路由器

根据请求类型（文本、图像、音频、视频等）自动选择最佳LLM模型。
支持多模态自适应切换，包括：
- 文本聊天
- 图像理解
- 音频理解
- 视频理解
- 文生图
- 图生图
- 文生视频
- 图生视频
- 语音合成
- 语音识别
"""

from neurova.core.logger import get_logger
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class RequestType(Enum):
    """请求类型枚举"""

    CHAT = "chat"  # 文本聊天
    IMAGE_UNDERSTANDING = "image_understanding"  # 图像理解
    AUDIO_UNDERSTANDING = "audio_understanding"  # 音频理解
    VIDEO_UNDERSTANDING = "video_understanding"  # 视频理解
    TEXT_TO_IMAGE = "text_to_image"  # 文生图
    IMAGE_TO_IMAGE = "image_to_image"  # 图生图
    TEXT_TO_VIDEO = "text_to_video"  # 文生视频
    IMAGE_TO_VIDEO = "image_to_video"  # 图生视频
    TEXT_TO_SPEECH = "text_to_speech"  # 语音合成 (TTS)
    SPEECH_TO_TEXT = "speech_to_text"  # 语音识别 (STT)


class ModelCapability(Enum):
    """模型能力枚举"""

    TEXT = "text"  # 文本处理
    REASONING = "reasoning"  # 深度推理
    VISION = "vision"  # 视觉理解
    AUDIO = "audio"  # 音频处理
    VIDEO = "video"  # 视频处理
    IMAGE_GENERATION = "image_generation"  # 图像生成
    VIDEO_GENERATION = "video_generation"  # 视频生成
    TTS = "tts"  # 语音合成
    STT = "stt"  # 语音识别
    MULTIMODAL = "multimodal"  # 多模态
    TOOL_USE = "tool_use"  # 工具使用


@dataclass
class ModelSelectionResult:
    """模型选择结果"""

    provider_id: str
    provider_name: str
    model: str
    capabilities: List[ModelCapability] = field(default_factory=list)
    priority: int = 0
    health_status: str = "unknown"
    response_time: float = 0.0
    weight: float = 1.0


class LLMRouter:
    """
    LLM 单例路由器

    根据请求类型自动选择最佳模型，支持：
    - 多提供商注册
    - 能力匹配
    - 优先级排序
    - 健康状态检查
    - 响应时间优化
    """

    _instance: Optional["LLMRouter"] = None

    def __new__(cls) -> "LLMRouter":
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化路由器"""
        if self._initialized:
            return

        self._providers: Dict[str, Dict[str, Any]] = {}
        self._initialized = True
        logger.info("LLMRouter initialized")

    def register_provider(self, provider_id: str, provider_name: str, models: List[Dict[str, Any]]):
        """
        注册提供商

        Args:
            provider_id: 提供商ID
            provider_name: 提供商名称
            models: 模型列表，每个模型包含：
                - name: 模型名称
                - capabilities: 能力列表
                - priority: 优先级
                - health_status: 健康状态
                - response_time: 响应时间
                - weight: 权重
        """
        self._providers[provider_id] = {"name": provider_name, "models": models}
        logger.info("Provider registered: %s (%s) with %s models", provider_id, provider_name, len(models))

    def unregister_provider(self, provider_id: str):
        """
        注销提供商

        Args:
            provider_id: 提供商ID
        """
        if provider_id in self._providers:
            del self._providers[provider_id]
            logger.info("Provider unregistered: %s", provider_id)

    def list_providers(self) -> List[Dict[str, Any]]:
        """
        列出所有提供商

        Returns:
            提供商列表
        """
        result = []
        for provider_id, provider_data in self._providers.items():
            result.append(
                {"provider_id": provider_id, "provider_name": provider_data["name"], "models": provider_data["models"]}
            )
        return result

    def select_model(
        self,
        request_type: RequestType,
        required_capabilities: Optional[List[ModelCapability]] = None,
        exclude_providers: Optional[List[str]] = None,
    ) -> Optional[ModelSelectionResult]:
        """
        根据请求类型选择最佳模型

        Args:
            request_type: 请求类型
            required_capabilities: 必需的能力列表
            exclude_providers: 排除的提供商列表

        Returns:
            最佳模型选择结果，如果没有合适的模型返回None
        """
        exclude_providers = exclude_providers or []

        # 收集所有候选模型
        candidates = []

        for provider_id, provider_data in self._providers.items():
            if provider_id in exclude_providers:
                continue

            for model_data in provider_data["models"]:
                # 检查健康状态
                if model_data.get("health_status") == "unhealthy":
                    continue

                # 检查能力匹配（未知能力字符串防御性跳过，不炸路由链路）
                model_capabilities: List[ModelCapability] = []
                for cap in model_data.get("capabilities", []):
                    try:
                        model_capabilities.append(ModelCapability(cap))
                    except ValueError:
                        continue

                # 检查是否满足必需能力
                if required_capabilities:
                    if not all(cap in model_capabilities for cap in required_capabilities):
                        continue

                # 检查请求类型匹配
                if not self._matches_request_type(request_type, model_capabilities):
                    continue

                # 创建候选结果
                candidate = ModelSelectionResult(
                    provider_id=provider_id,
                    provider_name=provider_data["name"],
                    model=model_data["name"],
                    capabilities=model_capabilities,
                    priority=model_data.get("priority", 0),
                    health_status=model_data.get("health_status", "healthy"),
                    response_time=model_data.get("response_time", 0.0),
                    weight=model_data.get("weight", 1.0),
                )

                candidates.append(candidate)

        if not candidates:
            logger.warning("No model found for request type: %s", request_type.value)
            return None

        # auto 路由健康过滤：429 退避暂停中的模型本轮跳过（落到同能力下一候选）。
        # 全部暂停时降级返回排序首位（路由可用的兜底，由限流器在调用前拦截）。
        try:
            from neurova.llm.model_rate_limiter import get_shared_limiter

            limiter = get_shared_limiter()
            healthy = [c for c in candidates if limiter.pause_remaining(c.model) <= 0.0]
            if healthy:
                candidates = healthy
        except Exception as e:  # noqa: BLE001 - 限流器不可用时按原序路由
            logger.debug("路由健康过滤跳过（限流器不可用）: %s", e)

        # 按优先级和响应时间排序
        candidates.sort(key=lambda x: (-x.priority, x.response_time, -x.weight))

        selected = candidates[0]
        logger.info("Model selected: %s/%s " f"for %s", selected.provider_name, selected.model, request_type.value)

        return selected

    def _matches_request_type(self, request_type: RequestType, capabilities: List[ModelCapability]) -> bool:
        """
        检查模型能力是否匹配请求类型

        Args:
            request_type: 请求类型
            capabilities: 模型能力列表

        Returns:
            是否匹配
        """
        # 请求类型到必需能力的映射
        capability_requirements = {
            RequestType.CHAT: [ModelCapability.TEXT],
            RequestType.IMAGE_UNDERSTANDING: [ModelCapability.VISION],
            RequestType.AUDIO_UNDERSTANDING: [ModelCapability.AUDIO],
            RequestType.VIDEO_UNDERSTANDING: [ModelCapability.VIDEO],
            RequestType.TEXT_TO_IMAGE: [ModelCapability.IMAGE_GENERATION],
            RequestType.IMAGE_TO_IMAGE: [ModelCapability.IMAGE_GENERATION],
            RequestType.TEXT_TO_VIDEO: [ModelCapability.VIDEO_GENERATION],
            RequestType.IMAGE_TO_VIDEO: [ModelCapability.VIDEO_GENERATION],
            RequestType.TEXT_TO_SPEECH: [ModelCapability.TTS],
            RequestType.SPEECH_TO_TEXT: [ModelCapability.STT],
        }

        required = capability_requirements.get(request_type, [ModelCapability.TEXT])

        # 检查是否满足所有必需能力
        return all(cap in capabilities for cap in required)


# ---------------------------------------------------------------------------
# 全局单例与 Provider 同步
# ---------------------------------------------------------------------------
# 根因修复（code-review P0-#4）：原先每次调用都 `LLMRouter()` 新建空实例且从未
# 调用 `register_provider()`，导致 `select_model()` 永远返回 None、多模态路由
# 静默降级。改为共享单例 + 从 LLMProviderManager 单例惰性同步 provider。

_router_instance: Optional["LLMRouter"] = None
_router_lock = threading.Lock()


def get_llm_router() -> "LLMRouter":
    """获取全局 LLMRouter 单例（懒初始化）。"""
    global _router_instance
    if _router_instance is None:
        with _router_lock:
            if _router_instance is None:
                _router_instance = LLMRouter()
    return _router_instance


def _infer_capabilities(model_name: str) -> List[ModelCapability]:
    """根据模型名关键词推断能力（委托 capability_detector 单一来源）。"""
    from neurova.llm.capability_detector import infer_capabilities as _detect

    return [
        ModelCapability(c)
        for c in _detect(model_name)
        if c in {m.value for m in ModelCapability}
    ]


def register_provider_from_config(
    provider_id: str,
    provider_name: str,
    model_names: List[str],
    model_metadata: Optional[Dict[str, Dict[str, Any]]] = None,
) -> None:
    """将 ProviderConfig 风格的 providers 注册到全局 LLMRouter。

    能力来源：provider.model_metadata 中已持久化的 capabilities 优先
    （模型管理页"自动检测"写入），缺失时名称推断兜底 —— 路由与标记同源。
    """
    from neurova.llm.capability_detector import detect_model_capabilities

    router = get_llm_router()
    metadata = model_metadata or {}
    models = []
    for m in model_names or []:
        meta = metadata.get(m, {}) or {}
        caps = detect_model_capabilities(
            m,
            existing=[str(c) for c in (meta.get("capabilities") or [])],
            display_name=str(meta.get("name") or ""),
        )
        models.append(
            {
                "name": m,
                "capabilities": [c for c in caps if c in {mc.value for mc in ModelCapability}],
                "priority": 1,
                "health_status": "healthy",
                "response_time": 0.0,
                "weight": 1.0,
            }
        )
    router.register_provider(provider_id, provider_name, models)


def sync_llm_router() -> None:
    """Best-effort：将 LLMProviderManager 单例的 providers 同步到全局 LLMRouter。"""
    try:
        from neurova.llm.provider_manager import get_provider_manager

        mgr = get_provider_manager()
        if mgr is None:
            return
        for pid, pconf in mgr._providers.items():
            register_provider_from_config(pid, pconf.name, pconf.models, pconf.model_metadata)
    except Exception as e:  # noqa: BLE001
        logger.warning("sync_llm_router 失败（多模态路由将惰性回退）: %s", e)


# 便捷函数
def select_model_for_request(
    request_type: RequestType, required_capabilities: Optional[List[ModelCapability]] = None
) -> Optional[ModelSelectionResult]:
    """
    为请求类型选择最佳模型的便捷函数

    Args:
        request_type: 请求类型
        required_capabilities: 必需的能力列表

    Returns:
        最佳模型选择结果
    """
    router = get_llm_router()
    # 惰性同步：首次调用且无 provider 时，尝试从 LLMProviderManager 拉取
    if not router._providers:
        sync_llm_router()
    return router.select_model(request_type, required_capabilities)


def detect_request_type(content: str) -> RequestType:
    """
    自动检测请求类型

    根据输入内容自动判断应该使用哪种请求类型。

    Args:
        content: 用户输入内容

    Returns:
        检测到的请求类型
    """
    content_lower = content.lower()

    # 优先检测发送文件标记（最精确）
    if "[用户发送了一张图片" in content:
        return RequestType.IMAGE_UNDERSTANDING

    if "[用户发送了一段语音" in content:
        return RequestType.AUDIO_UNDERSTANDING

    if "[用户发送了一个视频" in content:
        return RequestType.VIDEO_UNDERSTANDING

    # 检测生成请求（需在通用关键词之前）
    # 文生图：生成/画/创建/绘制 + 图片/图像/图画/照片
    if re.search(r"(生成|画|创建|绘制|制作|搞|弄|来).{0,10}(图片|图像|图画|照片)", content_lower):
        return RequestType.TEXT_TO_IMAGE

    # 文生视频：制作/生成/创建 + 视频/影片/录像
    if re.search(r"(制作|生成|创建|制作|搞|弄|来).{0,10}(视频|影片|录像)", content_lower):
        return RequestType.TEXT_TO_VIDEO

    # 语音合成：用语音读出/朗读/语音播放/读出来/念出来
    if any(keyword in content_lower for keyword in ["用语音读出", "朗读", "语音播放", "读出来", "念出来", "语音读"]):
        return RequestType.TEXT_TO_SPEECH

    # 检测多模态理解请求（通用关键词，仅在非生成场景时匹配）
    if "图片" in content_lower or "图像" in content_lower or "照片" in content_lower:
        return RequestType.IMAGE_UNDERSTANDING

    if "语音" in content_lower or "音频" in content_lower or "声音" in content_lower:
        return RequestType.AUDIO_UNDERSTANDING

    if "视频" in content_lower or "录像" in content_lower or "影片" in content_lower:
        return RequestType.VIDEO_UNDERSTANDING

    # 默认为文本聊天
    return RequestType.CHAT


# 请求类型到能力的映射
REQUEST_TYPE_CAPABILITIES: Dict[RequestType, List[ModelCapability]] = {
    RequestType.CHAT: [ModelCapability.TEXT],
    RequestType.IMAGE_UNDERSTANDING: [ModelCapability.VISION],
    RequestType.AUDIO_UNDERSTANDING: [ModelCapability.AUDIO],
    RequestType.VIDEO_UNDERSTANDING: [ModelCapability.VIDEO],
    RequestType.TEXT_TO_IMAGE: [ModelCapability.IMAGE_GENERATION],
    RequestType.IMAGE_TO_IMAGE: [ModelCapability.IMAGE_GENERATION],
    RequestType.TEXT_TO_VIDEO: [ModelCapability.VIDEO_GENERATION],
    RequestType.IMAGE_TO_VIDEO: [ModelCapability.VIDEO_GENERATION],
    RequestType.TEXT_TO_SPEECH: [ModelCapability.TTS],
    RequestType.SPEECH_TO_TEXT: [ModelCapability.STT],
}
