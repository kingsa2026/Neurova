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

import hashlib
import logging
import math
import re
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any, Set

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
    """上下文输入数据类 - 活水上下文池的基础单元"""
    source: ContextSource
    content: str
    priority: int = 50
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    tags: List[str] = field(default_factory=list)  # 标签列表
    hash: str = None  # 内容哈希（用于精确去重）
    created_at: datetime = None  # 创建时间
    updated_at: datetime = None  # 更新时间

    def __post_init__(self):
        """初始化后处理"""
        # 自动生成哈希
        if self.hash is None:
            self.hash = hashlib.md5(self.content.encode()).hexdigest()
        
        # 自动设置时间
        now = datetime.now()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "source": self.source.value,
            "content": self.content,
            "priority": self.priority,
            "metadata": self.metadata,
            "tokens": self.tokens,
            "tags": self.tags,
            "hash": self.hash,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
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
    
    支持三层隔离机制：
    - 用户隔离：不同用户的上下文完全隔离
    - Agent隔离：不同Agent的上下文完全隔离
    - Session隔离：不同Session的上下文完全隔离
    """

    def __init__(
        self,
        user_id: str = None,
        agent_id: str = None,
        session_id: str = None,
        max_tokens: int = 16000,
        auto_tag: bool = False,
        max_size: int = 100,
        ttl_seconds: int = 3600
    ):
        """
        初始化上下文池

        Args:
            user_id: 用户ID（必需）
            agent_id: Agent ID（必需）
            session_id: 会话ID（可选）
            max_tokens: 最大Token数量
            auto_tag: 是否启用自动标签生成
            max_size: 池最大大小限制（默认100）
            ttl_seconds: 上下文过期时间（秒，默认3600）
            
        Raises:
            ValueError: 如果 user_id 或 agent_id 未提供
        """
        # 验证隔离参数
        if user_id is None:
            raise ValueError("user_id is required")
        if agent_id is None:
            raise ValueError("agent_id is required")
        
        # 验证ID不包含分隔符
        separator = ":"
        if separator in user_id:
            raise ValueError("user_id 不能包含分隔符")
        if separator in agent_id:
            raise ValueError("agent_id 不能包含分隔符")
        if session_id and separator in session_id:
            raise ValueError("session_id 不能包含分隔符")
        
        self.user_id = user_id
        self.agent_id = agent_id
        self.session_id = session_id
        self.max_tokens = max_tokens
        self.auto_tag = auto_tag
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        
        self._collector = ContextCollector(max_tokens)
        self._converter = ContextConverter()
        self._compressor = ContextCompressor(max_tokens)
        
        # 活水上下文池新增组件
        self._drawer = SemanticMatchDrawer(max_tokens)
        self._deduplicator = DriftSafeDeduplicator()
        
        # 自动标签生成器
        if auto_tag:
            self._auto_tagger = AutoTagger()
        
        # 缓存机制
        self._cache = {}
        self._cache_version = 0
        self._last_build_version = -1
        
    @property
    def isolation_key(self) -> str:
        """生成隔离键"""
        session_part = self.session_id if self.session_id else "default"
        return f"{self.user_id}:{self.agent_id}:{session_part}"
    
    def add_context(self, context: ContextInput):
        """
        添加上下文

        Args:
            context: 上下文输入
        """
        # 如果启用自动标签，为上下文生成标签
        if self.auto_tag and hasattr(self, '_auto_tagger'):
            context = self._auto_tagger.auto_tag(context)
        
        # 检查大小限制
        if hasattr(self, 'max_size') and self.max_size > 0:
            current_size = len(self._collector._contexts)
            if current_size >= self.max_size:
                # 移除最旧的上下文
                self._collector._contexts.pop(0)
        
        self._collector.add_context(context)
        # 使缓存失效
        self._cache_version += 1

    def get_contexts(self) -> List[ContextInput]:
        """
        获取所有上下文（过滤过期的）

        Returns:
            上下文列表
        """
        contexts = self._collector.collect()
        
        # 过滤过期的上下文
        if hasattr(self, 'ttl_seconds') and self.ttl_seconds > 0:
            now = datetime.now()
            valid_contexts = []
            for ctx in contexts:
                if ctx.created_at:
                    age = (now - ctx.created_at).total_seconds()
                    if age <= self.ttl_seconds:
                        valid_contexts.append(ctx)
                else:
                    valid_contexts.append(ctx)
            return valid_contexts
        
        return contexts

    def cleanup_expired(self) -> int:
        """
        清理过期的上下文

        Returns:
            移除的上下文数量
        """
        if not hasattr(self, 'ttl_seconds') or self.ttl_seconds <= 0:
            return 0
        
        now = datetime.now()
        original_count = len(self._collector._contexts)
        
        # 过滤保留有效的上下文
        valid_contexts = []
        for ctx in self._collector._contexts:
            if ctx.created_at:
                age = (now - ctx.created_at).total_seconds()
                if age <= self.ttl_seconds:
                    valid_contexts.append(ctx)
            else:
                valid_contexts.append(ctx)
        
        self._collector._contexts = valid_contexts
        
        removed_count = original_count - len(valid_contexts)
        if removed_count > 0:
            self._cache_version += 1
        
        return removed_count

    @staticmethod
    def get_token_budget_for_model(model_name: str, default_budget: int = 16000) -> int:
        """
        根据模型获取 Token 预算（静态方法，可独立调用）

        Args:
            model_name: 模型名称
            default_budget: 默认预算

        Returns:
            Token 预算
        """
        # 根据模型名称调整预算
        model_budgets = {
            "gpt-4": 32000,
            "gpt-4-turbo": 32000,
            "gpt-4o": 32000,
            "gpt-3.5-turbo": 16000,
            "claude-3-opus": 200000,
            "claude-3-sonnet": 200000,
            "claude-3-haiku": 200000,
            "claude-2": 100000,
            "deepseek-chat": 32000,
            "deepseek-coder": 32000,
            "qwen-max": 32000,
            "qwen-turbo": 16000,
        }
        
        # 尝试匹配模型名称
        for model_pattern, budget in model_budgets.items():
            if model_pattern in model_name.lower():
                return budget
        
        return default_budget

    def get_token_budget_for_capabilities(self, capabilities: list) -> int:
        """
        根据模型能力获取 Token 预算

        Args:
            capabilities: 模型能力列表

        Returns:
            Token 预算
        """
        try:
            from neurova.llm.llm_router import ModelCapability
        except ImportError:
            logger.debug("ModelCapability 延迟导入失败，使用默认预算")
            return 16000
        
        base_budget = 16000
        
        # 根据能力调整预算
        if ModelCapability.VISION in capabilities:
            base_budget += 16000  # 视觉模型需要更多预算
        if ModelCapability.AUDIO in capabilities:
            base_budget += 8000  # 音频模型需要更多预算
        if ModelCapability.VIDEO in capabilities:
            base_budget += 32000  # 视频模型需要更多预算
        if ModelCapability.MULTIMODAL in capabilities:
            base_budget += 16000  # 多模态模型需要更多预算
        
        return base_budget

    def build_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        """
        为指定模型构建上下文

        Args:
            model_name: 模型名称

        Returns:
            适配模型格式的消息列表
        """
        # 检查缓存
        cache_key = f"{self.isolation_key}:{model_name}"
        if (cache_key in self._cache and 
            self._last_build_version == self._cache_version):
            return self._cache[cache_key]
        
        # 获取上下文
        contexts = self.get_contexts()
        
        # 构建消息
        messages = []
        for ctx in contexts:
            msg = self._converter.convert_for_model(ctx, model_name)
            messages.append(msg)
        
        # 更新缓存
        self._cache[cache_key] = messages
        self._last_build_version = self._cache_version
        
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
    
    def draw(self, need: str = None) -> List[ContextInput]:
        """
        按需取水 - 活水上下文池核心方法
        
        Args:
            need: 需求描述字符串，如 "编程 代码 函数"
                  如果为 None，返回综合得分最高的水滴
        
        Returns:
            排序后的水滴列表（已应用 Token 预算）
        """
        # 1. 去重
        all_drops = self._collector.collect()
        deduped = self._deduplicator.dedup(all_drops, stage='output')
        
        # 2. 按需取水
        return self._drawer.draw(deduped, need=need)
    
    def dedup(self, stage: str = 'input') -> int:
        """
        对上下文池进行去重
        
        Args:
            stage: 去重阶段 ('input', 'compression', 'output')
        
        Returns:
            去重后保留的上下文数量
        """
        all_drops = self._collector.collect()
        deduped = self._deduplicator.dedup(all_drops, stage=stage)
        
        # 更新收集器
        self._collector._contexts = deduped
        
        return len(deduped)

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


class DriftSafeDeduplicator:
    """防漂移去重器 - 多阶段去重，保留关键上下文"""
    
    def __init__(self, semantic_threshold: float = 0.95):
        """
        初始化去重器
        
        Args:
            semantic_threshold: 语义去重阈值（越高越保守）
        """
        self.semantic_threshold = semantic_threshold
    
    def dedup(self, drops: List[ContextInput], stage: str = 'input') -> List[ContextInput]:
        """
        多阶段去重
        
        Args:
            drops: 水滴列表
            stage: 去重阶段 ('input', 'compression', 'output')
            
        Returns:
            去重后的水滴列表
        """
        if not drops:
            return []
        
        # 阶段1：精确去重（安全，无信息丢失）
        stage1 = self._exact_dedup(drops)
        
        # 阶段2：模式去重（同来源相似内容）
        stage2 = self._pattern_dedup(stage1)
        
        return stage2
    
    def _exact_dedup(self, drops: List[ContextInput]) -> List[ContextInput]:
        """精确去重：相同哈希的内容"""
        seen_hashes = set()
        result = []
        
        for drop in drops:
            if drop.hash not in seen_hashes:
                seen_hashes.add(drop.hash)
                result.append(drop)
            else:
                # 保留优先级更高的版本
                existing_idx = next(
                    (i for i, d in enumerate(result) if d.hash == drop.hash), 
                    None
                )
                if existing_idx is not None and drop.priority > result[existing_idx].priority:
                    result[existing_idx] = drop
        
        return result
    
    def _pattern_dedup(self, drops: List[ContextInput]) -> List[ContextInput]:
        """模式去重：同来源相似内容"""
        by_source: Dict[ContextSource, List[ContextInput]] = {}
        
        for drop in drops:
            if drop.source not in by_source:
                by_source[drop.source] = []
            by_source[drop.source].append(drop)
        
        result = []
        for source, source_drops in by_source.items():
            # 对同一来源的内容进行去重
            deduped = self._dedup_same_source(source_drops)
            result.extend(deduped)
        
        return result
    
    def _dedup_same_source(self, drops: List[ContextInput]) -> List[ContextInput]:
        """对同一来源的内容去重（只去重相同内容）"""
        if len(drops) <= 1:
            return drops
        
        # 按哈希分组，保留每组优先级最高的
        by_hash: Dict[str, List[ContextInput]] = {}
        for drop in drops:
            if drop.hash not in by_hash:
                by_hash[drop.hash] = []
            by_hash[drop.hash].append(drop)
        
        # 从每组中选择优先级最高的
        result = []
        for hash_val, hash_drops in by_hash.items():
            best = max(hash_drops, key=lambda d: d.priority)
            result.append(best)
        
        return result


class SemanticMatchDrawer:
    """向量语义匹配取水器 - 按需取水，不需要预定义需求类型"""
    
    # 来源衰减倍数
    SOURCE_MULTIPLIERS = {
        ContextSource.USER_INPUT: 1.0,       # 用户输入：正常衰减
        ContextSource.CONVERSATION: 0.8,     # 对话历史：稍快衰减
        ContextSource.MEMORY: 0.3,           # 记忆：慢衰减
        ContextSource.EMOTION: 0.5,          # 情感：中等衰减
        ContextSource.TOOL_CALL: 0.6,        # 工具调用：中等衰减
        ContextSource.SYSTEM_INSTRUCTION: 0.1,  # 系统指令：极慢衰减
        ContextSource.EXPERIENCE: 0.4,       # 经验：慢衰减
        ContextSource.REFLECTION: 0.4,       # 反思：慢衰减
        ContextSource.MULTIMODAL: 0.7,       # 多模态：中等衰减
        ContextSource.DEVELOPER_INSTRUCTION: 0.1,  # 开发者指令：极慢衰减
    }
    
    # 权重配置
    WEIGHTS = {
        'match_score': 0.5,   # 匹配度权重
        'freshness': 0.2,     # 新鲜度权重
        'priority': 0.2,      # 优先级权重
        'source_match': 0.1   # 来源匹配权重
    }
    
    def __init__(self, max_tokens: int = 16000):
        """
        初始化取水器
        
        Args:
            max_tokens: 最大 Token 数量
        """
        self.max_tokens = max_tokens
        self._vector_store = None
    
    @property
    def vector_store(self):
        """懒加载向量存储"""
        if self._vector_store is None:
            try:
                from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
                self._vector_store = UnifiedVectorStore(backend="auto")
            except ImportError:
                logger.warning("UnifiedVectorStore 不可用，使用简单匹配")
                self._vector_store = False
        return self._vector_store
    
    def preload_vector_store(self):
        """预加载向量存储"""
        if self._vector_store is None:
            try:
                from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore
                self._vector_store = UnifiedVectorStore(backend="auto")
                logger.info("向量存储预加载完成")
            except ImportError:
                logger.warning("UnifiedVectorStore 不可用，使用简单匹配")
                self._vector_store = False
    
    def draw(self, drops: List[ContextInput], need: str = None) -> List[ContextInput]:
        """
        按需取水
        
        Args:
            drops: 水滴列表
            need: 需求描述字符串，如 "编程 代码 函数"
                  如果为 None，返回综合得分最高的水滴
        
        Returns:
            排序后的水滴列表（已应用 Token 预算）
        """
        if not drops:
            return []
        
        # 1. 计算每个水滴的得分
        scored_drops = []
        for drop in drops:
            score = self._calculate_score(drop, need)
            scored_drops.append((score, drop))
        
        # 2. 按得分降序排序
        scored_drops.sort(key=lambda x: -x[0])
        
        # 3. 应用 Token 预算
        result = []
        total_tokens = 0
        
        for score, drop in scored_drops:
            drop_tokens = drop.tokens if drop.tokens > 0 else ContextPoolUtils.estimate_tokens(drop.content)
            
            if total_tokens + drop_tokens <= self.max_tokens:
                result.append(drop)
                total_tokens += drop_tokens
            else:
                # 尝试截断
                remaining = self.max_tokens - total_tokens
                if remaining > 100:  # 至少 100 tokens
                    truncated = self._truncate_drop(drop, remaining)
                    if truncated:
                        result.append(truncated)
                break
        
        return result
    
    def _calculate_score(self, drop: ContextInput, need: str = None) -> float:
        """计算水滴综合得分"""
        # 匹配度得分
        match_score = self._calculate_match_score(drop, need) if need else 0.5
        
        # 新鲜度得分
        freshness_score = self._calculate_freshness_score(drop)
        
        # 优先级得分
        priority_score = drop.priority / 100.0
        
        # 来源匹配得分
        source_score = self._calculate_source_score(drop, need) if need else 0.5
        
        # 综合得分
        total = (
            self.WEIGHTS['match_score'] * match_score +
            self.WEIGHTS['freshness'] * freshness_score +
            self.WEIGHTS['priority'] * priority_score +
            self.WEIGHTS['source_match'] * source_score
        )
        
        return total
    
    def _calculate_match_score(self, drop: ContextInput, need: str) -> float:
        """计算匹配度得分 - 核心匹配逻辑"""
        if not need:
            return 0.5
        
        # 尝试使用向量匹配
        if self.vector_store:
            return self._vector_match_score(drop, need)
        
        # 降级到关键词匹配
        return self._keyword_match_score(drop, need)
    
    def _vector_match_score(self, drop: ContextInput, need: str) -> float:
        """向量语义匹配"""
        try:
            # 编码需求
            need_vec = self.vector_store.encode(need)
            
            # 编码水滴内容（包含标签）
            drop_text = drop.content
            if drop.tags:
                drop_text += " " + " ".join(drop.tags)
            drop_vec = self.vector_store.encode(drop_text)
            
            # 计算余弦相似度
            from neurova.cognitive_layers.memory_layer.unified_vector_store import cosine_similarity
            similarity = cosine_similarity(need_vec, drop_vec)
            
            # 归一化到 [0, 1]
            return (similarity + 1) / 2
        except Exception as e:
            logger.warning(f"向量匹配失败，降级到关键词匹配: {e}")
            return self._keyword_match_score(drop, need)
    
    def _keyword_match_score(self, drop: ContextInput, need: str) -> float:
        """关键词匹配（降级方案）"""
        import re
        
        # 提取关键词
        need_keywords = [kw.strip() for kw in re.sub(r'[^\w\s]', ' ', need).split() if len(kw.strip()) > 1]
        if not need_keywords:
            return 0.5
        
        # 匹配标签
        tag_matches = sum(1 for kw in need_keywords 
                         if any(kw in tag for tag in drop.tags))
        
        # 匹配内容
        content_matches = sum(1 for kw in need_keywords if kw in drop.content)
        
        # 计算匹配度
        total_keywords = len(need_keywords)
        tag_ratio = tag_matches / total_keywords
        content_ratio = min(content_matches / total_keywords, 1.0)
        
        return 0.5 * tag_ratio + 0.5 * content_ratio
    
    def _calculate_freshness_score(self, drop: ContextInput) -> float:
        """计算新鲜度得分"""
        if not drop.updated_at:
            return 0.5
        
        age_hours = (datetime.now() - drop.updated_at).total_seconds() / 3600
        
        # 指数衰减
        freshness = math.exp(-0.1 * age_hours)
        
        # 来源调整
        multiplier = self.SOURCE_MULTIPLIERS.get(drop.source, 0.5)
        
        return freshness * multiplier
    
    def _calculate_source_score(self, drop: ContextInput, need: str) -> float:
        """计算来源匹配得分"""
        if not need:
            return 0.5
        
        # 简单实现：检查来源是否在需求中提及
        source_text = drop.source.value.replace("_", " ")
        need_lower = need.lower()
        
        if source_text in need_lower:
            return 1.0
        
        return 0.3  # 默认得分
    
    def _truncate_drop(self, drop: ContextInput, max_tokens: int) -> Optional[ContextInput]:
        """截断水滴以适应 Token 预算"""
        drop_tokens = drop.tokens if drop.tokens > 0 else ContextPoolUtils.estimate_tokens(drop.content)
        
        if drop_tokens <= max_tokens:
            return drop
        
        # 按比例截断内容
        ratio = max_tokens / drop_tokens
        truncated_content = drop.content[:int(len(drop.content) * ratio)]
        
        # 创建截断后的副本
        return ContextInput(
            id=drop.id if hasattr(drop, 'id') else None,
            source=drop.source,
            content=truncated_content + "...",
            priority=drop.priority,
            metadata=drop.metadata,
            tokens=max_tokens,
            tags=drop.tags,
            hash=hashlib.md5(truncated_content.encode()).hexdigest(),
            created_at=drop.created_at,
            updated_at=drop.updated_at,
        )


class AutoTagger:
    """自动标签生成器 - 从内容和来源自动生成标签"""
    
    # 来源标签映射
    SOURCE_TAGS = {
        ContextSource.SYSTEM_INSTRUCTION: ["系统", "指令"],
        ContextSource.DEVELOPER_INSTRUCTION: ["开发者", "指令"],
        ContextSource.MEMORY: ["记忆"],
        ContextSource.CONVERSATION: ["对话", "历史"],
        ContextSource.EXPERIENCE: ["经验", "知识"],
        ContextSource.EMOTION: ["情感", "心情"],
        ContextSource.REFLECTION: ["反思", "日志"],
        ContextSource.TOOL_CALL: ["工具", "调用"],
        ContextSource.MULTIMODAL: ["多模态", "媒体"],
        ContextSource.USER_INPUT: ["用户", "输入"],
    }
    
    # 常见关键词模式
    KEYWORD_PATTERNS = {
        "编程": ["编程", "代码", "开发"],
        "代码": ["代码", "编程", "程序"],
        "Python": ["Python", "编程", "代码"],
        "机器学习": ["机器学习", "ML", "AI"],
        "深度学习": ["深度学习", "神经网络", "AI"],
        "优化": ["优化", "性能", "改进"],
        "调试": ["调试", "错误", "问题"],
        "测试": ["测试", "验证", "检查"],
        "部署": ["部署", "发布", "上线"],
        "数据库": ["数据库", "存储", "SQL"],
        "API": ["API", "接口", "服务"],
        "前端": ["前端", "UI", "界面"],
        "后端": ["后端", "服务", "服务端"],
    }
    
    def generate_tags(self, content: str) -> List[str]:
        """
        从内容生成标签
        
        Args:
            content: 文本内容
            
        Returns:
            生成的标签列表
        """
        if not content:
            return []
        
        tags = set()
        
        # 提取中文关键词（2-4个字的词）
        chinese_words = re.findall(r'[\u4e00-\u9fff]{2,4}', content)
        for word in chinese_words:
            if len(word) >= 2:
                tags.add(word)
        
        # 提取英文关键词（单词，长度>2）
        english_words = re.findall(r'[a-zA-Z]{3,}', content)
        for word in english_words:
            tags.add(word)
        
        # 匹配预定义关键词模式
        for keyword, related_tags in self.KEYWORD_PATTERNS.items():
            if keyword in content:
                tags.update(related_tags)
        
        # 限制标签数量
        return list(tags)[:10]
    
    def generate_source_tags(self, source: ContextSource) -> List[str]:
        """
        根据来源生成标签
        
        Args:
            source: 上下文来源
            
        Returns:
            来源标签列表
        """
        return self.SOURCE_TAGS.get(source, [])
    
    def merge_tags(self, existing_tags: List[str], new_tags: List[str]) -> List[str]:
        """
        合并标签，去重
        
        Args:
            existing_tags: 现有标签
            new_tags: 新标签
            
        Returns:
            合并后的标签列表
        """
        # 使用集合去重
        tag_set: Set[str] = set(existing_tags)
        tag_set.update(new_tags)
        
        # 转换为列表并排序（保持一致性）
        return sorted(list(tag_set))
    
    def auto_tag(self, context: ContextInput) -> ContextInput:
        """
        自动为 ContextInput 生成标签
        
        Args:
            context: 上下文输入
            
        Returns:
            添加了标签的上下文输入（新对象）
        """
        # 生成内容标签
        content_tags = self.generate_tags(context.content)
        
        # 生成来源标签
        source_tags = self.generate_source_tags(context.source)
        
        # 合并标签
        all_tags = self.merge_tags(context.tags, content_tags + source_tags)
        
        # 创建新的 ContextInput（避免修改原对象）
        return ContextInput(
            source=context.source,
            content=context.content,
            priority=context.priority,
            metadata=context.metadata,
            tokens=context.tokens,
            tags=all_tags,
            hash=context.hash,
            created_at=context.created_at,
            updated_at=context.updated_at,
        )