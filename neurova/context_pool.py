from __future__ import annotations

"""
上下文池 - Context Pool

提供上下文重组、精炼、转换能力，支持：
- 对话语义理解与重组
- 记忆检索结果整合
- 工具调用及结果处理
- 多模态能力转换
- 模型切换时的上下文适配
"""

import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)

class ContextSource(Enum):
    """上下文来源枚举"""
    SYSTEM_INSTRUCTION = "system_instruction"  # 系统指令
    DEVELOPER_INSTRUCTION = "developer_instruction"  # 开发者指令
    MEMORY = "memory"  # 记忆
    CONVERSATION = "conversation"  # 对话历史
    EXPERIENCE = "experience"  # 经验知识
    EMOTION = "emotion"  # 情感状态
    REFLECTION = "reflection"  # 反思日志
    TOOL_CALL = "tool_call"  # 工具调用
    MULTIMODAL = "multimodal"  # 多模态内容
    USER_INPUT = "user_input"  # 用户输入

@dataclass
class ContextInput:
    """上下文输入数据类"""
    source: ContextSource
    content: str
    priority: int = 50
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source": self.source.value,
            "content": self.content,
            "priority": self.priority,
            "metadata": self.metadata,
            "tokens": self.tokens
        }

class ContextCollector:
    """上下文收集器"""

    def __init__(self, max_tokens: int = 16000):
        """
        初始化收集器

        Args:
            max_tokens: 最大Token数量
        """
        self.max_tokens = max_tokens
        self._contexts: List[ContextInput] = []

    def add_context(self, context: ContextInput):
        """
        添加上下文

        Args:
            context: 上下文输入
        """
        # 估算Token数量
        if context.tokens == 0:
            context.tokens = ContextPoolUtils.estimate_tokens(context.content)

        self._contexts.append(context)

    def collect(self) -> List[ContextInput]:
        """
        收集并排序上下文

        Returns:
            按优先级排序的上下文列表
        """
        # 按优先级降序排序
        sorted_contexts = sorted(
            self._contexts,
            key=lambda x: (-x.priority, x.tokens)
        )

        # 应用Token预算
        return self._apply_token_budget(sorted_contexts)

    def collect_by_source(self, source: ContextSource) -> List[ContextInput]:
        """
        按来源收集上下文

        Args:
            source: 上下文来源

        Returns:
            指定来源的上下文列表
        """
        return [ctx for ctx in self._contexts if ctx.source == source]

    def _apply_token_budget(self, contexts: List[ContextInput]) -> List[ContextInput]:
        """
        应用Token预算

        Args:
            contexts: 排序后的上下文列表

        Returns:
            预算内的上下文列表
        """
        result = []
        total_tokens = 0

        for ctx in contexts:
            if total_tokens + ctx.tokens <= self.max_tokens:
                result.append(ctx)
                total_tokens += ctx.tokens
            else:
                # 尝试截断以适应预算
                remaining_tokens = self.max_tokens - total_tokens
                if remaining_tokens > 0:
                    # 按比例截断字符（1 token ≈ 1.5 字符 for Chinese）
                    char_limit = int(remaining_tokens * 1.5)
                    truncated_content = ctx.content[:char_limit]
                    truncated_ctx = ContextInput(
                        source=ctx.source,
                        content=truncated_content,
                        priority=ctx.priority,
                        metadata=ctx.metadata,
                        tokens=remaining_tokens
                    )
                    result.append(truncated_ctx)
                break

        return result

