#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-10a 的 live-verify：配对信息在真链路上一路活到会话台账（Issue #90 §11.2）。

跑的**全是真生产对象**：

1. 真 `Agent` 壳 + 真 `ToolExecutor`（唯一执行咽喉）+ 真 `OpenAILoop`
   的 `handle_tool_calls`（工具执行体是替身，边界止于技能执行体那一层）；
2. 真 `post_chat_pipeline` 的落盘步骤 `_step_save_session` —— 它读
   `_collect_tool_messages()` 并把展示记录写进 assistant 消息的
   `metadata.tool_calls`；会话库写盘全在系统临时目录；
3. 真 `_recall_by_call_id`（模型可调用的直取寻址）按 `tool_call_id` 取回原文；
4. 真出口门控 `redact_tool_messages_for_channel`（渠道/WS 广播那一条）。

判据（缺一条这条链就是断的）：

- 调用侧记录带 `tool_call_id` 与协议原文形态 `arguments`；
- 台账读回来仍能**逐字节**重建 provider 的 tool_call（id + arguments）；
- 直取寻址命中（调用侧 id 就是结果侧的键）；
- 出口门控把两个参数字段**同时**脱敏，原文串不裸奔出网。

一条命令复现：PYTHONPATH=. python tests/manual/tool_call_pairing_t10a_90.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="t10a-live-"))

TOOL_NAME = "probe_reader"
PROVIDER_ID = "call_provider_0001"
RAW_ARGUMENTS = '{"query": "北京 天气", "password": "hunter2"}'
AGENT_ID = "a1"
SESSION_ID = "sess_t10a"


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "T-10a live 探针技能"
        self.config = {}


class _StubRegistry:
    def __init__(self, name, execute):
        self._skill = _StubSkill(name)
        self.skills = {name: self._skill}
        self.execute_skill = execute

    def get_skill(self, name):
        return self._skill if name == self._skill.name else None

    def has_skill(self, name):
        return name == self._skill.name

    def list_skills(self):
        return []


def _agent():
    from neurova.agent_core import Agent

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "t10a"
    agent.config.agent_id = AGENT_ID
    agent.config.workspace_path = tempfile.mkdtemp(prefix="t10a-ws-")
    agent.user_id = "u1"
    agent.agent_id = AGENT_ID
    # 真组合面：与 `agent_core.init_memory` 同型的装配（MemCore 是真对象，
    # 会话库是 `get_session_manager()` 单例）
    from neurova.core.turn_context import set_turn_identity
    from neurova.mem_core import MemCore
    from neurova.session_manager import get_session_manager

    # 与 `chat_pipeline._init_agent_state` 同型的写入：身份走真 property 读面
    set_turn_identity("查一下北京天气", SESSION_ID, "u1")
    agent.session_manager = get_session_manager()
    agent.memory_agent = MemCore(agent)
    agent._current_user_id = "u1"
    agent.tool_memory = None
    agent.tool_lifecycle = None
    agent.skill_packer = None
    agent.tool_router = None
    agent.skill_registry = None
    agent._tool_records = []
    agent.append_tool_messages = lambda records: agent._tool_records.extend(records or [])
    agent.get_tool_messages_snapshot = lambda: list(agent._tool_records)
    agent._collect_tool_messages = lambda: list(agent._tool_records)
    agent.reset_tool_messages = lambda: agent._tool_records.clear()
    agent._skill_registry = _StubRegistry(
        TOOL_NAME, AsyncMock(return_value={"content": "北京今天晴，26 度"})
    )
    return agent


