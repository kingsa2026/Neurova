# -*- coding: utf-8 -*-
"""B1-6 快赢四件回归测试（QwenPaw #7187/#6617/#7268/#7337 对齐）。

1. 标题生成剥思考内容：`<think>/<thinking>/<analysis>/<reasoning>` 块
   （含未闭合）不进入标题。
2. Retry-After 解析：整秒/小数/HTTP-date/非法 → float/None；
   report_429 接受服务端值（尊重服务端上限语义）。
3. 超时独立错误类别：ErrorCategory.TIMEOUT，TimeoutError/超时文本归
   TIMEOUT（不再混入 connection）。
4. 输出能力 vs 请求限制：get_model_output_capability（模型能输出多少）
   与 clamp_max_tokens（单次请求限额）分离；resolve_max_output_length
   用户覆盖优先（source=user_override），发现值不得覆盖用户配置。
"""
from __future__ import annotations

import asyncio

import pytest


class TestTitleStripThink:
    def test_strips_closed_think_block(self):
        from neurova.session_title import _clean_title

        assert _clean_title("<think>推理过程很长</think>真正的标题") == "真正的标题"

    def test_strips_unclosed_block(self):
        from neurova.session_title import _clean_title

        assert _clean_title("标题<think>未闭合的推理……").startswith("标题")

    def test_all_tag_variants(self):
        from neurova.session_title import _clean_title

        for tag in ("think", "thinking", "analysis", "reasoning"):
            out = _clean_title(f"<{tag}>x</{tag}>T{tag}")
            assert out == f"T{tag}", (tag, out)

    def test_fallback_title_strips_think(self):
        from neurova.session_title import fallback_title

        out = fallback_title("<thinking>思考内容</thinking>帮我写周报")
        assert "思考内容" not in out
        assert "周报" in out


class TestRetryAfter:
    def test_parse_integer_seconds(self):
        from neurova.llm.model_rate_limiter import parse_retry_after

        assert parse_retry_after("120") == 120.0

    def test_parse_decimal(self):
        from neurova.llm.model_rate_limiter import parse_retry_after

        assert parse_retry_after("3.5") == 3.5

    def test_parse_http_date(self):
        from neurova.llm.model_rate_limiter import parse_retry_after
        from email.utils import format_datetime
        from datetime import datetime, timezone, timedelta

        future = datetime.now(timezone.utc) + timedelta(seconds=90)
        val = parse_retry_after(format_datetime(future))
        assert val is not None
        assert 80 <= val <= 95

    def test_invalid_returns_none(self):
        from neurova.llm.model_rate_limiter import parse_retry_after

        assert parse_retry_after("soon") is None
        assert parse_retry_after("") is None
        assert parse_retry_after(None) is None

    def test_report_429_respects_retry_after(self):
        from neurova.llm.model_rate_limiter import ModelRateLimiter, parse_retry_after

        limiter = ModelRateLimiter()
        limiter.report_429("m1", pause_seconds=parse_retry_after("120"))
        remaining = limiter.pause_remaining("m1")
        assert 60 <= remaining <= 180  # 服务端值生效（±50% 抖动窗口）


class TestTimeoutCategory:
    def test_category_exists(self):
        from neurova.llm.providers.error_mapping import ErrorCategory

        assert ErrorCategory.TIMEOUT.value == "timeout"
        assert ErrorCategory.TIMEOUT.retryable is True

    def test_timeout_exception_normalized(self):
        from neurova.llm.providers.error_mapping import (
            ErrorCategory,
            normalize_provider_error,
        )

        err = normalize_provider_error(TimeoutError("request timed out"))
        assert err.category == ErrorCategory.TIMEOUT

    def test_timeout_message_normalized(self):
        from neurova.llm.providers.error_mapping import (
            ErrorCategory,
            normalize_provider_error,
        )

        err = normalize_provider_error(asyncio.TimeoutError())
        assert err.category == ErrorCategory.TIMEOUT

    def test_discovery_kind_maps_timeout(self):
        from neurova.llm.provider_manager import _classify_discovery_error_kind

        assert _classify_discovery_error_kind(TimeoutError("read timed out")) == "timeout"


class TestOutputCapabilityVsRequestLimit:
    def test_capability_lookup(self):
        from neurova.llm.model_limits import get_model_output_capability

        assert get_model_output_capability("gpt-4o") == 16384
        assert get_model_output_capability("deepseek-chat") == 8192

    def test_capability_unknown_is_none(self):
        from neurova.llm.model_limits import get_model_output_capability

        assert get_model_output_capability("totally-unknown-model") is None

    def test_resolve_user_override_wins(self):
        from neurova.llm.model_limits import resolve_max_output_length

        value, source = resolve_max_output_length("gpt-4o", user_override=8192)
        assert value == 8192
        assert source == "user_override"

    def test_resolve_catalog_fallback(self):
        from neurova.llm.model_limits import resolve_max_output_length

        value, source = resolve_max_output_length("gpt-4o")
        assert value == 16384
        assert source == "catalog"

    def test_resolve_unknown_honest(self):
        from neurova.llm.model_limits import resolve_max_output_length

        value, source = resolve_max_output_length("mystery-model")
        assert value is None
        assert source == "unknown"

    def test_request_limit_still_clamped(self):
        from neurova.llm.model_limits import clamp_max_tokens

        # 请求限额口径不变（与能力上限是两个维度）
        assert clamp_max_tokens(999_999, "gpt-4o") <= 32_768
