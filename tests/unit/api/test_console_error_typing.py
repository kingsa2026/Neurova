# -*- coding: utf-8 -*-
"""P1-3 错误事件结构化分型（配额事件化）。

Codex 对齐（docs/Neurova_Codex代码级对比_2026-09-14.md §2.5/P1-3）：
- SSE error 事件携带 {error_kind, retryable}——分类走 model_error_policy 单源
  （既有可重试白名单：rate_limited/transient；配额/认证/参数不可重试）
- 配额类（rate_limited）额外发独立 quota_limited 事件（配额横幅引导换模型）
- 分类失败 fail-open：payload 为空 dict，不影响 error 事件本体
"""
import pytest

from neurova.api.endpoints.console import _error_event_payload


class TestErrorEventPayload:
    def test_rate_limited_retryable(self):
        payload = _error_event_payload("Error code: 429 - too many requests")
        assert payload["error_kind"] == "rate_limited"
        assert payload["retryable"] is True

    def test_auth_not_retryable(self):
        payload = _error_event_payload("Error: invalid api key")
        assert payload["error_kind"] == "authentication"
        assert payload["retryable"] is False

    def test_transient_retryable(self):
        payload = _error_event_payload("Request timed out after 30s")
        assert payload["error_kind"] == "transient"
        assert payload["retryable"] is True

    def test_bad_request_not_retryable(self):
        payload = _error_event_payload("Error code: 400 - invalid request body")
        assert payload["error_kind"] == "bad_request"
        assert payload["retryable"] is False

    def test_context_overflow_not_retryable(self):
        payload = _error_event_payload("maximum context length exceeded")
        assert payload["error_kind"] == "context_overflow"
        assert payload["retryable"] is False

    def test_empty_message_fail_open(self):
        assert _error_event_payload("") == {}
        assert _error_event_payload(None) == {}


class TestQuotaEventDecision:
    def test_rate_limited_triggers_quota_event(self):
        from neurova.api.endpoints.console import _should_emit_quota_event

        assert _should_emit_quota_event("Error code: 429 - quota exceeded") is True

    def test_other_kinds_do_not(self):
        from neurova.api.endpoints.console import _should_emit_quota_event

        assert _should_emit_quota_event("invalid api key") is False
        assert _should_emit_quota_event("") is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
