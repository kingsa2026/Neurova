"""
LLM 模块

包含:
- LLM Router: 多模态自适应路由器
- Providers: LLM 提供商实现
- Generators: 文本生成器
"""


from .llm_router import (
    LLMRouter,
    ModelCapability,
    ModelSelectionResult,
    RequestType,
    detect_request_type,
    select_model_for_request,
)

__all__ = [
    "RequestType",
    "ModelCapability",
    "ModelSelectionResult",
    "LLMRouter",
    "select_model_for_request",
    "detect_request_type",
]
