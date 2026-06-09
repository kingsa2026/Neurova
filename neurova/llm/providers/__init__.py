"""
Provider 系统

统一的 LLM Provider 接口和实现
"""

import logging

_logger = logging.getLogger(__name__)

try:
    from neurova.llm.providers.anthropic_provider import AnthropicProvider
except ImportError as _e:
    _logger.debug(f"AnthropicProvider 未可用: {_e}")
    AnthropicProvider = None

try:
    from neurova.llm.providers.base import BaseProvider
except ImportError as _e:
    _logger.debug(f"BaseProvider 未可用: {_e}")
    BaseProvider = None

try:
    from neurova.llm.providers.types import ConnectionResult
except ImportError as _e:
    _logger.debug(f"ConnectionResult 未可用: {_e}")
    ConnectionResult = None

try:
    from neurova.llm.providers.gemini_provider import GeminiProvider
except ImportError as _e:
    _logger.debug(f"GeminiProvider 未可用: {_e}")
    GeminiProvider = None

try:
    from neurova.llm.providers.ollama_provider import OllamaProvider
except ImportError as _e:
    _logger.debug(f"OllamaProvider 未可用: {_e}")
    OllamaProvider = None

try:
    from neurova.llm.providers.openai_provider import OpenAIProvider
except ImportError as _e:
    _logger.debug(f"OpenAIProvider 未可用: {_e}")
    OpenAIProvider = None

try:
    from neurova.llm.providers.openrouter_provider import OpenRouterProvider
except ImportError as _e:
    _logger.debug(f"OpenRouterProvider 未可用: {_e}")
    OpenRouterProvider = None

# llm imports
try:
    import neurova.llm.providers.anthropic_provider
except ImportError as _e:
    _logger.debug(f"llm.providers.anthropic_provider 模块未可用: {_e}")

try:
    import neurova.llm.providers.base
except ImportError as _e:
    _logger.debug(f"llm.providers.base 模块未可用: {_e}")

try:
    import neurova.llm.providers.capability_cache
except ImportError as _e:
    _logger.debug(f"llm.providers.capability_cache 模块未可用: {_e}")

try:
    import neurova.llm.providers.gemini_provider
except ImportError as _e:
    _logger.debug(f"llm.providers.gemini_provider 模块未可用: {_e}")

try:
    import neurova.llm.providers.lm_studio_provider
except ImportError as _e:
    _logger.debug(f"llm.providers.lm_studio_provider 模块未可用: {_e}")

try:
    import neurova.llm.providers.ollama_provider
except ImportError as _e:
    _logger.debug(f"llm.providers.ollama_provider 模块未可用: {_e}")

try:
    import neurova.llm.providers.openai_provider
except ImportError as _e:
    _logger.debug(f"llm.providers.openai_provider 模块未可用: {_e}")

try:
    import neurova.llm.providers.openrouter_provider
except ImportError as _e:
    _logger.debug(f"llm.providers.openrouter_provider 模块未可用: {_e}")

try:
    import neurova.llm.providers.rate_limiter
except ImportError as _e:
    _logger.debug(f"llm.providers.rate_limiter 模块未可用: {_e}")

try:
    import neurova.llm.providers.secret_store
except ImportError as _e:
    _logger.debug(f"llm.providers.secret_store 模块未可用: {_e}")

try:
    import neurova.llm.providers.types
except ImportError as _e:
    _logger.debug(f"llm.providers.types 模块未可用: {_e}")