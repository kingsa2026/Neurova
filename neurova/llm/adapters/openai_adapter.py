"""
Neurova OpenAI Provider Adapter
OpenAI 提供商适配器 - 实现统一接口
"""

import time
from typing import Optional, Dict, Any, List, Generator

from neurova.core.logger import get_logger
from neurova.llm.interfaces.provider_interface import (
    LLMAbstractProvider,
    ProviderConfig,
    Message,
    CallResult,
    ProviderType,
)
from neurova.llm.sandbox.security_sandbox import SecuritySandbox

logger = get_logger(__name__)


class OpenAIAdapter(LLMAbstractProvider):
    """
    OpenAI provider adapter
    
    Implements the unified LLM interface for OpenAI API
    """
    
    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        self._sandbox = SecuritySandbox(config)
        
        # Price tables (USD per 1K tokens)
        self.price_tables = {
            "gpt-4o": {"input": 0.0025, "output": 0.01},
            "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
            "gpt-4-turbo": {"input": 0.01, "output": 0.03},
            "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
        }
        
        logger.info(f"OpenAIAdapter initialized for {config.model_name}")
    
    @property
    def provider_type(self) -> ProviderType:
        return ProviderType.OPENAI
    
    async def call(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> CallResult:
        """Execute OpenAI API call with sandbox protection"""
        start_time = time.time()
        
        # Validate request in sandbox
        estimated_tokens = self._estimate_message_tokens(messages)
        is_valid, reason = self._sandbox.validate_request(
            messages=messages,
            requested_tokens=estimated_tokens + (max_tokens or 1000),
            tools_to_use=[],
        )
        
        if not is_valid:
            raise ValueError(f"Sandbox validation failed: {reason}")
        
        try:
            # Acquire resource slot
            async with self._sandbox.acquire_resource():
                # Make API call (mock implementation)
                result = await self._execute_openai_call(
                    messages=messages,
                    temperature=temperature or self.config.temperature,
                    max_tokens=max_tokens or self.config.max_tokens_per_call,
                )
                
                # Update usage
                self._sandbox.update_usage(
                    prompt_tokens=result.usage["prompt_tokens"],
                    completion_tokens=result.usage["completion_tokens"],
                )
                
                self._call_count += 1
                
                return result
                
        except Exception as e:
            self._last_error = str(e)
            logger.error(f"OpenAI call failed: {e}")
            raise
    
    async def stream_call(
        self,
        messages: List[Message],
        temperature: Optional[float] = None,
    ) -> Generator[str, None, None]:
        """Stream OpenAI responses"""
        # Implement streaming logic
        pass
    
    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Estimate cost based on token counts"""
        price_map = self.price_tables.get(
            self.config.model_name,
            {"input": 0, "output": 0}
        )
        
        cost = (
            input_tokens * price_map["input"] / 1000 +
            output_tokens * price_map["output"] / 1000
        )
        
        return round(cost, 6)
    
    async def _execute_openai_call(
        self,
        messages: List[Message],
        temperature: float,
        max_tokens: int,
    ) -> CallResult:
        """Execute actual OpenAI API call"""
        # Mock implementation - replace with real API call
        
        # Convert messages to OpenAI format
        openai_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in messages
        ]
        
        # Simulate response
        usage = {
            "prompt_tokens": sum(len(msg.content.split()) for msg in messages),
            "completion_tokens": max_tokens,
            "total_tokens": 0,
        }
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
        
        latency = time.time() - getattr(self, '_call_start_time', time.time())
        
        return CallResult(
            content="Mock response from OpenAI",
            usage=usage,
            model=self.config.model_name,
            finish_reason="stop",
            latency_seconds=latency,
            cost_usd=self.estimate_cost(usage["prompt_tokens"], usage["completion_tokens"]),
        )
    
    def _estimate_message_tokens(self, messages: List[Message]) -> int:
        """估算消息 token 数：走全仓唯一尺子。"""
        from neurova.context.token_estimator import estimate_tokens

        total = sum(estimate_tokens(str(msg.content)) for msg in messages)
        return max(1, total)


# Factory function for creating adapters
def create_openai_adapter(config: ProviderConfig) -> OpenAIAdapter:
    """Factory function to create OpenAI adapter"""
    return OpenAIAdapter(config)
