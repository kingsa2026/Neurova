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
from datetime import datetime
from typing import Any, Dict, List

from neurova.context.token_estimator import EstimationStrategy, TokenEstimator

logger = logging.getLogger(__name__)


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
        ttl_seconds: int = 3600,
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

    def add_context(self, context):
        if self.auto_tag and hasattr(self, "_auto_tagger"):
            context = self._auto_tagger.auto_tag(context)

        if hasattr(self, "max_size") and self.max_size > 0:
            current_size = len(self._collector._contexts)
            if current_size >= self.max_size:
                self._collector._contexts.pop(0)

        self._collector.add_context(context)
        self._cache_version += 1

    def get_contexts(self) -> List:
        contexts = self._collector.collect()

        if hasattr(self, "ttl_seconds") and self.ttl_seconds > 0:
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
        if not hasattr(self, "ttl_seconds") or self.ttl_seconds <= 0:
            return 0

        now = datetime.now()
        original_count = len(self._collector._contexts)

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

        for model_pattern, budget in model_budgets.items():
            if model_pattern in model_name.lower():
                return budget

        return default_budget

    def get_token_budget_for_capabilities(self, capabilities: list) -> int:
        try:
            from neurova.llm.llm_router import ModelCapability
        except ImportError:
            logger.debug("ModelCapability 延迟导入失败，使用默认预算")
            return 16000

        base_budget = 16000

        if ModelCapability.VISION in capabilities:
            base_budget += 16000
        if ModelCapability.AUDIO in capabilities:
            base_budget += 8000
        if ModelCapability.VIDEO in capabilities:
            base_budget += 32000
        if ModelCapability.MULTIMODAL in capabilities:
            base_budget += 16000

        return base_budget

    def build_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        cache_key = f"{self.isolation_key}:{model_name}"
        if cache_key in self._cache and self._last_build_version == self._cache_version:
            return self._cache[cache_key]

        contexts = self.get_contexts()

        messages = []
        for ctx in contexts:
            msg = self._converter.convert_for_model(ctx, model_name)
            messages.append(msg)

        self._cache[cache_key] = messages
        self._last_build_version = self._cache_version

        return messages

    def convert_context_for_model(self, model_name: str) -> List[Dict[str, Any]]:
        return self.build_context_for_model(model_name)

    def compress_context(self):
        contexts = self.get_contexts()
        compressed = self._compressor.compress(contexts)
        self._collector._contexts = compressed

    def merge_with(self, other_pool: "ContextPool"):
        other_contexts = other_pool.get_contexts()
        for ctx in other_contexts:
            self._collector.add_context(ctx)

    def draw(self, need: str = None) -> List:
        all_drops = self._collector.collect()
        deduped = self._deduplicator.dedup(all_drops, stage="output")
        return self._drawer.draw(deduped, need=need)

    def dedup(self, stage: str = "input") -> int:
        all_drops = self._collector.collect()
        deduped = self._deduplicator.dedup(all_drops, stage=stage)
        self._collector._contexts = deduped
        return len(deduped)


from neurova.context.pool_models import ContextSource, ContextInput
from neurova.context.collector import ContextCollector
from neurova.context.converter import ContextConverter
from neurova.context.compressor import ContextCompressor
from neurova.context.utils import ContextPoolUtils
from neurova.context.dedup import DriftSafeDeduplicator
from neurova.context.semantic_drawer import SemanticMatchDrawer
from neurova.context.auto_tagger import AutoTagger

__all__ = [
    "ContextSource",
    "ContextInput",
    "ContextPool",
    "ContextCollector",
    "ContextConverter",
    "ContextCompressor",
    "ContextPoolUtils",
    "DriftSafeDeduplicator",
    "SemanticMatchDrawer",
    "AutoTagger",
]