class ContextConverter:
    """上下文格式转换器"""

    def to_openai_format(self, context: ContextInput) -> Dict[str, Any]:
        """
        转换为 OpenAI 格式

        Args:
            context: 上下文输入

        Returns:
            OpenAI 格式的消息
        """
        # 根据来源确定角色
        role = self._get_role_for_source(context.source)

        # 处理多模态内容
        if context.source == ContextSource.MULTIMODAL and context.metadata.get("media_type"):
            return self._convert_multimodal_to_openai(context, role)

        return {
            "role": role,
            "content": context.content
        }

    def to_anthropic_format(self, context: ContextInput) -> Dict[str, Any]:
        """
        转换为 Anthropic 格式

        Args:
            context: 上下文输入

        Returns:
            Anthropic 格式的消息
        """
        # 根据来源确定角色
        role = self._get_role_for_source(context.source)

        # 处理多模态内容
        if context.source == ContextSource.MULTIMODAL and context.metadata.get("media_type"):
            return self._convert_multimodal_to_anthropic(context, role)

        return {
            "role": role,
            "content": [{"type": "text", "text": context.content}]
        }

    def convert_for_model(self, context: ContextInput, model_name: str) -> Dict[str, Any]:
        """
        根据模型名称转换格式

        Args:
            context: 上下文输入
            model_name: 模型名称

        Returns:
            适配模型格式的消息
        """
        # 判断模型类型
        if self._is_anthropic_model(model_name):
            return self.to_anthropic_format(context)
        else:
            return self.to_openai_format(context)

    def _get_role_for_source(self, source: ContextSource) -> str:
        """
        根据来源获取角色

        Args:
            source: 上下文来源

        Returns:
            角色名称
        """
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
        """
        判断是否为 Anthropic 模型

        Args:
            model_name: 模型名称

        Returns:
            是否为 Anthropic 模型
        """
        return "claude" in model_name.lower() or "anthropic" in model_name.lower()

    def _convert_multimodal_to_openai(
        self,
        context: ContextInput,
        role: str
    ) -> Dict[str, Any]:
        """
        转换多模态内容为 OpenAI 格式

        Args:
            context: 上下文输入
            role: 角色

        Returns:
            OpenAI 格式的多模态消息
        """
        content = []

        # 添加文本内容
        if context.content:
            content.append({
                "type": "text",
                "text": context.content
            })

        # 添加媒体内容
        media_type = context.metadata.get("media_type")
        media_url = context.metadata.get("media_url")

        if media_type == "image" and media_url:
            content.append({
                "type": "image_url",
                "image_url": {"url": media_url}
            })
        elif media_type == "audio" and media_url:
            # OpenAI 不直接支持音频，需要转换
            content.append({
                "type": "text",
                "text": f"[音频文件: {context.metadata.get('filename', 'unknown')}]"
            })
        elif media_type == "video" and media_url:
            # OpenAI 不直接支持视频，需要转换
            content.append({
                "type": "text",
                "text": f"[视频文件: {context.metadata.get('filename', 'unknown')}]"
            })

        return {
            "role": role,
            "content": content
        }

    def _convert_multimodal_to_anthropic(
        self,
        context: ContextInput,
        role: str
    ) -> Dict[str, Any]:
        """
        转换多模态内容为 Anthropic 格式

        Args:
            context: 上下文输入
            role: 角色

        Returns:
            Anthropic 格式的多模态消息
        """
        content = []

        # 添加文本内容
        if context.content:
            content.append({
                "type": "text",
                "text": context.content
            })

        # 添加媒体内容
        media_type = context.metadata.get("media_type")
        media_url = context.metadata.get("media_url")

        if media_type == "image" and media_url:
            content.append({
                "type": "image",
                "source": {
                    "type": "url",
                    "url": media_url
                }
            })
        elif media_type == "audio" and media_url:
            # Anthropic 不直接支持音频
            content.append({
                "type": "text",
                "text": f"[音频文件: {context.metadata.get('filename', 'unknown')}]"
            })
        elif media_type == "video" and media_url:
            # Anthropic 不直接支持视频
            content.append({
                "type": "text",
                "text": f"[视频文件: {context.metadata.get('filename', 'unknown')}]"
            })

        return {
            "role": role,
            "content": content
        }

class ContextCompressor:
    """上下文压缩器"""

    def __init__(self, max_tokens: int = 16000, enable_summarization: bool = False):
        """
        初始化压缩器

        Args:
            max_tokens: 最大Token数量
            enable_summarization: 是否启用摘要压缩
        """
        self.max_tokens = max_tokens
        self.enable_summarization = enable_summarization

    def compress(self, contexts: List[ContextInput]) -> List[ContextInput]:
        """
        压缩上下文列表

        Args:
            contexts: 原始上下文列表

        Returns:
            压缩后的上下文列表
        """
        # 确保每个上下文都有token估算
        for ctx in contexts:
            if ctx.tokens == 0:
                ctx.tokens = ContextPoolUtils.estimate_tokens(ctx.content)

        # 计算总Token数
        total_tokens = sum(ctx.tokens for ctx in contexts)

        if total_tokens <= self.max_tokens:
            return contexts

        # 按优先级排序
        sorted_contexts = sorted(
            contexts,
            key=lambda x: (-x.priority, x.tokens)
        )

        # 逐个添加直到超出预算
        result = []
        current_tokens = 0

        for ctx in sorted_contexts:
            if current_tokens + ctx.tokens <= self.max_tokens:
                result.append(ctx)
                current_tokens += ctx.tokens
            else:
                # 尝试压缩
                remaining_tokens = self.max_tokens - current_tokens
                if remaining_tokens > 0:
                    compressed_ctx = self._compress_context(ctx, remaining_tokens)
                    if compressed_ctx:
                        result.append(compressed_ctx)
                break

        return result

    def _compress_context(
        self,
        context: ContextInput,
        max_tokens: int
    ) -> Optional[ContextInput]:
        """
        压缩单个上下文

        Args:
            context: 原始上下文
            max_tokens: 最大Token数量

        Returns:
            压缩后的上下文
        """
        if self.enable_summarization:
            # 实现摘要压缩（简化版）
            summary = f"[摘要] {context.content[:max_tokens//2]}..."
            return ContextInput(
                source=context.source,
                content=summary,
                priority=context.priority,
                metadata=context.metadata,
                tokens=max_tokens
            )
        else:
            # 简单截断
            truncated_content = context.content[:max_tokens]
            return ContextInput(
                source=context.source,
                content=truncated_content,
                priority=context.priority,
                metadata=context.metadata,
                tokens=max_tokens
            )

