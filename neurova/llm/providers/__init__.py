"""
Provider 系统

统一的 LLM Provider 接口和实现
"""

from neurova.core.logger import get_logger
_logger = get_logger(__name__)

try:
    from neurova.llm.providers.anthropic_provider import AnthropicProvider
except ImportError as _e:
    _logger.debug("AnthropicProvider 未可用: %s", _e)
    AnthropicProvider = None

try:
    from neurova.llm.providers.base import BaseProvider
except ImportError as _e:
    _logger.debug("BaseProvider 未可用: %s", _e)
    BaseProvider = None

try:
    from neurova.llm.providers.types import ConnectionResult
except ImportError as _e:
    _logger.debug("ConnectionResult 未可用: %s", _e)
    ConnectionResult = None

try:
    from neurova.llm.providers.gemini_provider import GeminiProvider
except ImportError as _e:
    _logger.debug("GeminiProvider 未可用: %s", _e)
    GeminiProvider = None

try:
    from neurova.llm.providers.ollama_provider import OllamaProvider
except ImportError as _e:
    _logger.debug("OllamaProvider 未可用: %s", _e)
    OllamaProvider = None

try:
    from neurova.llm.providers.openai_provider import OpenAIProvider
except ImportError as _e:
    _logger.debug("OpenAIProvider 未可用: %s", _e)
    OpenAIProvider = None

try:
    from neurova.llm.providers.opencode_provider import OpenCodeProvider
except ImportError as _e:
    _logger.debug("OpenCodeProvider 未可用: %s", _e)
    OpenCodeProvider = None

try:
    from neurova.llm.providers.openrouter_provider import OpenRouterProvider
except ImportError as _e:
    _logger.debug("OpenRouterProvider 未可用: %s", _e)
    OpenRouterProvider = None
