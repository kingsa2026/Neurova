"""
Generator manager
统一管理与分发 AIGC 生成类型（text_to_image / image_to_image / text_to_video / image_to_video …）

批次0 修复（渠道 AIGC 复活）：
- 原 ``generate()`` 使用未导入的 ``GenType``/``GenerationConfig`` 名字——NameError
  被外层 except 吞成 error，任何调用必失败；现改为真实导入并按 GeneratorType 分发。
- ``_map_to_llm_request_type`` 返回大写枚举名但查 ``RequestType(值)``（小写值），
  恒 ValueError 被静默吞；现映射到 RequestType 真实值。
- 六个 BaseGenerator「虚构端点」实现体（文档判定假 API 路径，从未真实产出）
  已随批次0删除；统一走 ``runtime.ProtocolGenerator`` → ``protocols.py`` 实测矩阵。
"""

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neurova.llm.generators.base import GenerationConfig, GenerationResult, GeneratorType
from neurova.llm.generators.runtime import GenerationCredsError, ProtocolGenerator

logger = get_logger(__name__)

# 生成器类型（注册面 key 用 GeneratorType 值字符串）
_GENERATOR_TYPES = [
    GeneratorType.TEXT_TO_IMAGE,
    GeneratorType.IMAGE_TO_IMAGE,
    GeneratorType.TEXT_TO_VIDEO,
    GeneratorType.IMAGE_TO_VIDEO,
    GeneratorType.KEYFRAME_TO_VIDEO,
    GeneratorType.VIDEO_TO_VIDEO,
]


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
    """生成器统一管理器（facade：一切生成类型 → ProtocolGenerator → 实测协议）。"""

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

        self._register_default_generators()

    def _register_default_generators(self) -> None:
        """注册实测协议 facade 实例（批次0：六件虚构端点实现已删，统一 ProtocolGenerator）。"""
        for gtype in _GENERATOR_TYPES:
            self._generators[gtype.value] = ProtocolGenerator(
                generator_id=gtype.value, generator_type=gtype
            )

    def _load_providers(self) -> None:
        """加载可用的提供者"""
        if self._provider_manager:
            try:
                providers = self._provider_manager.list_providers()
                logger.info("Loaded %d providers", len(providers))
            except Exception as e:
                logger.warning("Failed to load providers: %s", str(e))

    def get_generator(self, generator_type: str, model: Optional[str] = None) -> Optional[Any]:
        """
        获取指定类型的生成器。

        Args:
            generator_type: 生成器类型（str 或 GeneratorType 枚举值）
            model: 兼容位——渠道 mixin 以 ``get_generator(type, model)`` 二参调用；
                模型选择发生在 config/generate 阶段，此处仅接受不消费。

        Returns:
            生成器实例或 None
        """
        key = generator_type.value if isinstance(generator_type, GeneratorType) else str(generator_type)
        return self._generators.get(key)

    async def generate(
        self, generator_type: str, prompt: str, model: Optional[str] = None, provider: Optional[str] = None, **kwargs
    ) -> GeneratorResult:
        """
        执行生成任务（facade 入口；渠道/脚本可用的高层 API）。

        Args:
            generator_type: 生成器类型
            prompt: 生成提示
            model: 指定模型（可选；缺省时 LLMRouter 按能力路由）
            provider: 指定提供者（可选）
            **kwargs: 透传 GenerationConfig.extra_params

        Returns:
            GeneratorResult 执行结果
        """
        start_time = time.time()

        try:
            try:
                gtype = GeneratorType(generator_type)
            except ValueError:
                return self._create_error_result(
                    f"Generator type '{generator_type}' not supported", duration_ms=0.0
                )

            generator = self.get_generator(gtype)
            if generator is None:
                return self._create_error_result(f"Generator type '{generator_type}' not available")

            # 如果未指定模型，使用 LLMRouter 选择
            if model is None and self._llm_router:
                request_type = self._map_to_llm_request_type(gtype.value)
                if request_type:
                    try:
                        from neurova.llm.llm_router import RequestType as _RT

                        model_info = self._llm_router.select_model(_RT(request_type))
                        if model_info:
                            model = getattr(model_info, "model", None)
                            provider = getattr(model_info, "provider_id", provider)
                    except Exception as e:
                        logger.warning("模型自动选择失败，使用默认模型: %s", e)

            config = GenerationConfig(
                type=gtype,
                prompt=prompt,
                model=model or "",
                model_id=model or "",
                extra_params=kwargs,
            )
            result: GenerationResult = await generator.generate(config)

            duration_ms = (time.time() - start_time) * 1000

            return GeneratorResult(
                success=result.success,
                data=result,
                error=result.error or None,
                model_used=model,
                provider_used=provider,
                duration_ms=duration_ms,
            )

        except GenerationCredsError as e:
            duration_ms = (time.time() - start_time) * 1000
            return self._create_error_result(str(e), duration_ms=duration_ms)
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error("Generation failed: %s", str(e))
            return self._create_error_result(str(e), duration_ms=duration_ms)

    def _map_to_llm_request_type(self, generator_type: str) -> Optional[str]:
        """映射生成器类型到 LLM 请求类型（RequestType 枚举值，小写）。

        批次0 根因修复：旧实现返回 ``"IMAGE_GENERATION"``（大写名）喂
        ``RequestType(...)``（其值为小写 ``image_generation`` 等）→ 恒 ValueError
        被上层静默吞掉，auto 路由从未生效。
        """
        mapping = {
            "text_to_image": "text_to_image",
            "text_to_video": "text_to_video",
            "image_to_image": "image_to_image",
            "image_to_video": "image_to_video",
            "keyframe_to_video": "image_to_video",
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
