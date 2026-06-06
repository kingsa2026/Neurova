"""
Generator manager
Unified management for text-to-image, text-to-video, image-to-video, keyframe-to-video, video-to-video

集成 LLMRouter 实现自动模型选择
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


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
        if hasattr(self, '_initialized'):
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
        self,
        generator_type: str,
        prompt: str,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        **kwargs
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
                return self._create_error_result(
                    f"Generator type '{generator_type}' not available"
                )
            
            # 如果未指定模型，使用 LLMRouter 选择
            if model is None and self._llm_router:
                request_type = self._map_to_llm_request_type(generator_type)
                if request_type:
                    model_info = self._llm_router.get_best_model(request_type)
                    if model_info:
                        model = model_info.get("model")
                        provider = model_info.get("provider")
            
            # 执行生成
            result = await generator.generate(
                prompt=prompt,
                model=model,
                provider=provider,
                **kwargs
            )
            
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

    def _create_error_result(
        self,
        error: str,
        duration_ms: float = 0.0
    ) -> GeneratorResult:
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
