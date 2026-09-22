# -*- coding: utf-8 -*-
"""B5 规模：窗口折叠的 token 计量必须一趟算完（Issue #90 台账 §2 补充发现）。

红灯依据（改前实证）：`compact_window` 单次调用内对同一批文本重复计量约 **2.4×**
——`split_window_by_budget` 每轮重算整窗 + 逐条单算，而 `compact_window` 的
递进折叠循环（ratio 0.5→1.0）每轮又各来一遍。尺子换成 tiktoken 后单次折叠
约 20ms→75ms，长会话成倍放大。

契约（修复后）：

1. 单次折叠内每条消息的 token **只算一次**（计量次数与消息条数同阶，与递进轮数无关）；
2. `estimate_window_tokens` 的口径**唯一**：整窗值 == 逐条值之和 + 条数×协议开销，
   不存在"总量一份、逐条另一份"的第二套口径；
3. 折叠结果（dropped/kept 划分与 tokens_before/after 读数）与改前逐字相同。
"""

from __future__ import annotations

import typing

import pytest

from neurova.context import window_compactor
from neurova.context.window_compactor import (
    PER_MSG_OVERHEAD,
    WindowTokenMeter,
    compact_window,
    estimate_window_tokens,
    split_window_by_budget,
)


def _window(count: int, fill: str = "窗口消息内容填充") -> typing.List[dict]:
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"{fill}-{i}"}
        for i in range(count)
    ]


class CountingEstimator:
    """计数估算器：真估算器外包一层计数（判据是调用次数，不是结果）。"""

    def __init__(self):
        self.calls: typing.Dict[str, int] = {}
        from neurova.context.token_estimator import estimate_tokens

        self._real = estimate_tokens

    def __call__(self, text: str) -> int:
        self.calls[text] = self.calls.get(text, 0) + 1
        return self._real(text)

    @property
    def total_calls(self) -> int:
        return sum(self.calls.values())


class TestMeterComputesOncePerMessage:
    def test_total_equals_parts_plus_overhead(self):
        """口径唯一性：整窗计量 == Σ内容计量 + 条数×协议开销（无第二套算法）。"""
        from neurova.context.token_estimator import estimate_tokens

        msgs = _window(12)
        assert estimate_window_tokens(msgs) == (
            sum(estimate_tokens(m["content"]) for m in msgs) + len(msgs) * PER_MSG_OVERHEAD
        )

    def test_meter_memoizes_per_message(self):
        """同一批消息重复求值只算一次（meter 是一次调用内的记忆体）。"""
        estimator = CountingEstimator()
        meter = WindowTokenMeter(estimator)
        msgs = _window(10)

        first = meter.total(msgs)
        for _ in range(5):
            assert meter.total(msgs) == first
        for msg in msgs:
            meter.one(msg)

        # 每条消息内容只被真正计量一次
        assert set(estimator.calls.values()) == {1}, estimator.calls
        assert estimator.total_calls == len(msgs)

    def test_meter_agrees_with_module_function(self):
        msgs = _window(7)
        meter = WindowTokenMeter()
        assert meter.total(msgs) == estimate_window_tokens(msgs)
        for msg in msgs:
            assert meter.one(msg) == estimate_window_tokens([msg])


class TestCompactionMeterCallBudget:
    def test_single_compaction_metering_is_linear(self):
        """单次折叠内计量次数与消息条数同阶（不随递进轮数成倍放大）。"""
        estimator = CountingEstimator()
        meter = WindowTokenMeter(estimator)
        msgs = _window(40)

        split_window_by_budget(msgs, budget_tokens=200, keep_min_messages=4, meter=meter)

        # 40 条各一次 + 整窗一次以内的常数开销
        assert estimator.total_calls <= len(msgs) + 2, estimator.total_calls

    @pytest.mark.asyncio
    async def test_compact_window_reuses_meter_across_ratios(self):
        estimator = CountingEstimator()
        meter = WindowTokenMeter(estimator)
        msgs = _window(60)

        await compact_window(msgs, budget_tokens=120, summarize=None, keep_min_messages=6, meter=meter)

        assert estimator.total_calls <= len(msgs) + 2, (
            f"递进折叠各轮重复计量：{estimator.total_calls} 次 / {len(msgs)} 条"
        )

    @pytest.mark.asyncio
    async def test_compaction_result_unchanged_by_meter(self):
        """计量收敛不得改变折叠结果（dropped/kept 划分与读数逐字相同）。"""
        msgs = _window(40)

        without = await compact_window(msgs, budget_tokens=260, summarize=None, keep_min_messages=6)
        with_meter = await compact_window(
            msgs,
            budget_tokens=260,
            summarize=None,
            keep_min_messages=6,
            meter=WindowTokenMeter(),
        )

        assert without is not None and with_meter is not None
        assert [m["content"] for m in without.window] == [m["content"] for m in with_meter.window]
        assert without.compacted_count == with_meter.compacted_count
        assert without.tokens_before == with_meter.tokens_before
        assert without.tokens_after == with_meter.tokens_after

    def test_split_result_unchanged_by_meter(self):
        msgs = _window(30)
        plain_dropped, plain_kept = split_window_by_budget(msgs, budget_tokens=180, keep_min_messages=5)
        metered_dropped, metered_kept = split_window_by_budget(
            msgs, budget_tokens=180, keep_min_messages=5, meter=WindowTokenMeter()
        )
        assert [m["content"] for m in plain_dropped] == [m["content"] for m in metered_dropped]
        assert [m["content"] for m in plain_kept] == [m["content"] for m in metered_kept]


class TestOverheadIsSingleSourced:
    def test_overhead_exported_once(self):
        """协议开销只定义一处（模块常量），并对外可读——第二份口径即红。"""
        assert isinstance(PER_MSG_OVERHEAD, int) and PER_MSG_OVERHEAD > 0
        assert window_compactor.PER_MSG_OVERHEAD == PER_MSG_OVERHEAD
