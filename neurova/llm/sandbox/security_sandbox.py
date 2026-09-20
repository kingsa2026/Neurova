"""
Neurova LLM Security Sandbox
LLM 调用安全沙箱 - 资源隔离和限制
Neurova Style: Multi-layer security with resource quotas
"""

import time
import asyncio
import threading
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
import traceback

from neurova.core.logger import get_logger
from neurova.llm.interfaces.provider_interface import (
    Message,
    CallResult,
    ProviderConfig,
)

logger = get_logger(__name__)


@dataclass
class ResourceQuota:
    """Resource quota for sandbox"""
    max_tokens_per_call: int = 8192
    max_tokens_per_hour: int = 100000
    max_requests_per_minute: int = 60
    max_concurrent_calls: int = 5
    max_memory_mb: int = 512
    allowed_tools: List[str] = field(default_factory=list)  # Empty = all allowed


@dataclass
class QuotaUsage:
    """Track quota usage"""
    tokens_used_this_hour: int = 0
    requests_this_minute: int = 0
    concurrent_calls: int = 0
    memory_used_mb: int = 0
    last_reset_time: float = field(default_factory=time.time)


class SecuritySandbox:
    """
    Security sandbox for LLM calls
    
    Provides multiple layers of protection:
    1. Rate limiting
    2. Token limits
    3. Resource quotas
    4. Tool access control
    5. Memory isolation
    """
    
    def __init__(self, config: ProviderConfig, quota: Optional[ResourceQuota] = None):
        self.config = config
        self.quota = quota or ResourceQuota()
        self.usage = QuotaUsage()
        
        # Thread safety
        self._lock = threading.RLock()
        self._semaphore = threading.Semaphore(self.quota.max_concurrent_calls)
        
        # Rate limiting state
        self._request_timestamps: List[float] = []
        
        logger.info(
            f"SecuritySandbox initialized for {config.model_name} - "
            f"max_tokens={self.quota.max_tokens_per_call}, "
            f"rate_limit={self.quota.rate_limit_requests_per_minute}/min"
        )
    
    @asynccontextmanager
    async def acquire_resource(self):
        """Acquire resource slot (concurrency limit)"""
        acquired = self._semaphore.acquire(blocking=True, timeout=self.config.timeout_seconds)
        
        if not acquired:
            raise TimeoutError(
                f"Failed to acquire resource slot after "
                f"{self.config.timeout_seconds}s"
            )
        
        try:
            with self._lock:
                self.usage.concurrent_calls += 1
            
            yield
            
        finally:
            with self._lock:
                self.usage.concurrent_calls -= 1
            self._semaphore.release()
    
    def check_rate_limit(self) -> bool:
        """Check if request is within rate limit"""
        with self._lock:
            now = time.time()
            
            # Remove old timestamps (> 1 minute ago)
            self._request_timestamps = [
                ts for ts in self._request_timestamps
                if now - ts < 60.0
            ]
            
            # Check limit
            if len(self._request_timestamps) >= self.quota.max_requests_per_minute:
                return False
            
            # Record this request
            self._request_timestamps.append(now)
            self.usage.requests_this_minute += 1
            
            return True
    
    def check_token_limit(self, prompt_tokens: int, completion_tokens: int) -> bool:
        """Check if token usage is within limits"""
        with self._lock:
            # Per-call limit
            total_tokens = prompt_tokens + completion_tokens
            if total_tokens > self.quota.max_tokens_per_call:
                logger.warning(
                    f"Token limit exceeded: {total_tokens} > {self.quota.max_tokens_per_call}"
                )
                return False
            
            # Per-hour limit
            if (self.usage.tokens_used_this_hour + total_tokens > 
                self.quota.max_tokens_per_hour):
                logger.warning(
                    f"Hourly token limit exceeded: "
                    f"{self.usage.tokens_used_this_hour + total_tokens} > "
                    f"{self.quota.max_tokens_per_hour}"
                )
                return False
            
            return True
    
    def update_usage(self, prompt_tokens: int, completion_tokens: int):
        """Update token usage counters"""
        with self._lock:
            total_tokens = prompt_tokens + completion_tokens
            self.usage.tokens_used_this_hour += total_tokens
            
            # Reset hourly counter if needed
            if time.time() - self.usage.last_reset_time > 3600:
                logger.info("Resetting hourly token counter")
                self.usage.tokens_used_this_hour = total_tokens
                self.usage.requests_this_minute = 0
                self.usage.last_reset_time = time.time()
    
    def check_tool_access(self, tool_name: str) -> bool:
        """Check if tool is allowed"""
        if not self.quota.allowed_tools:
            return True  # Empty list = all tools allowed
        
        return tool_name in self.quota.allowed_tools
    
    def estimate_memory_usage(self, tokens: int) -> int:
        """Estimate memory usage in MB (rough estimate: 0.5KB per token)"""
        return max(1, tokens * 0.0005)  # Convert to MB
    
    def validate_request(
        self,
        messages: List[Message],
        requested_tokens: int,
        tools_to_use: List[str],
    ) -> tuple[bool, str]:
        """
        Validate entire request before execution
        
        Returns:
            (is_valid, reason)
        """
        # Check rate limit
        if not self.check_rate_limit():
            return False, "Rate limit exceeded"
        
        # Check token limit
        if not self.check_token_limit(requested_tokens, requested_tokens):
            return False, "Token limit exceeded"
        
        # Check tool access
        for tool in tools_to_use:
            if not self.check_tool_access(tool):
                return False, f"Tool '{tool}' not allowed"
        
        # Estimate memory
        estimated_memory = self.estimate_memory_usage(requested_tokens * 2)
        if estimated_memory > self.quota.max_memory_mb:
            return False, "Memory quota exceeded"
        
        return True, "OK"


