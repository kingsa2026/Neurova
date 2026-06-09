"""
LLM 模块

包含:
- LLM Router: 多模态自适应路由器
- Providers: LLM 提供商实现
- Generators: 文本生成器
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from .llm_router import (
        RequestType,
        ModelCapability,
        ModelSelectionResult,
        LLMRouter,
        select_model_for_request,
        detect_request_type,
    )
except ImportError as _e:
    _logger.debug(f"llm_router 模块未可用: {_e}")
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