class ContextPool:
    """
    上下文池 - 核心组件

    提供上下文收集、重组、转换、压缩的统一接口。
    支持模型切换时的上下文适配。
    """

    def __init__(self, max_tokens: int = 16000):
        """
        初始化上下文池

        Args:
            max_tokens: 最大Token数量
        """
        self.max_tokens = max_tokens
        self._collector = ContextCollector(max_tokens)
        self._converter = ContextConverter()
        self._compressor = ContextCompressor(max_tokens)

    def add_context(self, context: ContextInput):
        """
        添加上下文

        Args:
            context: 上下文输入
        """
        self._collector.add_context(context)

    def get_contexts(self) -> List[ContextInput]:
        """
        获取所有上下文

        Returns:
            上下文列表
        """
        return self._collector.collect()

    def build_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        """
        为指定模型构建上下文

        Args:
            model_name: 模型名称

        Returns:
            适配模型格式的消息列表
        """
        contexts = self.get_contexts()
        messages = []

        for ctx in contexts:
            msg = self._converter.convert_for_model(ctx, model_name)
            messages.append(msg)

        return messages

    def convert_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        """
        转换上下文格式以适配模型

        Args:
            model_name: 模型名称

        Returns:
            转换后的消息列表
        """
        return self.build_context_for_model(model_name)

    def compress_context(self):
        """压缩上下文以适应Token预算"""
        contexts = self.get_contexts()
        compressed = self._compressor.compress(contexts)

        # 清空并重新添加压缩后的上下文
        self._collector._contexts = compressed

    def merge_with(self, other_pool: 'ContextPool'):
        """
        合并另一个上下文池

        Args:
            other_pool: 另一个上下文池
        """
        other_contexts = other_pool.get_contexts()
        for ctx in other_contexts:
            self._collector.add_context(ctx)

class ContextPoolUtils:
    """上下文池工具函数"""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        """
        估算文本的Token数量

        Args:
            text: 文本

        Returns:
            估算的Token数量
        """
        if not text:
            return 0

        # 简单估算：中文约1.5 tokens/字，英文约0.25 tokens/词
        chinese_chars = sum(1 for char in text if '\u4e00' <= char <= '\u9fff')
        total_chars = len(text)
        non_chinese_chars = total_chars - chinese_chars

        # 英文按空格分词
        words = text.split()
        english_words = len(words)

        chinese_tokens = chinese_chars * 1.5
        english_tokens = english_words * 0.25

        return max(1, int(chinese_tokens + english_tokens))

    @staticmethod
    def merge_contexts(
        *context_lists: List[ContextInput]
    ) -> List[ContextInput]:
        """
        合并多个上下文列表

        Args:
            *context_lists: 上下文列表

        Returns:
            合并后的上下文列表
        """
        merged = []
        for ctx_list in context_lists:
            merged.extend(ctx_list)

        # 按优先级排序
        return sorted(merged, key=lambda x: (-x.priority, x.tokens))

    @staticmethod
    def filter_by_source(
        contexts: List[ContextInput],
        source: ContextSource
    ) -> List[ContextInput]:
        """
        按来源过滤上下文

        Args:
            contexts: 上下文列表
            source: 上下文来源

        Returns:
            过滤后的上下文列表
        """
        return [ctx for ctx in contexts if ctx.source == source]