class SandboxManager:
    """
    Manage multiple sandboxes for different providers/agents
    
    Singleton pattern for global state management
    """
    
    _instance = None
    _lock = threading.RLock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._sandboxes: Dict[str, SecuritySandbox] = {}
        self._default_quota = ResourceQuota()
        
        logger.info("SandboxManager initialized")
        self._initialized = True
    
    def get_sandbox(
        self,
        provider_id: str,
        config: ProviderConfig,
        quota: Optional[ResourceQuota] = None,
    ) -> SecuritySandbox:
        """Get or create sandbox for provider"""
        key = f"{provider_id}:{config.model_name}"
        
        with self._lock:
            if key not in self._sandboxes:
                sandbox_quota = quota or self._default_quota
                self._sandboxes[key] = SecuritySandbox(config, sandbox_quota)
                logger.info(f"Created sandbox for {key}")
            
            return self._sandboxes[key]
    
    def remove_sandbox(self, provider_id: str, model_name: str) -> None:
        """Remove sandbox"""
        key = f"{provider_id}:{model_name}"
        
        with self._lock:
            if key in self._sandboxes:
                del self._sandboxes[key]
                logger.info(f"Removed sandbox for {key}")
    
    def get_all_stats(self) -> Dict[str, Any]:
        """Get stats for all sandboxes"""
        stats = {}
        
        with self._lock:
            for key, sandbox in self._sandboxes.items():
                stats[key] = {
                    "quota": {
                        "max_tokens_per_call": sandbox.quota.max_tokens_per_call,
                        "max_tokens_per_hour": sandbox.quota.max_tokens_per_hour,
                        "rate_limit": sandbox.quota.max_requests_per_minute,
                    },
                    "usage": {
                        "tokens_this_hour": sandbox.usage.tokens_used_this_hour,
                        "requests_this_minute": sandbox.usage.requests_this_minute,
                        "concurrent_calls": sandbox.usage.concurrent_calls,
                    },
                }
        
        return stats


# Global instance management
_sandbox_manager_instance: Optional[SandboxManager] = None
_sandbox_manager_lock = threading.Lock()


def get_sandbox_manager() -> SandboxManager:
    """Get global SandboxManager instance"""
    global _sandbox_manager_instance
    
    if _sandbox_manager_instance is None:
        with _sandbox_manager_lock:
            if _sandbox_manager_instance is None:
                _sandbox_manager_instance = SandboxManager()
    
    return _sandbox_manager_instance


def reset_sandbox_manager() -> None:
    """Reset SandboxManager instance (for testing)"""
    global _sandbox_manager_instance
    _sandbox_manager_instance = None
