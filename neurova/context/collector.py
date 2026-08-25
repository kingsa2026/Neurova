from __future__ import annotations

"""
上下文收集器 - Context Collector

负责收集、排序和预算控制上下文输入。
"""

from neurova.core.logger import get_logger
from typing import List

from neurova.context.pool_models import ContextInput

logger = get_logger(__name__)


class ContextCollector:
    """上下文收集器"""

    def __init__(self, max_tokens: int = 16000):
        self.max_tokens = max_tokens
        self._contexts: List[ContextInput] = []

    def add_context(self, context: ContextInput):
        if context.tokens == 0:
            context.tokens = self._estimate_tokens(context.content)
        self._contexts.append(context)

    def collect(self) -> List[ContextInput]:
        # [归档完整性] collect() 返回全部条目且绝不截断内容：
        # 上下文池的定位是无损归档（活水），裁剪只允许发生在"视图层"（Drawer
        # 整条选取），归档本身永不被裁剪/压缩。
        return sorted(self._contexts, key=lambda x: (-x.priority, x.tokens))

    def collect_by_source(self, source) -> List[ContextInput]:
        return [ctx for ctx in self._contexts if ctx.source == source]

    def _apply_token_budget(self, contexts: List[ContextInput]) -> List[ContextInput]:
        result = []
        total_tokens = 0

        for ctx in contexts:
            if total_tokens + ctx.tokens <= self.max_tokens:
                result.append(ctx)
                total_tokens += ctx.tokens
            else:
                remaining_tokens = self.max_tokens - total_tokens
                if remaining_tokens > 0:
                    char_limit = int(remaining_tokens * 1.5)
                    truncated_content = ctx.content[:char_limit]
                    truncated_ctx = ContextInput(
                        source=ctx.source,
                        content=truncated_content,
                        priority=ctx.priority,
                        metadata=ctx.metadata,
                        tokens=remaining_tokens,
                    )
                    result.append(truncated_ctx)
                break

        return result

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        from neurova.context.token_estimator import EstimationStrategy, TokenEstimator
        estimator = TokenEstimator(EstimationStrategy.BALANCED)
        return estimator.estimate(text)
