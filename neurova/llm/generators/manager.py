"""
Generator manager
Unified management for text-to-image, text-to-video, image-to-video, keyframe-to-video, video-to-video

集成 LLMRouter 实现自动模型选择
"""

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)

# BUG AUDIT L-02: 生成器类型 → (模块后缀, 类名) 映射，用于按类型注册真实实例
_GENERATOR_REGISTRY: Dict[str, tuple] = {
    "text_to_image": ("text_to_image", "TextToImageGenerator"),
    "image_to_image": ("image_to_image", "ImageToImageGenerator"),
    "text_to_video": ("text_to_video", "TextToVideoGenerator"),
    "image_to_video": ("image_to_video", "ImageToVideoGenerator"),
    "keyframe_to_video": ("keyframe_to_video", "KeyframeToVideoGenerator"),
    "video_to_video": ("video_to_video", "VideoToVideoGenerator"),
}


@dataclass
class GeneratorResult:
    """生成器执行结果"""

    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
    model_used: Optional[str] = None
    provider_used: Optional[str] = None
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error": self.error,
            "model_used": self.model_used,
            "provider_used": self.provider_used,
            "duration_ms": self.duration_ms,
            "metadata": self.metadata,
        }


class GeneratorManager:
    """生成器统一管理器"""

    _instance: Optional["GeneratorManager"] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        if hasattr(self, "_initialized"):
            return
        self._initialized = True
        self._config = config or {}
        self._generators: Dict[str, Any] = {}
        self._provider_manager = None
        self._llm_router = None
        self._initialize_generators()
        logger.info("GeneratorManager initialized")

    def _initialize_generators(self) -> None:
        """初始化所有生成器"""
        # 延迟导入避免循环依赖
        try:
            from neurova.llm.llm_router import LLMRouter

            self._llm_router = LLMRouter()
        except ImportError:
            logger.warning("LLMRouter not available")

        try:
            from neurova.llm.provider_manager import get_provider_manager

            self._provider_manager = get_provider_manager()
        except ImportError:
            logger.warning("ProviderManager not available")

        # BUG AUDIT L-02: 此前 self._generators 全局唯一赋值处只有 `{}`，
        # 从不写入，导致所有 AIGC 调用返回 "not available"。在此注册真实实例。
        self._register_default_generators()

    def _register_default_generators(self) -> None:
        """按 _GENERATOR_REGISTRY 注册真实生成器实例（BUG AUDIT L-02 根因修复）。

        旧实现中 self._generators 从不写入，get_generator 恒返回 None，
        所有文生图/图生图/文生视频/图生视频均报 "not available"。
        """
        api_key = ""
        base_url = ""
        if self._provider_manager is not None:
            try:
                api_key = getattr(self._provider_manager, "default_api_key", "") or ""
                base_url = getattr(self._provider_manager, "default_base_url", "") or ""
            except Exception as e:
                logger.warning("读取 provider 凭据失败: %s", e)

        for gen_type, (module_suffix, cls_name) in _GENERATOR_REGISTRY.items():
            try:
                import importlib

                mod = importlib.import_module(f"neurova.llm.generators.{module_suffix}")
                cls = getattr(mod, cls_name)
                self._generators[gen_type] = cls(
                    generator_id=gen_type, api_key=api_key, base_url=base_url
                )
            except Exception as e:
                logger.error("注册生成器 %s(%s) 失败: %s", gen_type, cls_name, e)

    def _load_providers(self) -> None:
        """加载可用的提供者"""
        if self._provider_manager:
            try:
                providers = self._provider_manager.list_providers()
                logger.info("Loaded %d providers", len(providers))
            except Exception as e:
                logger.warning("Failed to load providers: %s", str(e))

    def get_generator(self, generator_type: str) -> Optional[Any]:
        """
        获取指定类型的生成器

        Args:
            generator_type: 生成器类型 (text_to_image, text_to_video, etc.)

        Returns:
            生成器实例或 None
        """
        return self._generators.get(generator_type)

    async def generate(
        self, generator_type: str, prompt: str, model: Optional[str] = None, provider: Optional[str] = None, **kwargs
    ) -> GeneratorResult:
        """
        执行生成任务

        Args:
            generator_type: 生成器类型
            prompt: 生成提示
            model: 指定模型（可选）
            provider: 指定提供者（可选）
            **kwargs: 其他参数

        Returns:
            GeneratorResult 执行结果
        """
        start_time = time.time()

        try:
            # 获取生成器
            generator = self.get_generator(generator_type)
            if generator is None:
                return self._create_error_result(f"Generator type '{generator_type}' not available")

            # 如果未指定模型，使用 LLMRouter 选择
            # BUG AUDIT L-02: 旧代码调用不存在的 get_best_model()，且返回值为
            # ModelSelectionResult（含 .model / .provider_id 属性而非 dict）。
            if model is None and self._llm_router:
                request_type = self._map_to_llm_request_type(generator_type)
                if request_type:
                    try:
                        from neurova.llm.llm_router import RequestType as _RT

                        model_info = self._llm_router.select_model(_RT(request_type))
                        if model_info:
                            model = getattr(model_info, "model", None)
                            provider = getattr(model_info, "provider_id", provider)
                    except Exception as e:
                        logger.warning("模型自动选择失败，使用默认模型: %s", e)

            # 构造 GenerationConfig 并调用生成器
            # BUG AUDIT L-02: BaseGenerator.generate 接收 config: GenerationConfig，
            # 旧代码用 generate(prompt=..., model=...) 会 TypeError。
            try:
                gtype = GenType(generator_type)
            except ValueError:
                gtype = GenType.TEXT_GENERATION
            config = GenerationConfig(
                type=gtype,
                prompt=prompt,
                model_id=model or "",
                extra_params=kwargs,
            )
            result = await generator.generate(config)

            duration_ms = (time.time() - start_time) * 1000

            return GeneratorResult(
                success=True,
                data=result,
                model_used=model,
                provider_used=provider,
                duration_ms=duration_ms,
            )

        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("Generation failed: %s", str(e))
            return self._create_error_result(str(e), duration_ms=duration_ms)

    def _map_to_llm_request_type(self, generator_type: str) -> Optional[str]:
        """映射生成器类型到 LLM 请求类型"""
        mapping = {
            "text_to_image": "IMAGE_GENERATION",
            "text_to_video": "VIDEO_GENERATION",
            "image_to_image": "IMAGE_GENERATION",
            "image_to_video": "VIDEO_GENERATION",
            "keyframe_to_video": "VIDEO_GENERATION",
            "video_to_video": "VIDEO_GENERATION",
        }
        return mapping.get(generator_type)

    def _get_provider(self, provider_name: str) -> Optional[Any]:
        """获取指定的提供者"""
        if self._provider_manager:
            try:
                return self._provider_manager.get_provider(provider_name)
            except Exception as e:
                logger.warning("Failed to get provider %s: %s", provider_name, str(e))
        return None

    def list_available_providers(self) -> List[str]:
        """列出可用的提供者"""
        if self._provider_manager:
            try:
                return [p.name for p in self._provider_manager.list_providers()]
            except Exception:
                pass
        return []

    def refresh_providers(self) -> None:
        """刷新提供者列表"""
        self._load_providers()

    def _create_error_result(self, error: str, duration_ms: float = 0.0) -> GeneratorResult:
        """创建错误结果"""
        return GeneratorResult(
            success=False,
            error=error,
            duration_ms=duration_ms,
        )


# 全局单例
_manager_instance: Optional[GeneratorManager] = None
_manager_lock = threading.Lock()


def get_generator_manager(config: Optional[Dict[str, Any]] = None) -> GeneratorManager:
    """获取 GeneratorManager 单例"""
    global _manager_instance
    if _manager_instance is None:
        with _manager_lock:
            if _manager_instance is None:
                _manager_instance = GeneratorManager(config=config)
    return _manager_instance


def reset_generator_manager() -> None:
    """重置 GeneratorManager 单例（用于测试）"""
    global _manager_instance
    with _manager_lock:
        _manager_instance = None
