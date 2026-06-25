"""
模型能力探测模块

探测 LLM 模型的能力（流式输出、函数调用、多模态等）
"""

from neurova.core.logger import get_logger
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = get_logger(__name__)


class ModelCapability(Enum):
    """模型能力枚举"""

    STREAMING = "streaming"
    FUNCTION_CALLING = "function_calling"
    VISION = "vision"
    JSON_MODE = "json_mode"
    CODE_INTERPRETER = "code_interpreter"
    PARALLEL_FUNCTION_CALLING = "parallel_function_calling"
    SYSTEM_MESSAGE = "system_message"
    MULTI_TURN = "multi_turn"


@dataclass
class CapabilityResult:
    """能力检测结果"""

    model_name: str
    provider: str
    capabilities: Dict[ModelCapability, bool] = field(default_factory=dict)
    response_time_ms: float = 0.0
    error: Optional[str] = None
    probed_at: float = field(default_factory=time.time)

    def has_capability(self, cap: ModelCapability) -> bool:
        """检查是否具有指定能力"""
        return self.capabilities.get(cap, False)

    def get_supported_capabilities(self) -> List[ModelCapability]:
        """获取所有支持的能力列表"""
        return [cap for cap, supported in self.capabilities.items() if supported]

    def get_unsupported_capabilities(self) -> List[ModelCapability]:
        """获取所有不支持的能力列表"""
        return [cap for cap, supported in self.capabilities.items() if not supported]

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典"""
        return {
            "model_name": self.model_name,
            "provider": self.provider,
            "capabilities": {cap.value: supported for cap, supported in self.capabilities.items()},
            "response_time_ms": self.response_time_ms,
            "error": self.error,
            "probed_at": self.probed_at,
            "supported_count": len(self.get_supported_capabilities()),
            "unsupported_count": len(self.get_unsupported_capabilities()),
        }


class CapabilityDetector:
    """模型能力探测器"""

    def __init__(self, timeout: float = 30.0):
        """
        初始化探测器

        Args:
            timeout: 探测超时时间（秒）
        """
        self._timeout = timeout
        self._probe_prompts = {
            ModelCapability.STREAMING: "Say 'streaming test' in one word.",
            ModelCapability.FUNCTION_CALLING: "What is the weather in Tokyo?",
            ModelCapability.VISION: "Describe this image.",
            ModelCapability.JSON_MODE: 'Return {"status": "ok"} as JSON.',
            ModelCapability.CODE_INTERPRETER: "Calculate 2+2.",
            ModelCapability.PARALLEL_FUNCTION_CALLING: "Get weather for Tokyo and Paris.",
            ModelCapability.SYSTEM_MESSAGE: "Follow the system instruction.",
            ModelCapability.MULTI_TURN: "Continue our conversation.",
        }
        logger.info("CapabilityDetector initialized with timeout=%.1fs", timeout)

    async def probe(
        self,
        model_name: str,
        provider: str,
        llm_client: Any,
        capabilities_to_probe: Optional[List[ModelCapability]] = None,
    ) -> CapabilityResult:
        """
        探测模型能力

        Args:
            model_name: 模型名称
            provider: 提供商名称
            llm_client: LLM 客户端实例
            capabilities_to_probe: 要探测的能力列表，None 表示全部探测

        Returns:
            CapabilityResult 探测结果
        """
        start_time = time.time()

        if capabilities_to_probe is None:
            capabilities_to_probe = list(ModelCapability)

        capabilities = {}

        for cap in capabilities_to_probe:
            try:
                if cap == ModelCapability.STREAMING:
                    supported = await self._probe_streaming(llm_client, model_name)
                elif cap == ModelCapability.FUNCTION_CALLING:
                    supported = await self._probe_function_calling(llm_client, model_name)
                elif cap == ModelCapability.VISION:
                    supported = await self._probe_vision(llm_client, model_name)
                elif cap == ModelCapability.JSON_MODE:
                    supported = await self._probe_json_mode(llm_client, model_name)
                elif cap == ModelCapability.CODE_INTERPRETER:
                    supported = await self._probe_code_interpreter(llm_client, model_name)
                elif cap == ModelCapability.PARALLEL_FUNCTION_CALLING:
                    supported = await self._probe_parallel_function_calling(llm_client, model_name)
                elif cap == ModelCapability.SYSTEM_MESSAGE:
                    supported = await self._probe_system_message(llm_client, model_name)
                elif cap == ModelCapability.MULTI_TURN:
                    supported = await self._probe_multi_turn(llm_client, model_name)
                else:
                    supported = False

                capabilities[cap] = supported
                logger.debug("Probed %s for %s: %s", cap.value, model_name, supported)

            except Exception as e:
                logger.warning("Failed to probe %s for %s: %s", cap.value, model_name, str(e))
                capabilities[cap] = False

        elapsed_ms = (time.time() - start_time) * 1000

        result = CapabilityResult(
            model_name=model_name,
            provider=provider,
            capabilities=capabilities,
            response_time_ms=elapsed_ms,
        )

        logger.info(
            "Probe complete for %s/%s: %d/%d capabilities supported in %.1fms",
            provider,
            model_name,
            len(result.get_supported_capabilities()),
            len(capabilities_to_probe),
            elapsed_ms,
        )

        return result

    async def _probe_streaming(self, llm_client: Any, model_name: str) -> bool:
        """探测流式输出能力"""
        try:
            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": self._probe_prompts[ModelCapability.STREAMING]}],
                max_tokens=10,
                stream=True,
            )
            # 尝试读取第一个 chunk
            async for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    return True
            return False
        except Exception as e:
            logger.debug("Streaming probe failed: %s", str(e))
            return False

    async def _probe_function_calling(self, llm_client: Any, model_name: str) -> bool:
        """探测函数调用能力"""
        try:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather in a location",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string", "description": "The city name"},
                            },
                            "required": ["location"],
                        },
                    },
                }
            ]

            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": self._probe_prompts[ModelCapability.FUNCTION_CALLING]}],
                tools=tools,
                tool_choice="auto",
                max_tokens=100,
            )

            if response.choices and response.choices[0].message:
                message = response.choices[0].message
                return hasattr(message, "tool_calls") and message.tool_calls is not None
            return False
        except Exception as e:
            logger.debug("Function calling probe failed: %s", str(e))
            return False

    async def _probe_vision(self, llm_client: Any, model_name: str) -> bool:
        """探测视觉能力"""
        try:
            # 使用一个简单的 base64 图片进行测试
            test_image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="

            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": self._probe_prompts[ModelCapability.VISION]},
                            {"type": "image_url", "image_url": {"url": test_image}},
                        ],
                    }
                ],
                max_tokens=50,
            )

            return response.choices and response.choices[0].message and response.choices[0].message.content
        except Exception as e:
            logger.debug("Vision probe failed: %s", str(e))
            return False

    async def _probe_json_mode(self, llm_client: Any, model_name: str) -> bool:
        """探测 JSON 模式能力"""
        try:
            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": self._probe_prompts[ModelCapability.JSON_MODE]}],
                response_format={"type": "json_object"},
                max_tokens=50,
            )

            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content
                if content:
                    import json

                    try:
                        json.loads(content)
                        return True
                    except json.JSONDecodeError:
                        pass
            return False
        except Exception as e:
            logger.debug("JSON mode probe failed: %s", str(e))
            return False

    async def _probe_code_interpreter(self, llm_client: Any, model_name: str) -> bool:
        """探测代码解释器能力"""
        try:
            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": self._probe_prompts[ModelCapability.CODE_INTERPRETER]}],
                tools=[
                    {
                        "type": "function",
                        "function": {
                            "name": "execute_code",
                            "description": "Execute Python code",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "code": {"type": "string"},
                                },
                                "required": ["code"],
                            },
                        },
                    }
                ],
                max_tokens=100,
            )

            if response.choices and response.choices[0].message:
                message = response.choices[0].message
                return hasattr(message, "tool_calls") and message.tool_calls is not None
            return False
        except Exception as e:
            logger.debug("Code interpreter probe failed: %s", str(e))
            return False

    async def _probe_parallel_function_calling(self, llm_client: Any, model_name: str) -> bool:
        """探测并行函数调用能力"""
        try:
            tools = [
                {
                    "type": "function",
                    "function": {
                        "name": "get_weather",
                        "description": "Get the current weather in a location",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "location": {"type": "string"},
                            },
                            "required": ["location"],
                        },
                    },
                }
            ]

            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": self._probe_prompts[ModelCapability.PARALLEL_FUNCTION_CALLING]}],
                tools=tools,
                tool_choice="auto",
                max_tokens=200,
            )

            if response.choices and response.choices[0].message:
                message = response.choices[0].message
                if hasattr(message, "tool_calls") and message.tool_calls:
                    return len(message.tool_calls) > 1
            return False
        except Exception as e:
            logger.debug("Parallel function calling probe failed: %s", str(e))
            return False

    async def _probe_system_message(self, llm_client: Any, model_name: str) -> bool:
        """探测系统消息能力"""
        try:
            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "system", "content": "You are a helpful assistant. Always respond with 'SYSTEM_TEST_OK'."},
                    {"role": "user", "content": self._probe_prompts[ModelCapability.SYSTEM_MESSAGE]},
                ],
                max_tokens=50,
            )

            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content or ""
                return "SYSTEM_TEST_OK" in content
            return False
        except Exception as e:
            logger.debug("System message probe failed: %s", str(e))
            return False

    async def _probe_multi_turn(self, llm_client: Any, model_name: str) -> bool:
        """探测多轮对话能力"""
        try:
            messages = [
                {"role": "user", "content": "My name is Alice."},
                {"role": "assistant", "content": "Hello Alice! Nice to meet you."},
                {"role": "user", "content": "What is my name?"},
            ]

            response = await llm_client.chat.completions.create(
                model=model_name,
                messages=messages,
                max_tokens=50,
            )

            if response.choices and response.choices[0].message:
                content = response.choices[0].message.content or ""
                return "Alice" in content
            return False
        except Exception as e:
            logger.debug("Multi-turn probe failed: %s", str(e))
            return False

    def _get_model_info(self, model_name: str) -> Dict[str, Any]:
        """获取模型信息（从模型名推断）"""
        info = {
            "name": model_name,
            "family": "unknown",
            "size": "unknown",
        }

        name_lower = model_name.lower()

        # 推断模型家族
        if "gpt" in name_lower:
            info["family"] = "gpt"
        elif "claude" in name_lower:
            info["family"] = "claude"
        elif "gemini" in name_lower:
            info["family"] = "gemini"
        elif "qwen" in name_lower:
            info["family"] = "qwen"
        elif "deepseek" in name_lower:
            info["family"] = "deepseek"
        elif "llama" in name_lower:
            info["family"] = "llama"
        elif "mistral" in name_lower:
            info["family"] = "mistral"

        # 推断模型大小
        if "mini" in name_lower or "small" in name_lower:
            info["size"] = "small"
        elif "large" in name_lower or "max" in name_lower:
            info["size"] = "large"
        elif "turbo" in name_lower or "fast" in name_lower:
            info["size"] = "fast"

        return info


class CapabilityCache:
    """能力缓存管理器"""

    def __init__(self, ttl: float = 3600.0, max_size: int = 1000):
        """
        初始化缓存

        Args:
            ttl: 缓存过期时间（秒）
            max_size: 最大缓存条目数
        """
        self._cache: Dict[str, CapabilityResult] = {}
        self._ttl = ttl
        self._max_size = max_size
        self._lock = threading.RLock()
        logger.info("CapabilityCache initialized with ttl=%.1fs, max_size=%d", ttl, max_size)

    def get(self, model_name: str, provider: str) -> Optional[CapabilityResult]:
        """
        获取缓存的能力结果

        Args:
            model_name: 模型名称
            provider: 提供商名称

        Returns:
            CapabilityResult 或 None（如果未命中或过期）
        """
        key = f"{provider}:{model_name}"

        with self._lock:
            result = self._cache.get(key)
            if result is None:
                return None

            # 检查是否过期
            if time.time() - result.probed_at > self._ttl:
                del self._cache[key]
                logger.debug("Cache expired for %s", key)
                return None

            logger.debug("Cache hit for %s", key)
            return result

    def set(self, result: CapabilityResult) -> None:
        """
        缓存能力结果

        Args:
            result: 能力检测结果
        """
        key = f"{result.provider}:{result.model_name}"

        with self._lock:
            # 如果缓存已满，删除最旧的条目
            if len(self._cache) >= self._max_size:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].probed_at)
                del self._cache[oldest_key]
                logger.debug("Cache evicted oldest entry: %s", oldest_key)

            self._cache[key] = result
            logger.debug("Cached result for %s", key)

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()
            logger.info("Cache cleared")

    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            now = time.time()
            valid_count = sum(1 for r in self._cache.values() if now - r.probed_at <= self._ttl)
            expired_count = len(self._cache) - valid_count

            return {
                "total_entries": len(self._cache),
                "valid_entries": valid_count,
                "expired_entries": expired_count,
                "max_size": self._max_size,
                "ttl_seconds": self._ttl,
            }


# 全局单例
_detector_instance: Optional[CapabilityDetector] = None
_cache_instance: Optional[CapabilityCache] = None
_detector_lock = threading.Lock()
_cache_lock = threading.Lock()


def get_capability_detector(timeout: float = 30.0) -> CapabilityDetector:
    """获取全局 CapabilityDetector 实例"""
    global _detector_instance
    if _detector_instance is None:
        with _detector_lock:
            if _detector_instance is None:
                _detector_instance = CapabilityDetector(timeout=timeout)
    return _detector_instance


def get_capability_cache(ttl: float = 3600.0, max_size: int = 1000) -> CapabilityCache:
    """获取全局 CapabilityCache 实例"""
    global _cache_instance
    if _cache_instance is None:
        with _cache_lock:
            if _cache_instance is None:
                _cache_instance = CapabilityCache(ttl=ttl, max_size=max_size)
    return _cache_instance


def reset_capability_detector() -> None:
    """重置全局 CapabilityDetector 实例（用于测试）"""
    global _detector_instance
    with _detector_lock:
        _detector_instance = None


def reset_capability_cache() -> None:
    """重置全局 CapabilityCache 实例（用于测试）"""
    global _cache_instance
    with _cache_lock:
        _cache_instance = None


async def detect_capabilities(
    model_name: str,
    provider: str,
    llm_client: Any,
    use_cache: bool = True,
    timeout: float = 30.0,
) -> CapabilityResult:
    """
    探测模型能力（便捷函数）

    Args:
        model_name: 模型名称
        provider: 提供商名称
        llm_client: LLM 客户端实例
        use_cache: 是否使用缓存
        timeout: 探测超时时间（秒）

    Returns:
        CapabilityResult 探测结果
    """
    cache = get_capability_cache() if use_cache else None

    # 尝试从缓存获取
    if cache:
        cached = cache.get(model_name, provider)
        if cached is not None:
            logger.debug("Using cached capabilities for %s/%s", provider, model_name)
            return cached

    # 执行探测
    detector = get_capability_detector(timeout=timeout)
    result = await detector.probe(model_name, provider, llm_client)

    # 缓存结果
    if cache:
        cache.set(result)

    return result
