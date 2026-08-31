from __future__ import annotations

"""
Provider 核心类型定义

使用 Pydantic 模型定义 Provider 和 Model 的数据结构，
提供类型安全和序列化支持。
"""

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ProviderType(str, Enum):
    """Provider 类型"""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    OPENCODE = "opencode"
    CUSTOM = "custom"


class ProviderCapability(str, Enum):
    """Provider 能力"""

    TEXT = "text"
    VISION = "vision"
    AUDIO = "audio"
    VIDEO = "video"
    IMAGE_GENERATION = "image_generation"
    VIDEO_GENERATION = "video_generation"
    TTS = "tts"
    STT = "stt"
    MULTIMODAL = "multimodal"
    TOOL_USE = "tool_use"


class ModelInfo(BaseModel):
    """模型信息"""

    id: str = ""
    name: str = ""
    provider: str = ""
    provider_type: ProviderType = ProviderType.OPENAI
    capabilities: List[ProviderCapability] = Field(default_factory=list)
    max_tokens: int = 4096
    context_window: int = 4096
    pricing: Dict[str, float] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    # 归属服务商 id(_get_all_models 聚合视图用;model.py 端点按此映射 provider)
    owned_by: str = ""
    is_free: bool = False

    def to_dict(self) -> Dict[str, Any]:
        # requirements: pydantic>=2.5;model_dump 为 v2 原生 API
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ModelInfo":
        return cls(**data)


class ProviderInfo(BaseModel):
    """Provider 信息"""

    id: str = ""
    name: str = ""
    provider_type: ProviderType = ProviderType.OPENAI
    api_key: str = ""
    base_url: str = ""
    models: List[ModelInfo] = Field(default_factory=list)
    capabilities: List[ProviderCapability] = Field(default_factory=list)
    enabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        # requirements: pydantic>=2.5;model_dump 为 v2 原生 API
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProviderInfo":
        return cls(**data)


class ProbeResult(BaseModel):
    """模型探测结果"""

    model_id: str = ""
    supported: bool = False
    capabilities: List[ProviderCapability] = Field(default_factory=list)
    latency_ms: float = 0.0
    error: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ConnectionResult(BaseModel):
    """连接测试结果"""

    success: bool = False
    latency_ms: float = 0.0
    error: str = ""
    models_available: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
