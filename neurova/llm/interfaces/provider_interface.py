"""
Neurova LLM Provider Interface
LLM 提供商统一接口定义 - 适配器模式基础
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Generator
from dataclasses import dataclass, field
from enum import Enum
import time


class ProviderType(str, Enum):
    """Supported provider types"""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GEMINI = "gemini"
    OLLAMA = "ollama"
    LOCAL = "local"


@dataclass
class ProviderConfig:
    """Provider configuration"""
    api_key: str
    base_url: Optional[str] = None
    model_name: str = "gpt-4o"
    timeout_seconds: float = 60.0
    max_retries: int = 3
    temperature: float = 0.7
    top_p: float = 1.0
    
    # Security settings
    sandbox_enabled: bool = True
    max_tokens_per_call: int = 8192
    rate_limit_requests_per_minute: int = 60


@dataclass
class Message:
    """Message structure"""
    role: str  # "system", "user", "assistant"
    content: str


@dataclass
class CallResult:
    """LLM call result"""
    content: str
    usage: Dict[str, int]  # prompt_tokens, completion_tokens, total_tokens
    model: str
    finish_reason: str
    latency_seconds: float
    cost_usd: float = 0.0
    raw_response: Optional[Dict] = None


class LLMAbstractProvider(ABC):
    """
    Abstract base class for LLM providers
    
    All providers must implement these methods to ensure consistency
    """
    
    def __init__(self, config: ProviderConfig):
        self.config = config
        self._call_count = 0
        self._last_error: Optional[str] = None
    
    @property
    @abstractmethod
    def provider_type(self) -> ProviderType:
        """Return provider type identifier"""
        pass
    
    @abstractmethod
    async def call(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> CallResult:
        """
        Main entry point for LLM calls
        
        Args:
            messages: Conversation history
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
        
        Returns:
            CallResult with response and metadata
        """
        pass
    
    @abstractmethod
    async def stream_call(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
    ) -> Generator[str, None, None]:
        """Stream responses token by token"""
        pass
    
    @abstractmethod
    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate API call cost in USD"""
        pass
    
    def get_stats(self) -> Dict[str, Any]:
        """Get provider statistics"""
        return {
            "provider": self.provider_type.value,
            "model": self.config.model_name,
            "total_calls": self._call_count,
            "last_error": self._last_error,
        }
    
    def reset_stats(self) -> None:
        """Reset statistics"""
        self._call_count = 0
        self._last_error = None


class ChatProvider(LLMAbstractProvider):
    """Chat-based provider interface"""
    
    async def chat(
        self,
        messages: List[Message],
        **kwargs,
    ) -> CallResult:
        """Convenience method for chat completions"""
        return await self.call(messages, **kwargs)


class CompletionProvider(LLMAbstractProvider):
    """Text completion provider interface"""
    
    @abstractmethod
    async def complete(
        self,
        prompt: str,
        **kwargs,
    ) -> CallResult:
        """Text completion"""
        pass
