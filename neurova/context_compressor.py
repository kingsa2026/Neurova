"""
智能上下文压缩器

核心特性:
1. 保证会话轮次完整性 - 不截断user/assistant对话对
2. 分层压缩策略 - 从低优先级开始压缩
3. 记忆优先级管理 - 重要记忆不被压缩
4. Token预算管理 - 精确控制上下文长度
5. 摘要生成 - 对压缩部分生成有意义的摘要
"""

import re
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from neurova.context.token_estimator import EstimationStrategy, TokenEstimator
from neurova.core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CompressionConfig:
    """压缩配置"""

    max_tokens: int = 4096
    min_tokens: int = 512
    target_ratio: float = 0.7  # 目标压缩率
    preserve_recent_turns: int = 5  # 保留最近轮次数
    summary_max_length: int = 200  # 摘要最大长度
    enable_progressive: bool = True  # 启用渐进式压缩
    priority_threshold: float = 0.8  # 优先级阈值（高于此值不压缩）

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return asdict(self)


class MessagePriority(Enum):
    """消息优先级"""

    LOW = 0.2
    MEDIUM = 0.5
    HIGH = 0.8
    CRITICAL = 1.0  # 不应被压缩


@dataclass
class Message:
    """消息数据"""

    role: str  # user, assistant, system
    content: str
    priority: MessagePriority = MessagePriority.MEDIUM
    timestamp: Optional[float] = None
    token_count: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None

    def estimate_tokens(self) -> int:
        """估算token数量"""
        if self.token_count is not None:
            return self.token_count

        # 使用统一的 Token 估算器
        estimator = TokenEstimator(EstimationStrategy.BALANCED)
        return estimator.estimate(self.content)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "role": self.role,
            "content": self.content,
            "priority": self.priority.value,
            "timestamp": self.timestamp,
            "token_count": self.token_count,
        }


