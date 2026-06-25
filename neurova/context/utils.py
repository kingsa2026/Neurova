from __future__ import annotations

"""
上下文池工具函数 - Context Pool Utils

提供 Token 估算、上下文合并、按来源过滤等工具函数。
"""

from neurova.core.logger import get_logger
from typing import List

from neurova.context.pool_models import ContextInput, ContextSource
from neurova.context.token_estimator import EstimationStrategy, TokenEstimator

logger = get_logger(__name__)


class ContextPoolUtils:
    """上下文池工具函数"""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        estimator = TokenEstimator(EstimationStrategy.BALANCED)
        return estimator.estimate(text)

    @staticmethod
    def merge_contexts(*context_lists: List[ContextInput]) -> List[ContextInput]:
        merged = []
        for ctx_list in context_lists:
            merged.extend(ctx_list)
        return sorted(merged, key=lambda x: (-x.priority, x.tokens))

    @staticmethod
    def filter_by_source(contexts: List[ContextInput], source: ContextSource) -> List[ContextInput]:
        return [ctx for ctx in contexts if ctx.source == source]
