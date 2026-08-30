"""
P1-1① 上下文管线期① — 溢出恢复纯函数测试

compact_messages_for_overflow：把超窗消息折叠为可重试的紧凑序列。
折叠策略（对标 QP scroll 语义，单次恢复）：
- 保留全部 system 消息（角色契约）
- 保留第一条 user 消息（任务锚点）
- 保留末尾 recent_keep 条（近期上下文完整）
- 中段整体折叠为一条恢复桩；工具轮（assistant tool_calls + 其后 tool 结果）
  必须整轮同进同出——不留孤儿 tool 消息（破坏 API 协议）
"""

import pytest

from neurova.context.recovery import (
    assign_turn_ids,
    compact_messages_for_overflow,
    is_context_overflow_error,
)


def _sys(content="you are helpful"):
    return {"role": "system", "content": content}


def _user(content):
    return {"role": "user", "content": content}


def _assistant(content="", tool_calls=None):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tool(call_id, content="result"):
    return {"role": "tool", "tool_call_id": call_id, "content": content}


def _turn(i):
    """一轮完整工具轮：user → assistant(tool_calls) → tool → assistant(答复)"""
    return [
        _user(f"question {i}"),
        _assistant(tool_calls=[{"id": f"c{i}", "type": "function", "function": {"name": "t", "arguments": "{}"}}]),
        _tool(f"c{i}", f"result {i}"),
        _assistant(f"answer {i}"),
    ]


class TestAssignTurnIds:
    def test_user_message_opens_turn(self):
        msgs = [_user("q1"), _assistant("a1"), _user("q2"), _assistant("a2")]
        tagged = assign_turn_ids(msgs)
        assert [t for _, t in tagged] == ["turn_1", "turn_1", "turn_2", "turn_2"]

    def test_leading_assistant_gets_turn_1(self):
        tagged = assign_turn_ids([_assistant("hi"), _user("q")])
        assert [t for _, t in tagged] == ["turn_1", "turn_1"]

    def test_empty_messages(self):
        assert assign_turn_ids([]) == []


class TestIsContextOverflowError:
    def test_token_limit_error_type(self):
        from neurova.llm_client import TokenLimitExceeded

        assert is_context_overflow_error(TokenLimitExceeded("ctx too long")) is True

    def test_provider_message_variants(self):
        for msg in (
            RuntimeError("This model's maximum context length is 8192 tokens"),
            RuntimeError("request too large: too many tokens"),
            RuntimeError("context_length_exceeded"),
        ):
            assert is_context_overflow_error(msg) is True

    def test_unrelated_errors_not_matched(self):
        assert is_context_overflow_error(RuntimeError("rate limited")) is False
        assert is_context_overflow_error(ValueError("boom")) is False


class TestCompactMessagesForOverflow:
    def test_preserves_system_first_user_and_recent(self):
        msgs = [_sys()] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        compact, info = compact_messages_for_overflow(msgs, recent_keep=6)
        # system 在首位；第一条 user（任务锚点）保留；末尾 6 条完整保留
        assert compact[0]["role"] == "system"
        assert compact[1] == _user("question 1")
        assert compact[-6:] == msgs[-6:]
        assert info["folded_count"] > 0

    def test_recovery_stub_marks_folding(self):
        msgs = [_sys()] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        compact, _ = compact_messages_for_overflow(msgs, recent_keep=6)
        stubs = [m for m in compact if m.get("role") == "user" and "折叠" in str(m.get("content", ""))]
        assert len(stubs) == 1

    def test_no_orphan_tool_messages(self):
        """协议完整性：任何 tool 消息的前驱必须是带 tool_calls 的 assistant。"""
        msgs = [_sys()] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        compact, _ = compact_messages_for_overflow(msgs, recent_keep=6)
        for idx, msg in enumerate(compact):
            if msg.get("role") == "tool":
                prev = compact[idx - 1]
                assert prev.get("role") == "assistant" and prev.get("tool_calls"), (
                    f"孤儿 tool 消息 @ {idx}: {msg}"
                )

    def test_tool_call_id_uniqueness_preserved(self):
        """折叠后保留区的 tool_call_id 不得与桩区冲突（API 严格校验 id 关联）。"""
        msgs = [_sys()] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        compact, _ = compact_messages_for_overflow(msgs, recent_keep=6)
        kept_ids = [
            tc.get("id")
            for m in compact
            for tc in (m.get("tool_calls") or [])
        ]
        assert len(kept_ids) == len(set(kept_ids))

    def test_already_small_sequence_unchanged(self):
        msgs = [_sys(), _user("q"), _assistant("a")]
        compact, info = compact_messages_for_overflow(msgs, recent_keep=6)
        assert compact == msgs and info["folded_count"] == 0

    def test_recovery_info_structure(self):
        msgs = [_sys()] + _turn(1) + _turn(2) + _turn(3) + _turn(4)
        compact, info = compact_messages_for_overflow(msgs, recent_keep=6)
        assert set(info) >= {"folded_count", "original_count", "compact_count"}
        assert info["original_count"] == len(msgs)
        assert info["compact_count"] == len(compact)
        assert len(compact) < len(msgs)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
