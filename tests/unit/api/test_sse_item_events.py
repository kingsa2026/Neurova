# -*- coding: utf-8 -*-
"""P1-1 SSE 事件 item 化映射器（Codex item 语义对齐）。

- 事件形态：{type: item_started|item_delta|item_completed, thread_id, turn_id,
  item_id, item_type, data}
- content/reasoning delta → agent_message/reasoning item 的 started(首片)+delta
- tool_call → item_started(tool_call)；tool_result → item_completed(tool_result)
- done/stopped/error 收口所有未闭合 item（Codex ItemCompleted 语义）
- 旧事件流零改动（本映射器是旁路增强，compat 别名=旧事件原样保留）
"""
import pytest

from neurova.api.endpoints.sse_items import ItemEventMapper


class TestItemEventMapper:
    def test_message_delta_lifecycle(self):
        m = ItemEventMapper(thread_id="sess-1", turn_id="t1")
        ev1 = m.on_legacy_events([{"type": "chunk", "content": "你好"}])
        ev2 = m.on_legacy_events([{"type": "chunk", "content": "，世界"}])
        ev3 = m.on_legacy_events([{"type": "done", "session_id": "sess-1"}])

        assert ev1[0]["type"] == "item_started"
        assert ev1[0]["item_type"] == "agent_message"
        assert ev1[0]["thread_id"] == "sess-1"
        assert ev1[0]["turn_id"] == "t1"
        assert ev1[0]["data"] == {"text": "你好"}
        item_id = ev1[0]["item_id"]

        assert ev2[0]["type"] == "item_delta"
        assert ev2[0]["item_id"] == item_id
        assert ev2[0]["data"] == {"text": "，世界"}

        closes = [e for e in ev3 if e["type"] == "item_completed"]
        assert len(closes) == 1 and closes[0]["item_id"] == item_id

    def test_reasoning_item_separate_from_message(self):
        m = ItemEventMapper(thread_id="s", turn_id="t")
        m.on_legacy_events([{"type": "chunk", "content": "answer"}])
        ev = m.on_legacy_events([{"type": "reasoning", "content": "thinking"}])
        started = [e for e in ev if e["type"] == "item_started"]
        assert started and started[0]["item_type"] == "reasoning"
        # reasoning 开启不应关闭 agent_message（两者可交错）
        assert not any(e["type"] == "item_completed" for e in ev)

    def test_tool_call_started_result_completed(self):
        m = ItemEventMapper(thread_id="s", turn_id="t")
        start = m.on_legacy_events(
            [{"type": "tool_call", "name": "web_search", "arguments": "{}"}]
        )
        assert start[0]["type"] == "item_started"
        assert start[0]["item_type"] == "tool_call"
        assert start[0]["data"]["name"] == "web_search"

        # 工具调用开启会收口未完成的 message/reasoning（Codex 语义）
        m.on_legacy_events([{"type": "chunk", "content": "prefix"}])
        start2 = m.on_legacy_events(
            [{"type": "tool_call", "name": "file_read", "arguments": "{}"}]
        )
        assert any(
            e["type"] == "item_completed" and e["item_type"] == "agent_message"
            for e in start2
        )

        done = m.on_legacy_events(
            [{"type": "tool_result", "name": "file_read", "result": "content"}]
        )
        completed = [e for e in done if e["type"] == "item_completed"]
        assert completed and completed[0]["item_type"] == "tool_result"
        assert completed[0]["data"]["result"] == "content"

    def test_stop_and_error_close_open_items(self):
        for terminal in ({"type": "stopped", "session_id": "s"}, {"type": "error", "message": "x"}):
            m = ItemEventMapper(thread_id="s", turn_id="t")
            m.on_legacy_events([{"type": "chunk", "content": "half"}])
            ev = m.on_legacy_events([terminal])
            assert any(
                e["type"] == "item_completed" and e["item_type"] == "agent_message"
                for e in ev
            )

    def test_passthrough_kinds_ignored(self):
        m = ItemEventMapper(thread_id="s", turn_id="t")
        assert m.on_legacy_events(
            [
                {"type": "usage", "total_tokens": 10},
                {"type": "memory_progress"},
                {"type": "retry", "wait_seconds": 1},
                {"type": "approval_required"},
                {"type": "artifact", "path": "x"},
            ]
        ) == []

    def test_item_ids_unique_and_stable(self):
        m = ItemEventMapper(thread_id="s", turn_id="t")
        ev1 = m.on_legacy_events([{"type": "chunk", "content": "a"}])
        ev2 = m.on_legacy_events([{"type": "chunk", "content": "b"}])
        assert ev1[0]["item_id"] == ev2[0]["item_id"]
        start = m.on_legacy_events([{"type": "tool_call", "name": "x", "arguments": "{}"}])
        # tool_call 先收口 message（close 在前），自身 started 在最后
        assert start[-1]["item_id"] != ev1[0]["item_id"]
        assert start[-1]["item_type"] == "tool_call"

    def test_malformed_event_ignored(self):
        m = ItemEventMapper(thread_id="s", turn_id="t")
        assert m.on_legacy_events(["not-a-dict", {}, None]) == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
