"""统一模型契约层（Dify §2.5 六型统一契约对标）。

- entities：消息族/结果族/结构化输出（OpenAI dict 双向适配器）
- schema：参数与能力上下文（三层既有目录为事实源，schema 驱动过滤）
"""

from neurova.llm.model_runtime.entities import (
    AssistantPromptMessage,
    EmbeddingUsage,
    ImagePromptMessageContent,
    LLMResult,
    LLMResultChunk,
    LLMResultChunkDelta,
    LLMStructuredOutput,
    LLMUsage,
    PromptMessage,
    PromptMessageTool,
    RerankDocument,
    RerankResult,
    SystemPromptMessage,
    TextEmbeddingResult,
    TextPromptMessageContent,
    ToolPromptMessage,
    UserPromptMessage,
    prompt_messages_from_openai,
    prompt_messages_to_openai,
)
from neurova.llm.model_runtime.schema import (
    MODEL_TYPE_CAPABILITIES,
    ModelSchema,
    ParameterRule,
    get_model_schema,
    model_types_for_capabilities,
)

__all__ = [
    # 消息族
    "PromptMessage",
    "SystemPromptMessage",
    "UserPromptMessage",
    "AssistantPromptMessage",
    "ToolPromptMessage",
    "PromptMessageTool",
    "TextPromptMessageContent",
    "ImagePromptMessageContent",
    "prompt_messages_from_openai",
    "prompt_messages_to_openai",
    # 结果族
    "LLMUsage",
    "LLMResult",
    "LLMResultChunk",
    "LLMResultChunkDelta",
    "EmbeddingUsage",
    "TextEmbeddingResult",
    "RerankDocument",
    "RerankResult",
    # 结构化输出
    "LLMStructuredOutput",
    # schema
    "ModelSchema",
    "ParameterRule",
    "get_model_schema",
    "MODEL_TYPE_CAPABILITIES",
    "model_types_for_capabilities",
]
