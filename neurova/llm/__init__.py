"""
LLM 模块

包含:
- LLM Router: 多模态自适应路由器
- Providers: LLM 提供商实现
- Generators: 文本生成器
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from .llm_router import (
        LLMRouter,
        ModelCapability,
        ModelSelectionResult,
        RequestType,
        detect_request_type,
        select_model_for_request,
    )
except ImportError as _e:
    _logger.debug("llm_router 模块未可用: %s", _e)
    RequestType = None
    ModelCapability = None
    ModelSelectionResult = None
    LLMRouter = None
    select_model_for_request = None
    detect_request_type = None

__all__ = [
    "RequestType",
    "ModelCapability",
    "ModelSelectionResult",
    "LLMRouter",
    "select_model_for_request",
    "detect_request_type",
]