class SmartContextCompressor:
    """
    智能上下文压缩器

    负责压缩对话历史，确保在token预算内保留最重要的信息。
    """

    def __init__(self, config: Optional[CompressionConfig] = None):
        """
        初始化压缩器

        Args:
            config: 压缩配置
        """
        self.config = config or CompressionConfig()

        # 统计信息
        self._stats = {"compressions": 0, "messages_compressed": 0, "tokens_saved": 0, "summaries_generated": 0}

        logger.info("SmartContextCompressor 初始化，最大tokens: %s", self.config.max_tokens)

    def compress_context(
        self,
        messages: List[Dict[str, Any]],
        memories: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        target_tokens: Optional[int] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """
        压缩上下文

        Args:
            messages: 消息列表
            memories: 记忆列表
            system_prompt: 系统提示
            target_tokens: 目标token数

        Returns:
            (压缩后的消息列表, 压缩摘要)
        """
        target = target_tokens or self.config.max_tokens

        # 转换为Message对象
        msg_objects = [Message(**msg) for msg in messages]

        # 计算当前token数
        total_tokens = self._count_tokens(msg_objects)

        # 如果已经在预算内，直接返回
        if total_tokens <= target:
            return messages, ""

        logger.info("开始压缩上下文，当前tokens: %s，目标: %s", total_tokens, target)

        # 分离记忆和对话
        memory_msgs = []
        conversation_msgs = []

        for msg in msg_objects:
            if msg.role == "memory":
                memory_msgs.append(msg)
            else:
                conversation_msgs.append(msg)

        # 压缩记忆
        compressed_memories, memory_summary = self._compress_memories(memory_msgs, target // 3)

        # 压缩对话历史
        remaining_budget = target - self._count_tokens(compressed_memories)
        compressed_conversation, conversation_summary = self._compress_history(
            conversation_msgs, remaining_budget, system_prompt
        )

        # 合并结果
        result = []
        for msg in compressed_memories + compressed_conversation:
            result.append(msg.to_dict())

        # 生成总摘要
        summary = self._generate_compression_summary(memory_summary, conversation_summary)

        self._stats["compressions"] += 1

        logger.info("压缩完成，压缩后tokens: %s", self._count_tokens(compressed_memories + compressed_conversation))

        return result, summary

    def _compress_memories(self, memories: List[Message], budget_tokens: int) -> Tuple[List[Message], str]:
        """
        压缩记忆

        Args:
            memories: 记忆列表
            budget_tokens: token预算

        Returns:
            (压缩后的记忆列表, 摘要)
        """
        if not memories:
            return [], ""

        # 按优先级排序
        memories.sort(key=lambda x: x.priority.value, reverse=True)

        compressed = []
        current_tokens = 0
        skipped = []

        for memory in memories:
            memory_tokens = memory.estimate_tokens()

            # 检查是否在预算内
            if current_tokens + memory_tokens <= budget_tokens:
                compressed.append(memory)
                current_tokens += memory_tokens
            else:
                skipped.append(memory)

        # 为跳过的记忆生成摘要
        summary = ""
        if skipped:
            summary = self._summarize_memories(skipped)
            self._stats["messages_compressed"] += len(skipped)
            self._stats["tokens_saved"] += sum(m.estimate_tokens() for m in skipped)

        return compressed, summary

    def _summarize_memories(self, memories: List[Message]) -> str:
        """
        为记忆生成摘要

        Args:
            memories: 记忆列表

        Returns:
            摘要文本
        """
        if not memories:
            return ""

        # 提取关键信息
        key_points = []
        for memory in memories[:5]:  # 最多取5个
            # 简化内容
            content = memory.content[:100] + "..." if len(memory.content) > 100 else memory.content
            key_points.append(content)

        summary = "相关记忆摘要：" + "；".join(key_points)

        # 截断到最大长度
        if len(summary) > self.config.summary_max_length:
            summary = summary[: self.config.summary_max_length] + "..."

        self._stats["summaries_generated"] += 1

        return summary

    def _compress_history(
        self, messages: List[Message], budget_tokens: int, system_prompt: Optional[str] = None
    ) -> Tuple[List[Message], str]:
        """
        压缩对话历史

        Args:
            messages: 消息列表
            budget_tokens: token预算
            system_prompt: 系统提示

        Returns:
            (压缩后的消息列表, 摘要)
        """
        if not messages:
            return [], ""

        # 计算系统提示的token数
        system_tokens = 0
        if system_prompt:
            # 使用统一的 Token 估算器
            estimator = TokenEstimator(EstimationStrategy.BALANCED)
            system_tokens = estimator.estimate(system_prompt)

        available_tokens = budget_tokens - system_tokens

        # 保留最近的轮次
        recent_turns = self.config.preserve_recent_turns * 2  # user + assistant
        recent_messages = messages[-recent_turns:] if len(messages) > recent_turns else messages

        # 计算最近消息的token数
        recent_tokens = sum(msg.estimate_tokens() for msg in recent_messages)

        # 如果最近消息已经在预算内
        if recent_tokens <= available_tokens:
            # 尝试添加更多历史消息
            older_messages = messages[:-recent_turns] if len(messages) > recent_turns else []

            if older_messages and self.config.enable_progressive:
                # 渐进式压缩
                additional, additional_summary = self._progressive_compress_history(
                    older_messages, available_tokens - recent_tokens
                )

                return additional + recent_messages, additional_summary
            else:
                return recent_messages, ""

        # 需要压缩最近消息
        if self.config.enable_progressive:
            compressed, summary = self._progressive_compress_history(messages, available_tokens)
        else:
            compressed, summary = self._simple_compress_history(messages, available_tokens)

        return compressed, summary

    def _progressive_compress_history(self, messages: List[Message], budget_tokens: int) -> Tuple[List[Message], str]:
        """
        渐进式压缩历史

        Args:
            messages: 消息列表
            budget_tokens: token预算

        Returns:
            (压缩后的消息列表, 摘要)
        """
        # 按轮次分组
        turns = self._group_into_turns(messages)

        # 按时间排序（从旧到新）
        turns.sort(key=lambda t: t[0].timestamp or 0)

        compressed = []
        current_tokens = 0
        skipped_turns = []

        for turn in turns:
            turn_tokens = sum(msg.estimate_tokens() for msg in turn)

            if current_tokens + turn_tokens <= budget_tokens:
                compressed.extend(turn)
                current_tokens += turn_tokens
            else:
                skipped_turns.append(turn)

        # 为跳过的轮次生成摘要
        summary = ""
        if skipped_turns:
            summary = self._summarize_turns(skipped_turns)

        return compressed, summary

    def _simple_compress_history(self, messages: List[Message], budget_tokens: int) -> Tuple[List[Message], str]:
        """
        简单压缩历史

        Args:
            messages: 消息列表
            budget_tokens: token预算

        Returns:
            (压缩后的消息列表, 摘要)
        """
        # 保留最近的消息
        compressed = []
        current_tokens = 0

        for msg in reversed(messages):
            msg_tokens = msg.estimate_tokens()

            if current_tokens + msg_tokens <= budget_tokens:
                compressed.insert(0, msg)
                current_tokens += msg_tokens
            else:
                break

        # 为被截断的部分生成摘要
        skipped = messages[: len(messages) - len(compressed)]
        summary = ""

        if skipped:
            summary = self._generate_history_summary(skipped)

        return compressed, summary

    def _calculate_dynamic_budget(self, total_tokens: int, message_count: int) -> int:
        """
        计算动态token预算

        Args:
            total_tokens: 总token数
            message_count: 消息数量

        Returns:
            动态预算
        """
        # 基础预算
        base_budget = self.config.max_tokens

        # 根据消息数量调整
        if message_count < 10:
            # 消息少时，预算更宽松
            return min(base_budget, total_tokens)
        elif message_count < 50:
            # 消息中等时，使用目标压缩率
            return int(base_budget * self.config.target_ratio)
        else:
            # 消息多时，更激进地压缩
            return int(base_budget * 0.5)

    def _smart_truncate(self, text: str, max_length: int, preserve_sentences: bool = True) -> str:
        """
        智能截断文本

        Args:
            text: 文本
            max_length: 最大长度
            preserve_sentences: 是否保留完整句子

        Returns:
            截断后的文本
        """
        if len(text) <= max_length:
            return text

        if preserve_sentences:
            # 在句子边界截断
            sentences = re.split(r"[。！？.!?]", text)
            result = []
            current_length = 0

            for sentence in sentences:
                if current_length + len(sentence) + 1 <= max_length:
                    result.append(sentence)
                    current_length += len(sentence) + 1
                else:
                    break

            return "。".join(result) + "..."
        else:
            # 直接截断
            return text[: max_length - 3] + "..."

    def _generate_history_summary(self, messages: List[Message]) -> str:
        """
        生成历史摘要

        Args:
            messages: 消息列表

        Returns:
            摘要文本
        """
        if not messages:
            return ""

        # 提取关键信息
        key_points = []

        for msg in messages:
            # 简化内容
            content = self._smart_truncate(msg.content, 50)
            key_points.append(f"{msg.role}: {content}")

        summary = "历史对话摘要：" + "；".join(key_points[:3])  # 最多3个

        # 截断
        if len(summary) > self.config.summary_max_length:
            summary = summary[: self.config.summary_max_length] + "..."

        self._stats["summaries_generated"] += 1

        return summary

    def _group_into_turns(self, messages: List[Message]) -> List[List[Message]]:
        """
        将消息分组为轮次

        Args:
            messages: 消息列表

        Returns:
            轮次列表
        """
        turns = []
        current_turn = []

        for msg in messages:
            current_turn.append(msg)

            # 当遇到assistant消息时，完成一个轮次
            if msg.role == "assistant":
                turns.append(current_turn)
                current_turn = []

        # 处理剩余的消息
        if current_turn:
            turns.append(current_turn)

        return turns

    def _summarize_turns(self, turns: List[List[Message]]) -> str:
        """
        为轮次生成摘要

        Args:
            turns: 轮次列表

        Returns:
            摘要文本
        """
        if not turns:
            return ""

        summaries = []
        for turn in turns[:3]:  # 最多3个轮次
            turn_summary = []
            for msg in turn:
                content = self._smart_truncate(msg.content, 30)
                turn_summary.append(f"{msg.role}: {content}")

            summaries.append(" → ".join(turn_summary))

        summary = "历史轮次摘要：" + "；".join(summaries)

        # 截断
        if len(summary) > self.config.summary_max_length:
            summary = summary[: self.config.summary_max_length] + "..."

        return summary

    def _build_context(
        self, messages: List[Message], system_prompt: Optional[str] = None, memories: Optional[List[Message]] = None
    ) -> List[Dict[str, Any]]:
        """
        构建上下文

        Args:
            messages: 消息列表
            system_prompt: 系统提示
            memories: 记忆列表

        Returns:
            上下文字典列表
        """
        context = []

        # 添加系统提示
        if system_prompt:
            context.append({"role": "system", "content": system_prompt})

        # 添加记忆
        if memories:
            for memory in memories:
                context.append(memory.to_dict())

        # 添加消息
        for msg in messages:
            context.append(msg.to_dict())

        return context

    def _build_system_prompt(self, base_prompt: str, summary: str) -> str:
        """
        构建系统提示

        Args:
            base_prompt: 基础提示
            summary: 压缩摘要

        Returns:
            完整系统提示
        """
        if not summary:
            return base_prompt

        return f"{base_prompt}\n\n[上下文压缩摘要]\n{summary}"

    def _estimate_total_tokens(self, messages: List[Message], system_prompt: Optional[str] = None) -> int:
        """
        估算总token数

        Args:
            messages: 消息列表
            system_prompt: 系统提示

        Returns:
            总token数
        """
        total = 0

        # 系统提示
        if system_prompt:
            # 使用统一的 Token 估算器
            estimator = TokenEstimator(EstimationStrategy.BALANCED)
            total += estimator.estimate(system_prompt)

        # 消息
        for msg in messages:
            total += msg.estimate_tokens()

        return total

    def _count_context_tokens(self, context: List[Dict[str, Any]]) -> int:
        """
        计算上下文token数

        Args:
            context: 上下文字典列表

        Returns:
            token数
        """
        total = 0

        for item in context:
            content = item.get("content", "")
            # 使用统一的 Token 估算器
            estimator = TokenEstimator(EstimationStrategy.BALANCED)
            total += estimator.estimate(content)

        return total

    def _count_tokens(self, messages: List[Message]) -> int:
        """
        计算消息token数

        Args:
            messages: 消息列表

        Returns:
            token数
        """
        return sum(msg.estimate_tokens() for msg in messages)

    def _generate_compression_summary(self, memory_summary: str, conversation_summary: str) -> str:
        """
        生成压缩摘要

        Args:
            memory_summary: 记忆摘要
            conversation_summary: 对话摘要

        Returns:
            总摘要
        """
        parts = []

        if memory_summary:
            parts.append(memory_summary)

        if conversation_summary:
            parts.append(conversation_summary)

        if not parts:
            return ""

        return "\n".join(parts)

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self._stats.copy()


# 单例管理
_compressor_instance: Optional[SmartContextCompressor] = None


def get_context_compressor(config: Optional[CompressionConfig] = None) -> SmartContextCompressor:
    """获取上下文压缩器单例"""
    global _compressor_instance

    if _compressor_instance is None:
        _compressor_instance = SmartContextCompressor(config)

    return _compressor_instance


def reset_context_compressor():
    """重置上下文压缩器单例"""
    global _compressor_instance
    _compressor_instance = None
