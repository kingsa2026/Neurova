from __future__ import annotations

"""
上下文压缩器 - Context Compressor

负责压缩上下文列表以适应 Token 预算。
"""

import logging
from typing import List, Optional

from neurova.context.pool_models import ContextInput

logger = logging.getLogger(__name__)


class ContextCompressor:
    """上下文压缩器"""

    def __init__(self, max_tokens: int = 16000, enable_summarization: bool = False):
        self.max_tokens = max_tokens
        self.enable_summarization = enable_summarization

    def compress(self, contexts: List[ContextInput]) -> List[ContextInput]:
        for ctx in contexts:
            if ctx.tokens == 0:
                ctx.tokens = self._estimate_tokens(ctx.content)

        total_tokens = sum(ctx.tokens for ctx in contexts)

        if total_tokens <= self.max_tokens:
            return contexts

        sorted_contexts = sorted(contexts, key=lambda x: (-x.priority, x.tokens))

        result = []
        current_tokens = 0

        for ctx in sorted_contexts:
            if current_tokens + ctx.tokens <= self.max_tokens:
                result.append(ctx)
                current_tokens += ctx.tokens
            else:
                remaining_tokens = self.max_tokens - current_tokens
                if remaining_tokens > 0:
                    compressed_ctx = self._compress_context(ctx, remaining_tokens)
                    if compressed_ctx:
                        result.append(compressed_ctx)
                break

        return result

    def _compress_context(self, context: ContextInput, max_tokens: int) -> Optional[ContextInput]:
        if self.enable_summarization:
            summary = f"[摘要] {context.content[:max_tokens//2]}..."
            return ContextInput(
                source=context.source,
                content=summary,
                priority=context.priority,
                metadata=context.metadata,
                tokens=max_tokens,
            )
        else:
            truncated_content = context.content[:max_tokens]
            return ContextInput(
                source=context.source,
                content=truncated_content,
                priority=context.priority,
                metadata=context.metadata,
                tokens=max_tokens,
            )

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        from neurova.context.token_estimator import EstimationStrategy, TokenEstimator
        estimator = TokenEstimator(EstimationStrategy.BALANCED)
        return estimator.estimate(text)
