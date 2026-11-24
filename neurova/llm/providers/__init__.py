"""
Provider 系统

统一的 LLM Provider 接口和实现

启动性能根修（2026-11-24）：包 __init__ 原先顶层 import 全部 provider
实现，连带 langchain-anthropic / anthropic / langchain-ollama 等重依赖链
（首载实测 ~3.8s）。只取本包轻量子模块（types/secret_store_clean/
rate_limiter）的消费方（provider_manager、multi_model_client）也因包
__init__ 先执行而被迫加载全部适配器，这段成本落在每次后端启动的关键
路径上。改为 PEP 562 惰性属性：provider 类仅在首次属性访问（真正构造
客户端时）才加载；`from neurova.llm.providers import X`、`import
neurova.llm.providers.anthropic_provider` 两种用法契约均保持。
"""

import importlib

# 惰性导出名 → (模块路径, 属性名)。轻量子模块（base/types）与重实现
# 同规则处理，避免两套心智。
_LAZY_PROVIDER_ATTRS = {
    "AnthropicProvider": ("neurova.llm.providers.anthropic_provider", "AnthropicProvider"),
    "BaseProvider": ("neurova.llm.providers.base", "BaseProvider"),
    "ConnectionResult": ("neurova.llm.providers.types", "ConnectionResult"),
    "GeminiProvider": ("neurova.llm.providers.gemini_provider", "GeminiProvider"),
    "OllamaProvider": ("neurova.llm.providers.ollama_provider", "OllamaProvider"),
    "OpenAIProvider": ("neurova.llm.providers.openai_provider", "OpenAIProvider"),
    "OpenCodeProvider": ("neurova.llm.providers.opencode_provider", "OpenCodeProvider"),
    "OpenRouterProvider": ("neurova.llm.providers.openrouter_provider", "OpenRouterProvider"),
}

# 对外公开面写在一处：这些名字真有人 `from neurova.llm.providers import X`
# 取走（`neurova/llm/provider_manager.py` 一次取六只），此前只能靠"文件顶层
# 恰好绑了它们"来供给——契约没写，下一次"清理门面"就可能把真在用的名字
# 当零消费者删掉（§6-220）。
__all__ = list(_LAZY_PROVIDER_ATTRS)


def __getattr__(name: str):
    target = _LAZY_PROVIDER_ATTRS.get(name)
    if target is None:
        raise AttributeError(
            f"module 'neurova.llm.providers' has no attribute {name!r}"
        )
    module_path, attr = target
    value = getattr(importlib.import_module(module_path), attr)
    globals()[name] = value  # 首访后固化为真属性，后续走常规查找
    return value


def __dir__() -> list:
    return sorted(set(globals()) | set(_LAZY_PROVIDER_ATTRS))
