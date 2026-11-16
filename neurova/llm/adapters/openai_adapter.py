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
        """流式未实现：显式点名失败，不以 `pass` 静默返回 None。

        空桩时代调用方迭代返回值会在别处炸 `TypeError: NoneType is not
        iterable`——报错点与根因无关（S5 移交 R6 诚实化）。真流式
        （aiohttp SSE）属新建能力，另立批次；grep 复核全仓无生产消费方
        （2026-11-17：基类 @abstractmethod 占位之外仅桩测试）。
        """
        raise NotImplementedError(
            "OpenAIAdapter.stream_call 未实现流式输出（仅支持非流式 call）；"
            "实现前调用在此显式失败，不再以 None 拖到迭代处炸 TypeError"
        )
    
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
        """执行真实 OpenAI 兼容 chat 调用（P1-10：替代 "Mock response" 假实现）。

        aiohttp 异步客户端（与 providers/openai_provider 同款软依赖）；
        凭据缺失/依赖缺失/HTTP >= 400 一律以异常诚实暴露，不伪造响应。
        """
        if not self.config.api_key:
            raise ValueError(
                "OpenAI API key 未配置（ProviderConfig.api_key 为空），拒绝伪造响应"
            )
        try:
            import aiohttp
        except ImportError as e:
            raise RuntimeError("aiohttp 未安装，无法执行真实 OpenAI 调用") from e

        base_url = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        payload = {
            "model": self.config.model_name,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config.api_key}",
        }
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        started = time.time()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=timeout,
            ) as response:
                body = await response.json()
                if response.status >= 400:
                    detail = ""
                    if isinstance(body, dict):
                        detail = str((body.get("error") or {}).get("message", body))
                    raise RuntimeError(
                        f"OpenAI 调用失败: HTTP {response.status}: {detail}"
                    )
        latency = time.time() - started

        choices = body.get("choices") or [{}]
        message = choices[0].get("message") or {}
        usage = body.get("usage") or {}
        # usage 缺失时回落 `_estimate_message_tokens`（沙箱校验的同一把尺子）
        prompt_tokens = int(usage.get("prompt_tokens") or self._estimate_message_tokens(messages))
        completion_tokens = int(usage.get("completion_tokens") or 0)
        return CallResult(
            content=str(message.get("content") or message.get("reasoning_content") or ""),
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": int(usage.get("total_tokens") or (prompt_tokens + completion_tokens)),
            },
            model=str(body.get("model") or self.config.model_name),
            finish_reason=str(choices[0].get("finish_reason") or "stop"),
            latency_seconds=latency,
            cost_usd=self.estimate_cost(prompt_tokens, completion_tokens),
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