def main() -> int:
    from neurova.agent.loops.openai_loop import OpenAILoop
    from neurova.post_chat_pipeline import PostChatPipeline
    from neurova.tool_executor import ToolExecutor

    agent = _agent()
    agent.tool_executor = ToolExecutor(agent)
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = agent
    loop.llm_client = None

    print("1) 真执行链落展示记录（真咽喉 + 真 handle_tool_calls）")
    asyncio.run(
        loop.handle_tool_calls(
            [{"id": PROVIDER_ID, "function": {"name": TOOL_NAME, "arguments": RAW_ARGUMENTS}}],
            [],
        )
    )
    records = agent.get_tool_messages_snapshot()
    call_rec = next(r for r in records if r.get("type") == "tool_call")
    result_rec = next(r for r in records if r.get("type") == "tool_result")
    print(f"   tool_call 键     = {sorted(call_rec)}")
    print(f"   tool_call_id     = {call_rec.get('tool_call_id')!r}")
    print(f"   arguments 原文   = {call_rec.get('arguments')!r}")
    assert call_rec.get("tool_call_id") == PROVIDER_ID, "调用侧没带 tool_call_id"
    assert call_rec.get("arguments") == RAW_ARGUMENTS, "调用侧没留住协议原文形态"
    assert result_rec.get("tool_call_id") == PROVIDER_ID, "结果侧不可寻址"

    print("2) 真落盘步骤：展示记录写进 assistant 消息 metadata.tool_calls")
    pipeline = PostChatPipeline(agent)
    pipeline._step_results = []
    saved_id = asyncio.run(
        pipeline._step_save_session(
            user_input="查一下北京天气",
            reply="北京今天晴",
            session_id=SESSION_ID,
            save_memory=True,
            metadata={"session_title": "t10a"},
        )
    )
    print(f"   落盘 session = {saved_id!r}")

    print("3) 从会话库读回来：必须能逐字节重建 provider 的 tool_call")
    from neurova.session_repository import get_session_repository

    repo = get_session_repository()
    history = repo.get_history(agent_id=AGENT_ID, session_id=SESSION_ID) or []
    ledger_entries = [
        tc
        for msg in history
        for tc in ((msg.get("metadata") or {}).get("tool_calls") or [])
    ]
    print(f"   台账条目数 = {len(ledger_entries)}")
    ledger_call = next(e for e in ledger_entries if e.get("type") == "tool_call")
    assert ledger_call.get("tool_call_id") == PROVIDER_ID, (
        f"台账里调用侧丢了 id：{sorted(ledger_call)}"
    )
    rebuilt = {
        "id": ledger_call["tool_call_id"],
        "type": "function",
        "function": {"name": ledger_call["tool_name"], "arguments": ledger_call["arguments"]},
    }
    assert rebuilt["function"]["arguments"] == RAW_ARGUMENTS, (
        "重建出的 arguments 与 provider 原文不逐字节相等（重新序列化会改写空白）"
    )
    print(f"   重建 assistant.tool_calls = {json.dumps(rebuilt, ensure_ascii=False)}")

    print("4) 真直取寻址：按调用侧 id 取回结果原文")
    recalled = asyncio.run(
        agent.tool_executor._recall_by_call_id(PROVIDER_ID, {"session_id": SESSION_ID})
    )
    print(f"   recall source = {recalled.get('source')} / error = {recalled.get('error')!r}")
    assert recalled.get("source") == "session_ledger", (
        f"调用侧 id 与结果侧不配对，直取寻址落空：{recalled}"
    )
    # 台账里的 result 是序列化后的 JSON 串（ascii 转义），判据在解出的文本上做
    _recalled_text = json.loads(str(recalled.get("content")))["content"]
    print(f"   content = {_recalled_text!r}")
    assert "26 度" in _recalled_text, "取回的不是本次结果原文"

    print("5) 真出口门控：两个参数字段同时脱敏，原文串不裸奔出网")
    from neurova.security.privacy_gate import redact_tool_messages_for_channel

    egress = redact_tool_messages_for_channel([call_rec])[0]
    print(f"   params    = {egress.get('params')}")
    print(f"   arguments = {egress.get('arguments')}")
    assert "hunter2" not in json.dumps(egress), "密钥经协议原文形态裸奔出网"
    assert json.loads(egress["arguments"])["query"] == "北京 天气", "脱敏改坏了非敏感字段"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
