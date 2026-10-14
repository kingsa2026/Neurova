"""
Provider 系统

统一的 LLM Provider 接口和实现
"""


from neurova.llm.providers.anthropic_provider import AnthropicProvider

from neurova.llm.providers.base import BaseProvider

from neurova.llm.providers.types import ConnectionResult

from neurova.llm.providers.gemini_provider import GeminiProvider

from neurova.llm.providers.ollama_provider import OllamaProvider

from neurova.llm.providers.openai_provider import OpenAIProvider

from neurova.llm.providers.opencode_provider import OpenCodeProvider

from neurova.llm.providers.openrouter_provider import OpenRouterProvider

# 对外公开面写在一处：这些名字真有人 `from neurova.llm.providers import X` 取走
# （`neurova/llm/provider_manager.py:2036` 一次取六只），此前只能靠"文件顶层恰好绑了它们"
# 来供给——契约没写，下一次"清理门面"就可能把真在用的名字当零消费者删掉（§6-220）。
__all__ = [
    "AnthropicProvider",
    "BaseProvider",
    "ConnectionResult",
    "GeminiProvider",
    "OllamaProvider",
    "OpenAIProvider",
    "OpenCodeProvider",
    "OpenRouterProvider",
]
