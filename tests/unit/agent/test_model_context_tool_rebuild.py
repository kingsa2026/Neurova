# -*- coding: utf-8 -*-
"""T-10b（R1）：会话库 → provider 合法模型上下文的专用读 API。

工单 §11.3 表 R1：`get_recent_context` 只回 `{role, content}` 且显式过滤非
user/assistant——"只含 user/assistant"本身是一条**防回灌契约**（工具/审计行
不得回灌模型诱发幻觉），直接改写会让展示/统计等既有消费方共同承担新语义。
故新增专用读 API `get_recent_model_context()`，由它承担重建职责。

重建规则（工单 §11.2 数据契约 + §11.3 旧数据必须诚实降级）：

- 会话库里**不存在** `role="tool"` 行——落盘的是 assistant 消息的
  `metadata.tool_calls`（展示记录）。重建即把该列表还原成
  `assistant.tool_calls` + 紧随其后的 `role="tool"` 结果消息；
- **禁止伪造配对**（§11.7 第 1 条）：T-10a 之前落盘的历史记录，调用侧没有
  `tool_call_id`，id ↔ arguments 无法对应。这类轮次**整条降级**为 `user`
  注记（沿用 `recovery.repair_tool_turns` 的孤儿语义）并计入降级计数，
  不得凭空造一个 id 出来；
- 新旧 API 各自成立：`get_recent_context` 形态**逐字节不变**（防回灌契约
  仍由它承担），重建只走新入口。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture
def sm(tmp_path):
    from neurova.session_manager import SessionManager

    manager = SessionManager()
    manager._sessions_dir = Path(tmp_path) / "sessions"
    manager._sessions_dir.mkdir(parents=True, exist_ok=True)
    return manager


def _tool_entries(call_id="call_a1", tool_name="file_read", with_call_side_id=True):
    """一轮工具调用的展示记录（T-10a 之后的形态）。"""
    call_entry = {
        "type": "tool_call",
        "tool_name": tool_name,
        "params": {"path": "a.txt"},
        "arguments": json.dumps({"path": "a.txt"}),
        "timestamp": "2026-09-24T10:00:00",
    }
    if with_call_side_id:
        call_entry["tool_call_id"] = call_id
    return [
        call_entry,
        {
            "type": "tool_result",
            "tool_name": tool_name,
            "tool_call_id": call_id,
            "result": "hello",
            "success": True,
            "timestamp": "2026-09-24T10:00:01",
        },
    ]


def _seed(sm, entries, session_id="s-t10b", agent_id="a-t10b"):
    sm.save_message(agent_id, session_id, "user", "读一下 a.txt")
    sm.save_message(
        agent_id, session_id, "assistant", "已读取",
        metadata={"tool_calls": entries},
    )
    return agent_id, session_id


def _assert_provider_legal(messages):
    """Provider 配对合法：每条 role="tool" 的 id 必须被前文 assistant 声明过。"""
    declared = set()
    for msg in messages:
        if msg.get("role") == "assistant":
            for call in msg.get("tool_calls") or []:
                declared.add(call.get("id"))
        if msg.get("role") == "tool":
            assert msg.get("tool_call_id") in declared, (
                f"孤儿 tool 消息（provider 400）：{msg.get('tool_call_id')} 未被声明"
            )


class TestRebuiltPairIsProviderLegal:
    def test_rebuilt_tool_pair_is_provider_legal(self, sm):
        agent_id, session_id = _seed(sm, _tool_entries())

        messages = sm.get_recent_model_context(agent_id=agent_id, session_id=session_id)

        assert messages, "专用读 API 没有返回任何消息"
        _assert_provider_legal(messages)
        assistant = next(m for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))
        call = assistant["tool_calls"][0]
        assert call["id"] == "call_a1"
        assert call["type"] == "function"
        assert call["function"]["name"] == "file_read"
        assert json.loads(call["function"]["arguments"]) == {"path": "a.txt"}
        tool_row = next(m for m in messages if m.get("role") == "tool")
        assert tool_row["tool_call_id"] == "call_a1"
        assert tool_row["content"] == "hello"

    def test_rebuilt_arguments_come_from_protocol_text(self, sm):
        """`arguments` 取 T-10a 落下的协议原文，不是从 params 反序列化重排的赝品。"""
        entries = _tool_entries()
        entries[0]["arguments"] = '{"path": "a.txt", "limit": 3}'
        agent_id, session_id = _seed(sm, entries)

        messages = sm.get_recent_model_context(agent_id=agent_id, session_id=session_id)

        call = next(m for m in messages if m.get("role") == "assistant" and m.get("tool_calls"))["tool_calls"][0]
        assert call["function"]["arguments"] == '{"path": "a.txt", "limit": 3}', (
            "重建必须逐字节沿用落盘的协议原文"
        )


class TestLegacyRecordsDegradeHonestly:
    def test_legacy_records_degrade_not_fabricated(self, sm):
        """T-10a 之前的历史：调用侧无 id → 整条降级为 user 注记，不得造 id。"""
        agent_id, session_id = _seed(sm, _tool_entries(with_call_side_id=False))

        messages = sm.get_recent_model_context(agent_id=agent_id, session_id=session_id)

        assert not any(m.get("role") == "tool" for m in messages), (
            "旧记录不得被重建出 tool 行——那样必然伪造配对"
        )
        assert not any(m.get("tool_calls") for m in messages if m.get("role") == "assistant"), (
            "旧记录不得被重建出 assistant.tool_calls"
        )
        notes = [m for m in messages if m.get("role") == "user" and "tool_call_id=" in str(m.get("content"))]
        assert notes, f"旧记录必须整条降级为 user 注记（不静默丢）：{[m.get('role') for m in messages]}"
        assert "hello" in notes[0]["content"], "降级不得丢内容"
        stats = sm.get_model_context_stats()
        assert stats["degraded_turns"] == 1, f"降级必须计数：{stats}"

    def test_degradation_counter_is_zero_when_rebuild_succeeds(self, sm):
        agent_id, session_id = _seed(sm, _tool_entries())
        sm.get_recent_model_context(agent_id=agent_id, session_id=session_id)
        assert sm.get_model_context_stats()["degraded_turns"] == 0
        assert sm.get_model_context_stats()["rebuilt_pairs"] == 1


class TestLegacyReadApiUnchanged:
    def test_get_recent_context_still_filters_tool_rows(self, sm):
        """防回灌契约仍由旧 API 承担：它不得因本票而放宽。"""
        agent_id, session_id = _seed(sm, _tool_entries())
        rows = sm.get_recent_context(agent_id=agent_id, session_id=session_id)
        assert rows, "旧 API 不应返回空"
        for row in rows:
            assert set(row.keys()) == {"role", "content"}, f"旧 API 形态被改动：{sorted(row.keys())}"
            assert row["role"] in ("user", "assistant"), f"旧 API 回灌了非对话行：{row['role']}"
