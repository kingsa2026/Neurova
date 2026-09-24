#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-10a 的 live-verify：配对锚点真的落到会话台账（Issue #90 工单 §11.2）。

跑的是**真生产链路**，不是单测替身：

1. 真 `Agent` 实例（`Agent(...)` 生产构造点）；
2. 真 `Agent.chat` 生产入口 + 真 loop 执行链（`handle_tool_calls` →
   真 `ToolExecutor` → 真内置工具 `get_datetime`）；
3. 真 `PostChatPipeline` 收尾落盘（`_step_save_session` 把展示记录写进
   assistant 消息的 `metadata.tool_calls`）；
4. 真 `SessionManager` 文件层落盘后被**读回来**（`get_history`），
   判据落在"会话台账里到底有什么"这一环，不是"记录里有几个键"。

一条命令复现：PYTHONPATH=. python tests/manual/tool_call_record_identity_t10a_90.py

四段读数：
1. 落盘台账里调用侧记录的 `tool_call_id` / `arguments`（T-10a 的产出）；
2. 结果侧记录的 `tool_call_id` 与调用侧**同值**（配对锚点两侧同源）；
3. 既有键一个不少（只增键，工单 §11.7 第 4 条）；
4. 出口脱敏面：`arguments` 里的敏感值不得原样出口（T-10a 放大视角命中点）。
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 写盘全在系统临时目录，不污染仓库 data/
os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="t10a-live-"))

CALL_ID = "call_live_t10a"


def _scriptedModel(agent, rounds):
    """模型边界替身：按脚本产出 chunk，不参与任何执行链。"""
    from neurova.llm_client import LLMResponse

    class _Scripted:
        def __init__(self, config):
            self.config = config
            self._rounds = rounds
            self.calls = 0

        def _next(self):
            script = self._rounds[min(self.calls, len(self._rounds) - 1)]
            self.calls += 1
            return script

        async def chat_stream(self, messages, **kwargs):
            for chunk in self._next():
                yield chunk

        async def chat(self, messages, **kwargs):
            for chunk in self._next():
                if isinstance(chunk, LLMResponse):
                    return chunk
            return LLMResponse(content="", finish_reason="stop")

    return _Scripted(agent.llm_client.config)


def _toolCallRound():
    from neurova.llm_client import LLMResponse

    return [[
        LLMResponse(
            content="",
            tool_calls=[{
                "index": 0,
                "id": CALL_ID,
                "type": "function",
                "function": {"name": "get_datetime",
                             "arguments": json.dumps({"taskNameActive": "看时间"})},
            }],
            finish_reason="tool_calls",
        )
    ], [LLMResponse(content="done", finish_reason="stop")]]


def _ledgerFromSession(agent_id: str, session_id: str):
    """从会话台账读回 assistant 消息的 metadata.tool_calls（真读回，不是内存态）。"""
    from neurova.session_manager import SessionManager

    manager = SessionManager()
    history = manager.get_recent_context(agent_id, session_id, max_turns=10)
    entries = []
    for msg in history or []:
        for record in ((msg.get("metadata") or {}).get("tool_calls") or []):
            entries.append(record)
    return entries


def main() -> int:
    from neurova.agent_core import Agent

    workspace = tempfile.mkdtemp(prefix="t10a-ws-")
    agent = Agent(name="T10aProbe", agent_id="t10a-probe",
                  workspace_path=workspace, enable_memory=False)
    model = _scriptedModel(agent, _toolCallRound())
    agent.llm_client = model
    agent.loop.llm_client = model

    session_id = "t10a-ledger"

    async def _go():
        await agent.chat("现在几点", session_id=session_id, stream=True)
        await agent.post_chat_pipeline.drain_background(timeout=60)

    asyncio.run(_go())

    root = Path(os.environ["NEUROVA_DATA_DIR"])
    session_files = sorted(root.glob(f"sessions/*/*{session_id}*.json"))
    assert session_files, f"会话未落盘：{root}/sessions 下没有 {session_id} 的文件"
    raw = json.loads(session_files[0].read_text(encoding="utf-8"))
    messages = raw if isinstance(raw, list) else raw.get("messages", [])
    ledger = []
    for msg in messages:
        ledger.extend(((msg.get("metadata") or {}).get("tool_calls") or []))
    assert ledger, "会话台账里没有 metadata.tool_calls —— 展示记录未落盘"

    calls = [r for r in ledger if r.get("type") == "tool_call"]
    results = [r for r in ledger if r.get("type") == "tool_result"]
    assert calls and results, f"台账条目不成对：{ledger}"

    print(f"[1 调用侧锚点] tool_call_id = {calls[0].get('tool_call_id')!r} "
          f"| arguments = {calls[0].get('arguments')!r}")
    assert calls[0].get("tool_call_id") == CALL_ID, (
        f"调用侧记录没带配对锚点：{sorted(calls[0])}"
    )

    print(f"[2 配对同源] 结果侧 tool_call_id = {results[0].get('tool_call_id')!r}")
    assert results[0].get("tool_call_id") == calls[0].get("tool_call_id"), (
        "两侧 anchor 不同值 —— 配对在落盘时就断了"
    )

    missing = [k for k in ("tool_name", "result", "success", "timestamp",
                           "reproducible", "offload_path") if k not in results[0]]
    print(f"[3 既有键] tool_result 缺键 = {missing or '无'}")
    assert not missing, f"tool_result 既有键被改动：{missing}"

    from neurova.security.privacy_gate import redact_tool_messages_for_channel

    leaked = redact_tool_messages_for_channel([
        {"type": "tool_call", "tool_name": "web_fetch",
         "params": {"password": "hunter2"},
         "arguments": json.dumps({"password": "hunter2"})},
    ])
    blob = json.dumps(leaked, ensure_ascii=False)
    print(f"[4 出口脱敏] arguments 出口形态 = {leaked[0].get('arguments')!r}")
    assert "hunter2" not in blob, f"原始参数串绕过出口脱敏：{blob}"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
