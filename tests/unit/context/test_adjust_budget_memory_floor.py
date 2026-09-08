# -*- coding: utf-8 -*-
"""遗留①（2026-09-08 审计登记）：_adjust_budget 小记忆预算公式。

病理：memory_budget = int(memory_estimate × compression_ratio)，当记忆整体
占比很小时（如 15 tokens vs 48000 历史预算），比例缩放把预算压到记忆自身
token 以下 → _build_memory_context 把记忆截成几个字符——截断腾出的量被
历史预算吞掉，零收益纯损毁。

修复语义：记忆整体 ≤ max_tokens/10（小占比）时保持自身预算不被缩水；
超大记忆（>10%）按比例缩放但不低于 max_tokens/10 的下限。
"""

import pytest
from unittest.mock import MagicMock

from neurova.context.injector import UnifiedContextInjector
from neurova.context.models import TokenBudget


def _cn_tokens(inj: UnifiedContextInjector, text: str) -> int:
    return inj._count_tokens(text)


class TestAdjustBudgetSmallMemoryFloor:
    """小占比记忆不得被比例缩放压到自身 token 以下。"""

    def _make(self, max_total: int = 16000) -> UnifiedContextInjector:
        return UnifiedContextInjector(
            memory_manager=MagicMock(),
            token_budget=TokenBudget(max_total=max_total, memories=4000, conversation_history=6000),
            enable_cache=False,
            enable_compression=True,
        )

    def test_tiny_memory_budget_at_least_own_estimate(self):
        """15-token 记忆在大历史下 ratio≈0.85 → int(15×0.856)=12 < 15（红）。"""
        inj = self._make()
        history = [
            {"role": "user", "content": "历史消息内容填充" * 20} for _ in range(150)
        ]  # ≈14400 tokens → total_needed > 0.9×max → 缩放分支触发
        memories = [{"content": "喜欢简洁回复", "temperature": 80}]
        mem_estimate = sum(_cn_tokens(inj, m["content"]) for m in memories)
        budget = inj._adjust_budget(history, memories, 16000)
        assert budget.memories >= mem_estimate, (
            f"memory_budget={budget.memories} < 记忆自身 {mem_estimate} tokens（小记忆被截成碎屑）"
        )

    def test_end_to_end_tiny_memory_not_truncated(self):
        """端到端：大历史+小记忆场景，信封里保留完整记忆原文。"""
        inj = self._make()
        history = [
            {"role": "user", "content": "历史消息内容填充" * 20} for _ in range(150)
        ]
        result = inj.build_context(
            system_prompt="系统提示",
            memories=[{"content": "用户偏好：喜欢简洁回复", "temperature": 80}],
            conversation_history=history,
            user_input="当前问题",
        )
        user_msg = result.context[-1]["content"]
        assert "用户偏好：喜欢简洁回复" in user_msg, (
            f"小记忆被截断：{user_msg[:200]!r}"
        )
        assert "[已截断]" not in user_msg.split("</memories>")[0], "memories 块内出现截断标记"

    def test_huge_memory_still_scaled(self):
        """超大记忆（>10% 窗口）仍按比例缩放并设下限——不为保记忆牺牲总量。"""
        inj = self._make()
        history = [
            {"role": "user", "content": "历史消息内容填充" * 20} for _ in range(150)
        ]
        big = "超大记忆内容" * 300  # 远超 1600 tokens
        memories = [{"content": big, "temperature": 80}]
        budget = inj._adjust_budget(history, memories, 16000)
        assert budget.memories < 16000 // 2, "超大记忆未被缩放"
        assert budget.memories >= 16000 // 10, "缩放后低于 max/10 下限（过度缩水）"
