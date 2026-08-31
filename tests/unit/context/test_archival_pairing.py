"""
P1-1① 期① 收尾 — orchestrator 写入侧归档打标测试

_archive_conversation_to_pool：
- user/assistant → CONVERSATION 源 + turn_id
- role=tool → TOOL_CALL 源 + pairs_with=当前轮（配对锚点）
- 池内配对闭合：draw 出口不产生孤儿
"""

import pytest

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.pool_models import ContextSource


def _make_orchestrator():
    from unittest.mock import MagicMock

    mock_agent = MagicMock()
    mock_agent.config = MagicMock()
    mock_agent.config.name = "t-agent"
    mock_agent.conversation_history = []
    orchestrator = ContextOrchestrator(mock_agent)
    return orchestrator


def _conversation_with_tool_result():
    return [
        {"role": "user", "content": "查一下北京天气"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "北京晴，26 度"},
        {"role": "assistant", "content": "北京今天晴，26 度。"},
    ]


class TestArchiveConversationToPool:
    def test_tool_message_archived_as_tool_call_with_pairs_with(self):
        orch = _make_orchestrator()
        orch._archive_conversation_to_pool(_conversation_with_tool_result())

        tool_chunks = [
            c for c in orch.context_pool.get_contexts()
            if c.source == ContextSource.TOOL_CALL
        ]
        assert len(tool_chunks) == 1
        chunk = tool_chunks[0]
        assert chunk.content == "北京晴，26 度"
        assert chunk.metadata["pairs_with"] == "turn_1"
        assert chunk.metadata["tool_call_id"] == "c1"

    def test_conversation_messages_tagged_with_turn_id(self):
        orch = _make_orchestrator()
        orch._archive_conversation_to_pool(_conversation_with_tool_result())

        convs = [
            c for c in orch.context_pool.get_contexts()
            if c.source == ContextSource.CONVERSATION
        ]
        turns = {c.metadata["turn_id"] for c in convs}
        assert turns == {"turn_1"}
        roles = {c.metadata["role"] for c in convs}
        assert roles == {"user", "assistant"}

    def test_second_user_message_opens_second_turn(self):
        orch = _make_orchestrator()
        msgs = _conversation_with_tool_result() + [
            {"role": "user", "content": "那上海呢"},
        ]
        orch._archive_conversation_to_pool(msgs)

        turns = {
            c.metadata["turn_id"]
            for c in orch.context_pool.get_contexts()
            if c.metadata.get("role") == "user"
        }
        assert turns == {"turn_1", "turn_2"}

    def test_pool_draw_no_orphan_for_paired_tool_result(self):
        """归档-调取闭环：配对完整时 draw 出口不剔除任何条目"""
        orch = _make_orchestrator()
        orch._archive_conversation_to_pool(_conversation_with_tool_result())

        view = orch.context_pool.draw()

        sources = [c.source for c in view]
        tool_count = sources.count(ContextSource.TOOL_CALL)
        assert tool_count == 1  # 配对完整 → 工具结果保留在视图


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
