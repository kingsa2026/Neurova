"""tool-turn 修复测试（OpenOcta 启发 P1-7：toolTurnRepair）

问题（OpenOcta toolTurnRepair 对症的坑）：折叠/压缩历史后 assistant 的
tool_calls 配对可能断裂——
- 孤儿 tool 结果：role:"tool" 消息的 tool_call_id 不在任何前文 assistant
  的 tool_calls 中 → OpenAI API 400（"messages with role 'tool' must be a
  response to a preceding message with 'tool_calls'"）
- 悬空 tool_calls：assistant 声明了 tool_calls 但结果被折掉 → OpenAI
  API 400（"tool_calls must be followed by tool messages"）

Neurova 的真实断点：context/orchestrator.build_context 视图重建（:484）
只保留 role+content——assistant 的 tool_calls 被剥掉后，session_context
里若混有 role:"tool" 消息（caller_provided_history / 部分渠道回传），
每个都是孤儿。compact_messages_for_overflow 已做轮次边界对齐，但边界
回退对"锚点裁剪"无能为力——repair 作为最后防线两处接线。

repair_tool_turns(messages) -> messages 契约：
- 原地语义等价返回新列表；不修改输入
- 孤儿 tool 消息 → 剥离为普通 user 系统注记（保留信息量，协议合法）
- 无结果的 assistant.tool_calls → 补合成 tool 结果（"已折叠"说明），
  防止悬空 tool_calls 400
- 尾部截断的 tool 块（assistant 带 tool_calls 但后面消息没了）同样补全
"""
from __future__ import annotations

import pytest


def tc(cid: str, name: str = "file_read"):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}


class TestOrphanToolResults:
    def test_orphan_tool_stripped_to_note(self):
        from neurova.context.recovery import repair_tool_turns

        msgs = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "c1", "content": "A"},
            {"role": "assistant", "content": "done"},
        ]
        out = repair_tool_turns(msgs)
        assert [m["role"] for m in out] == ["user", "user", "assistant"]
        assert "c1" in out[1]["content"] and "A" in out[1]["content"]
        # 不改输入
        assert msgs[1]["role"] == "tool"

    def test_paired_tool_kept(self):
        from neurova.context.recovery import repair_tool_turns

        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [tc("c1")]},
            {"role": "tool", "tool_call_id": "c1", "content": "A"},
            {"role": "assistant", "content": "done"},
        ]
        out = repair_tool_turns(msgs)
        assert [m["role"] for m in out] == ["assistant", "tool", "assistant"]
        assert out[0]["tool_calls"] == [tc("c1")]

    def test_orphan_tool_with_unmatched_id(self):
        """tool_call_id 存在于 assistant.tool_calls 但 ID 不同 → 孤儿转注记，
        assistant 的悬空调用同时补合成结果（协议闭合）。"""
        from neurova.context.recovery import repair_tool_turns

        msgs = [
            {"role": "assistant", "content": None, "tool_calls": [tc("c1")]},
            {"role": "tool", "tool_call_id": "c999", "content": "X"},
        ]
        out = repair_tool_turns(msgs)
        # 合成结果必须紧跟 assistant（tool 消息中间不能插其他角色），
        # 孤儿注记排在其后
        assert [m["role"] for m in out] == ["assistant", "tool", "user"]
        assert out[0]["tool_calls"] == [tc("c1")]
        assert "X" in out[2]["content"]  # 真实内容以注记保留
        assert out[1]["tool_call_id"] == "c1"  # 悬空调用被合成结果闭合


class TestDanglingToolCalls:
    def test_assistant_tool_calls_without_result_gets_synth(self):
        from neurova.context.recovery import repair_tool_turns

        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "tool_calls": [tc("c1"), tc("c2")]},
            {"role": "tool", "tool_call_id": "c1", "content": "A"},
            {"role": "assistant", "content": "final"},
        ]
        out = repair_tool_turns(msgs)
        # c2 缺结果 → 在 c1 之后补一条合成 tool 消息
        roles = [m["role"] for m in out]
        assert roles == ["user", "assistant", "tool", "tool", "assistant"]
        assert out[3]["tool_call_id"] == "c2"
        assert out[3]["content"]

    def test_tail_truncated_tool_block(self):
        from neurova.context.recovery import repair_tool_turns

        msgs = [
            {"role": "user", "content": "go"},
            {"role": "assistant", "content": None, "tool_calls": [tc("c1")]},
        ]
        out = repair_tool_turns(msgs)
        assert out[-1]["role"] == "tool"
        assert out[-1]["tool_call_id"] == "c1"


class TestPassThrough:
    def test_plain_messages_unchanged(self):
        from neurova.context.recovery import repair_tool_turns

        msgs = [
            {"role": "system", "content": "s"},
            {"role": "user", "content": "u"},
            {"role": "assistant", "content": "a"},
        ]
        out = repair_tool_turns(msgs)
        assert out == msgs

    def test_empty_and_non_list(self):
        from neurova.context.recovery import repair_tool_turns

        assert repair_tool_turns([]) == []


class TestOrchestratorWiring:
    """build_context 视图重建接线：剥 tool_calls 后残留的 role:"tool" 被
    repair 转化，不再把孤儿发往 LLM。"""

    def test_build_context_repairs_orphan_tools(self):
        from neurova.context.orchestrator import ContextOrchestrator
        from unittest.mock import MagicMock

        mock_agent = MagicMock()
        mock_agent.config.llm_model = "gpt-4"
        mock_agent.user_id = "u1"
        mock_agent.agent_id = "a1"

        co = ContextOrchestrator(mock_agent, use_pool=False)
        session_context = [
            {"role": "user", "content": "hi"},
            {"role": "tool", "tool_call_id": "c1", "content": "A"},
        ]
        context = co.build_context(
            user_input="go",
            session_context=session_context,
        )
        import asyncio

        if asyncio.iscoroutine(context):
            context = asyncio.run(context)
        roles = [m.get("role") for m in context]
        assert "tool" not in roles, f"孤儿 tool 消息应被 repair 转化，got {roles}"
