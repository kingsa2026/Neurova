from __future__ import annotations

"""
上下文格式转换器 - Context Converter

负责将上下文转换为不同模型的格式（OpenAI、Anthropic 等）。
"""

import logging
from typing import Any, Dict

from neurova.context.pool_models import ContextInput, ContextSource

logger = logging.getLogger(__name__)


class ContextConverter:
    """上下文格式转换器"""

    def to_openai_format(self, context: ContextInput) -> Dict[str, Any]:
        role = self._get_role_for_source(context.source)

        if context.source == ContextSource.MULTIMODAL and context.metadata.get("media_type"):
            return self._convert_multimodal_to_openai(context, role)

        return {"role": role, "content": context.content}

    def to_anthropic_format(self, context: ContextInput) -> Dict[str, Any]:
        role = self._get_role_for_source(context.source)

        if context.source == ContextSource.MULTIMODAL and context.metadata.get("media_type"):
            return self._convert_multimodal_to_anthropic(context, role)

        return {"role": role, "content": [{"type": "text", "text": context.content}]}

    def convert_for_model(self, context: ContextInput, model_name: str) -> Dict[str, Any]:
        if self._is_anthropic_model(model_name):
            return self.to_anthropic_format(context)
        else:
            return self.to_openai_format(context)

    def _get_role_for_source(self, source: ContextSource) -> str:
        role_mapping = {
            ContextSource.SYSTEM_INSTRUCTION: "system",
            ContextSource.DEVELOPER_INSTRUCTION: "system",
            ContextSource.MEMORY: "system",
            ContextSource.CONVERSATION: "user",
            ContextSource.EXPERIENCE: "system",
            ContextSource.EMOTION: "system",
            ContextSource.REFLECTION: "system",
            ContextSource.TOOL_CALL: "tool",
            ContextSource.MULTIMODAL: "user",
            ContextSource.USER_INPUT: "user",
        }
        return role_mapping.get(source, "user")

    def _is_anthropic_model(self, model_name: str) -> bool:
        return "claude" in model_name.lower() or "anthropic" in model_name.lower()

    def _convert_multimodal_to_openai(self, context: ContextInput, role: str) -> Dict[str, Any]:
        content = []

        if context.content:
            content.append({"type": "text", "text": context.content})

        media_type = context.metadata.get("media_type")
        media_url = context.metadata.get("media_url")

        if media_type == "image" and media_url:
            content.append({"type": "image_url", "image_url": {"url": media_url}})
        elif media_type == "audio" and media_url:
            content.append({"type": "text", "text": f"[音频文件: {context.metadata.get('filename', 'unknown')}]"})
        elif media_type == "video" and media_url:
            content.append({"type": "text", "text": f"[视频文件: {context.metadata.get('filename', 'unknown')}]"})

        return {"role": role, "content": content}

    def _convert_multimodal_to_anthropic(self, context: ContextInput, role: str) -> Dict[str, Any]:
        content = []

        if context.content:
            content.append({"type": "text", "text": context.content})

        media_type = context.metadata.get("media_type")
        media_url = context.metadata.get("media_url")

        if media_type == "image" and media_url:
            content.append({"type": "image", "source": {"type": "url", "url": media_url}})
        elif media_type == "audio" and media_url:
            content.append({"type": "text", "text": f"[音频文件: {context.metadata.get('filename', 'unknown')}]"})
        elif media_type == "video" and media_url:
            content.append({"type": "text", "text": f"[视频文件: {context.metadata.get('filename', 'unknown')}]"})

        return {"role": role, "content": content}
