# -*- coding: utf-8 -*-
"""P0-2 计量域卡：窗口计量的模型溢出保证金透传 + 载荷分桶。

契约（先红后绿，本文件先红）：

1. `estimate_window_tokens` / `WindowTokenMeter` / `estimateContextTokens` 接受
   `model_id`，对该模型的溢出保证金生效（同文本估值更高）；保证金只经
   `estimate_tokens(model_id=...)` 单源作用于**载荷**，协议开销
   `PER_MSG_OVERHEAD` 是常数，不参与放大；
2. 缺省（无 `model_id`）行为逐字节不变；
3. `messagePayloadBreakdown` 把一条消息的载荷按结构分桶
   （content / tool_calls / reasoning / other），桶间不重复计数，
   合计 == `messagePayloadTokens` 口径；`WindowTokenMeter.breakdown(msgs)`
   逐桶累计，与逐条分桶之和一致（无第二套算法）；
4. 预算报告（`budget_report`）增量带出分桶读数 `payload_buckets`，
   不破坏既有键。
"""

import json
import math

import pytest

from neurova.context.token_estimator import (
    estimate_tokens,
    getModelSafetyMargin,
    recordModelOverflow,
    resetModelSafetyMargins,
)
from neurova.context.window_compactor import (
    IMAGE_PART_TOKENS,
    PER_MSG_OVERHEAD,
    WindowTokenMeter,
    estimate_window_tokens,
    messagePayloadBreakdown,
    messagePayloadTokens,
)

MODEL = "test-model/window-meter-breakdown"

ZERO_BUCKETS = {"content": 0, "tool_calls": 0, "reasoning": 0, "other": 0}


def setup_function(_):
    resetModelSafetyMargins()


def _window():
    """混合形状窗口：正文 / 纯工具调用 / 工具回执 / 带 reasoning 的 assistant。"""
    return [
        {"role": "system", "content": "系统提示词"},
        {"role": "user", "content": "用户正文内容"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "run_code", "arguments": '{"code": "print(1)"}'},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "200 OK"},
        {"role": "assistant", "content": "带推理的正文", "reasoning_content": "内部推理草稿"},
    ]


class TestModelMarginAppliesToWindowMeter:
    def test_margin_amplifies_window_estimate(self):
        """同文本：模型有溢出保证金时，窗口估值必须更高。"""
        msgs = _window()
        base = estimate_window_tokens(msgs)
        recordModelOverflow(MODEL)  # margin = 1.25
        assert getModelSafetyMargin(MODEL) == pytest.approx(1.25)
        margined = estimate_window_tokens(msgs, model_id=MODEL)
        assert margined > base, (
            f"model_id 保证金未生效：带保证金 {margined} <= 基线 {base}"
        )

    def test_overhead_constant_not_amplified(self):
        """PER_MSG_OVERHEAD 是协议开销常数：不参与保证金放大。

        单条极小消息下精确钉死：期望 = ceil(载荷×1.25) + 开销原值；
        若开销被一起放大，读数会多出 ceil(4×1.25)-4 = 1。
        """
        msgs = [{"role": "user", "content": "x"}]
        recordModelOverflow(MODEL)
        expected = math.ceil(estimate_tokens("x") * 1.25) + PER_MSG_OVERHEAD
        assert estimate_window_tokens(msgs, model_id=MODEL) == expected, (
            "协议开销被保证金放大（应只放大载荷）"
        )

    def test_meter_uses_same_margin_as_stateless_entry(self):
        msgs = _window()
        recordModelOverflow(MODEL)
        meter = WindowTokenMeter(model_id=MODEL)
        assert meter.total(msgs) == estimate_window_tokens(msgs, model_id=MODEL)
        for msg in msgs:
            assert meter.one(msg) == estimate_window_tokens([msg], model_id=MODEL)

    def test_estimate_context_tokens_passthrough(self):
        from neurova.context_pool import estimateContextTokens

        msgs = _window()
        recordModelOverflow(MODEL)
        with_margin = estimateContextTokens(msgs, model_id=MODEL)
        assert with_margin == estimate_window_tokens(msgs, model_id=MODEL)
        assert with_margin > estimateContextTokens(msgs), "透传后保证金未生效"


class TestDefaultBehaviorUnchanged:
    def test_no_model_id_window_estimate_unchanged(self):
        """无 model_id：估值 = Σ(正文 + tool_calls 原文) + 条数×开销，逐字节不变。"""
        msgs = [m for m in _window() if not m.get("reasoning_content")]
        expected = 0
        for m in msgs:
            payload = estimate_tokens(m.get("content") or "")
            if m.get("tool_calls"):
                payload += estimate_tokens(json.dumps(m["tool_calls"], ensure_ascii=False))
            expected += payload + PER_MSG_OVERHEAD
        assert estimate_window_tokens(msgs) == expected
        assert estimate_window_tokens(msgs, model_id=None) == expected

    def test_estimate_context_tokens_default_identical(self):
        from neurova.context_pool import estimateContextTokens

        msgs = _window()
        assert estimateContextTokens(msgs) == estimate_window_tokens(msgs)
        assert estimateContextTokens(msgs, model_id=None) == estimateContextTokens(msgs)

    def test_messages_without_reasoning_field_payload_unchanged(self):
        """不带 reasoning 字段的消息：载荷口径与既有派生逐字节一致。"""
        for m in _window():
            if m.get("reasoning_content"):
                continue
            expected = estimate_tokens(m.get("content") or "")
            if m.get("tool_calls"):
                expected += estimate_tokens(json.dumps(m["tool_calls"], ensure_ascii=False))
            assert messagePayloadTokens(m) == expected, f"既有载荷口径被改动：{m.get('role')}"


