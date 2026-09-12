"""length 空回复的输出预算修复（真机问题：思考模型吃满 max_tokens）

病根（修复前）：finish_reason=length 且正文为空时，恢复逻辑只压缩**输入**
消息后重试——但约束在**输出侧**（思考吃满 max_tokens），重试原样撞同一堵墙，
用户看到"压缩上下文重试后仍未产出正文"。

验收：
- length 空回复重试时同步放宽输出预算（max_tokens 翻倍、下限 +4096、上限 65536）
- 思考档位同步降级（thinking_enabled=False / effort→light / reasoning_effort→low）
- 输入能折叠仍折叠（原恢复能力保留）
- 重试仍空 → 兜底提示照旧产出
- 无任何可动旋钮（无 max_tokens/无思考档/无可折叠）→ 不重试（防循环）
"""

from unittest.mock import MagicMock

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop, _raised_output_budget


def make_loop():
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = MagicMock()
    return loop


class TestRaisedOutputBudget:
    def test_doubles_and_caps(self):
        assert _raised_output_budget(4096) == 8192
        assert _raised_output_budget(40000) == 65536, "上限 65536"
        assert _raised_output_budget(30000) == 60000

    def test_floor_bump_for_small_budget(self):
        assert _raised_output_budget(1024) == 8192, "小预算至少 +4096"

    def test_invalid_or_missing_defaults(self):
        assert _raised_output_budget(None) == 8192
        assert _raised_output_budget("abc") == 8192
        assert _raised_output_budget(0) == 8192


class TestLengthRetry:
    @pytest.fixture
    def compact_mock(self, monkeypatch):
        """折叠函数打桩：返回可折叠信息（真实函数依赖具体消息形态）"""
        import neurova.context.recovery as recovery

        compact_msgs = [{"role": "user", "content": "compact"}]
        monkeypatch.setattr(
            recovery,
            "compact_messages_for_overflow",
            lambda messages, recent_keep=6: (compact_msgs, {"folded_count": 2, "original_count": 5, "compact_count": 3}),
        )
        return compact_msgs

    def _run(self, loop, request_params, monkeypatch, second_call_events=None):
        """打桩 _predict_stream_once：第一次 length 空回复，第二次按脚本"""
        calls = []

        async def fake_once(self, params):
            calls.append(dict(params))
            if len(calls) == 1:
                yield {"type": "reasoning", "data": "思考…" * 100}
                yield {"type": "done", "reply": "", "finish_reason": "length"}
            else:
                for ev in (second_call_events or [{"type": "done", "reply": "", "finish_reason": "length"}]):
                    yield ev

        monkeypatch.setattr(OpenAILoop, "_predict_stream_once", fake_once)

        async def collect():
            events = []
            async for ev in loop._predict_stream(request_params):
                events.append(ev)
            return events

        import asyncio

        return calls, asyncio.get_event_loop_policy(), collect

    @pytest.mark.asyncio
    async def test_retry_raises_budget_and_degrades_thinking(self, monkeypatch, compact_mock):
        loop = make_loop()
        request_params = {
            "messages": [{"role": "user", "content": "x"}],
            "max_tokens": 4096,
            "thinking_effort": "deep",
        }
        calls = []

        async def fake_once(self, params):
            calls.append(dict(params))
            if len(calls) == 1:
                yield {"type": "reasoning", "data": "思考…" * 100}
                yield {"type": "done", "reply": "", "finish_reason": "length"}
            else:
                yield {"type": "done", "reply": "", "finish_reason": "length"}

        monkeypatch.setattr(OpenAILoop, "_predict_stream_once", fake_once)

        events = []
        async for ev in loop._predict_stream(request_params):
            events.append(ev)

        assert len(calls) == 2, "必须发生重试"
        retry = calls[1]
        assert retry["max_tokens"] == 8192, "输出预算必须放宽（4096→8192）——病根在输出侧"
        assert retry["thinking_enabled"] is False, "思考必须降级"
        assert retry["thinking_effort"] == "light"
        assert retry["_length_empty_retried"] is True
        assert retry["messages"] == compact_mock, "输入折叠保留（原恢复能力）"
        # 重试仍空 → 兜底提示产出（杜绝空气泡）
        contents = [e for e in events if e.get("type") == "content"]
        assert any("未能生成回复" in e.get("data", "") for e in contents)

    @pytest.mark.asyncio
    async def test_retry_success_produces_content_no_notice(self, monkeypatch, compact_mock):
        loop = make_loop()
        request_params = {"messages": [{"role": "user", "content": "x"}], "max_tokens": 2048}

        calls = []

        async def fake_once(self, params):
            calls.append(dict(params))
            if len(calls) == 1:
                yield {"type": "reasoning", "data": "思考…" * 200}
                yield {"type": "done", "reply": "", "finish_reason": "length"}
            else:
                yield {"type": "content", "data": "正文来了"}
                yield {"type": "done", "reply": "正文来了", "finish_reason": "stop"}

        monkeypatch.setattr(OpenAILoop, "_predict_stream_once", fake_once)

        events = []
        async for ev in loop._predict_stream(request_params):
            events.append(ev)

        assert len(calls) == 2
        assert calls[1]["max_tokens"] == 8192, "2048 → 下限抬升 2048+4096=6144，翻倍 4096 → 取 6144"
        assert calls[1]["thinking_enabled"] is False
        assert not any("未能生成回复" in str(e.get("data", "")) for e in events), "重试成功不出兜底提示"

    @pytest.mark.asyncio
    async def test_no_knobs_no_fold_no_retry(self, monkeypatch):
        """无 max_tokens、无思考档、无可折叠 → 不重试（防循环），原样透传"""
        loop = make_loop()
        request_params = {"messages": [{"role": "user", "content": "short"}]}

        import neurova.context.recovery as recovery

        monkeypatch.setattr(
            recovery,
            "compact_messages_for_overflow",
            lambda messages, recent_keep=6: (messages, {"folded_count": 0}),
        )

        calls = []

        async def fake_once(self, params):
            calls.append(dict(params))
            yield {"type": "reasoning", "data": "思考…"}
            yield {"type": "done", "reply": "", "finish_reason": "length"}

        monkeypatch.setattr(OpenAILoop, "_predict_stream_once", fake_once)

        async for _ in loop._predict_stream(request_params):
            pass
        assert len(calls) == 1, "没有可动旋钮时不得空转重试"