class TestPayloadBreakdown:
    def test_bucket_keys_and_sum_equal_payload(self):
        """分桶键固定，且每条消息桶合计 == messagePayloadTokens 口径。"""
        for m in _window():
            buckets = messagePayloadBreakdown(m)
            assert set(buckets) == {"content", "tool_calls", "reasoning", "other"}
            assert sum(buckets.values()) == messagePayloadTokens(m), (
                f"分桶合计与总口径不一致：{m.get('role')} {buckets}"
            )

    def test_pure_tool_call_message_buckets(self):
        """纯工具调用消息（content 为空）：载荷归 tool_calls 桶，其余桶为零。"""
        call = _window()[2]
        buckets = messagePayloadBreakdown(call)
        assert buckets["content"] == 0
        assert buckets["tool_calls"] > 0
        assert buckets["reasoning"] == 0
        assert buckets["other"] == 0
        assert buckets["tool_calls"] == estimate_tokens(
            json.dumps(call["tool_calls"], ensure_ascii=False)
        )

    def test_reasoning_bucketed_without_double_count(self):
        """reasoning 字段存在时归 reasoning 桶，且不与 content 重复计数。"""
        m = _window()[4]
        buckets = messagePayloadBreakdown(m)
        assert buckets["reasoning"] == estimate_tokens("内部推理草稿")
        assert buckets["content"] == estimate_tokens("带推理的正文")
        assert buckets["tool_calls"] == 0
        assert sum(buckets.values()) == messagePayloadTokens(m)

    def test_multimodal_image_fixed_price_goes_to_other(self):
        """图像段固定计价归 other 桶（不按 URL 字符数计）。"""
        m = {
            "role": "user",
            "content": [
                {"type": "text", "text": "看图"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
            ],
        }
        buckets = messagePayloadBreakdown(m)
        assert buckets["content"] == estimate_tokens("看图")
        assert buckets["other"] == IMAGE_PART_TOKENS
        assert sum(buckets.values()) == messagePayloadTokens(m)

    def test_empty_message_all_buckets_zero(self):
        """空消息与空窗口：全零桶，不抛错。"""
        assert messagePayloadBreakdown({}) == ZERO_BUCKETS
        assert messagePayloadBreakdown({"role": "user", "content": ""}) == ZERO_BUCKETS
        assert estimate_window_tokens([]) == 0
        assert WindowTokenMeter().breakdown([]) == ZERO_BUCKETS

    def test_meter_breakdown_aggregates_window(self):
        """meter.breakdown 逐桶累计 == 逐条分桶之和（无第二套算法），
        且桶合计 + 条数×协议开销 == 整窗估值。"""
        msgs = _window()
        aggregated = WindowTokenMeter().breakdown(msgs)
        per_message = [messagePayloadBreakdown(m) for m in msgs]
        for name in ZERO_BUCKETS:
            assert aggregated[name] == sum(b[name] for b in per_message), (
                f"meter 分桶与逐条分桶不一致：{name}"
            )
        assert estimate_window_tokens(msgs) == (
            sum(aggregated.values()) + len(msgs) * PER_MSG_OVERHEAD
        )


class TestBudgetReportBuckets:
    def test_record_context_budget_carries_buckets(self):
        """recordContextBudget 增量带出 payload_buckets，既有键不破坏。"""
        from neurova.context.budget_report import (
            getContextBudget,
            recordContextBudget,
            resetContextBudget,
        )

        resetContextBudget()
        try:
            msgs = _window()
            report = recordContextBudget("agent-bucket", {"soul": "s" * 10}, messages=msgs)
            assert report["payload_buckets"] == WindowTokenMeter().breakdown(msgs)
            # 既有键全部保留
            assert report["total_chars"] == 10
            assert {
                "measured_at",
                "total_chars",
                "system_cap",
                "over_budget",
                "over_segment_caps",
                "segments",
                "agent_id",
            } <= set(report)
            stored = getContextBudget("agent-bucket")
            assert stored is not None
            assert stored["payload_buckets"] == report["payload_buckets"]
        finally:
            resetContextBudget()

    def test_budget_report_without_messages_zero_shape(self):
        """不传 messages：既有调用面拿到稳定的全零桶，不报错。"""
        from neurova.context.budget_report import buildAlwaysOnBudgetReport

        report = buildAlwaysOnBudgetReport({"soul": "abc"})
        assert report["payload_buckets"] == ZERO_BUCKETS
        assert report["total_chars"] == 3

    def test_budget_report_buckets_apply_margin(self):
        """分桶读数同样吃 model_id 保证金（载荷桶放大，口径与判据一致）。"""
        from neurova.context.budget_report import buildAlwaysOnBudgetReport

        msgs = _window()
        recordModelOverflow(MODEL)
        margined = buildAlwaysOnBudgetReport({"soul": "abc"}, messages=msgs, model_id=MODEL)
        plain = buildAlwaysOnBudgetReport({"soul": "abc"}, messages=msgs)
        assert margined["payload_buckets"] == WindowTokenMeter(model_id=MODEL).breakdown(msgs)
        assert sum(margined["payload_buckets"].values()) > sum(plain["payload_buckets"].values())
