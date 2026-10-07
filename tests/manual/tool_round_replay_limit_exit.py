# -*- coding: utf-8 -*-
"""批次 B 的 live-verify：被终止那一轮的工具结果，一路活到台账并被下一轮读回。

跑的真生产对象：
1. 真 `OpenAILoop.predict_step(stream=True)`（流式入口）+ 真门控装配（`_buildGateRunner`）
   + 真 `iteration` 上限（经配置单源 `agent_limits_settings.DEFAULTS` 调档，不手工传阈值）；
2. 真执行咽喉：`ToolExecutor` + `handle_tool_calls`（技能执行体是替身，边界止于执行体）；
3. 真落盘：`PostChatPipeline._step_save_session` 写进会话库；
4. 真读回：`SessionManager.get_recent_model_context`（工具轮重建的唯一入口）——
   下一轮模型实际会看到的那份上下文。

判据：`iteration` 门控开火终止后，**终止那一轮**的 tool_call_id 必须
①已随 `tool_result` 事件让出、②进了取证记录、③落进会话台账、④被下一轮读回。

一条命令复现：PYTHONPATH="E:/项目/Neurova" .venv/Scripts/python.exe tests/manual/tool_round_replay_limit_exit.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

DATA_ROOT = isolatedDataRoot()

REPO_DATA_DIR = PROJECT_ROOT / "data"


def fingerprintDataDir():
    """(相对路径, 字节数, mtime_ns) 三元组集合的哈希——原地改写会动 mtime，
    等量搬移会动路径，两种都逃不掉（清单集合差看不见这两种）。"""
    items = []
    if REPO_DATA_DIR.exists():
        for p in sorted(REPO_DATA_DIR.rglob("*")):
            if p.is_file():
                st = p.stat()
                items.append(f"{p.relative_to(REPO_DATA_DIR)}|{st.st_size}|{st.st_mtime_ns}")
    return hashlib.sha256("\n".join(items).encode("utf-8")).hexdigest(), len(items)


TOOL_NAME = "probe_reader"
AGENT_ID = "a_batchB"
SESSION_ID = "sess_batchB"
MAX_ROUNDS = 2


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "批次 B live 探针技能"
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


class ScriptedStream:
    """真流式契约的假供应商：按轮次产出 chunk，并记录每次收到的消息序列。"""

    def __init__(self, rounds):
        self.rounds = rounds
        self.calls = []
        self.config = SimpleNamespace()

    async def chat_stream(self, messages, **kwargs):
        self.calls.append([dict(m) for m in messages])
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        for chunk in self.rounds[idx]:
            yield chunk


def buildAgent():
    from neurova.core.turn_context import set_turn_identity
    from neurova.agent_core import Agent
    from neurova.mem_core import MemCore
    from neurova.session_manager import get_session_manager
    import tempfile

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "batchB"
    agent.config.agent_id = AGENT_ID
    agent.config.llm_model = "gpt-test"
    agent.config.workspace_path = tempfile.mkdtemp(prefix="batchB-ws-")
    agent.user_id = "u1"
    agent.agent_id = AGENT_ID
    set_turn_identity("连续读三个文件", SESSION_ID, "u1")
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
        TOOL_NAME,
        # 把收到的参数原样回显：不论执行体按位置还是按关键字收参，
        # 「这是哪一轮的那次调用」都能在读回的正文里被指认。
        AsyncMock(side_effect=lambda *a, **kw: {
            "content": f"探针读到内容 args={a} kwargs={kw}"
        }),
    )
    return agent


async def drive(agent, loop):
    from neurova.llm_client import LLMResponse

    def roundChunks(i):
        return [
            LLMResponse(content=f"第 {i} 次读。"),
            LLMResponse(
                tool_calls=[{
                    "index": 0,
                    "id": f"call_r{i}",
                    "type": "function",
                    "function": {"name": TOOL_NAME, "arguments": json.dumps({"signature": f"s{i}"})},
                }],
                finish_reason="tool_calls",
            ),
        ]

    llm = ScriptedStream(
        [roundChunks(1), roundChunks(2), roundChunks(3), [LLMResponse(content="收口。", finish_reason="stop")]]
    )
    loop.llm_client = llm
    agent.llm_client = llm
    messages = [{"role": "user", "content": "连续读三个文件"}]

    gen = await loop.predict_step(messages, tools=None, stream=True)
    events = [e async for e in gen]
    return llm, messages, events


def main() -> int:
    import neurova.security.agent_limits_settings as als
    from neurova.agent.loops.openai_loop import OpenAILoop
    from neurova.post_chat_pipeline import PostChatPipeline
    from neurova.tool_executor import ToolExecutor

    before, beforeCount = fingerprintDataDir()

    agent = buildAgent()
    agent.tool_executor = ToolExecutor(agent)
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = agent

    original = dict(als.DEFAULTS)
    als.DEFAULTS.update({"max_loop_rounds": MAX_ROUNDS, "goal_round_budget": None})
    try:
        llm, messages, events = asyncio.run(drive(agent, loop))
    finally:
        als.DEFAULTS.clear()
        als.DEFAULTS.update(original)

    gateEvents = [e for e in events if isinstance(e, dict) and e.get("type") == "gate_terminate"]
    streamedResults = [
        e["data"].get("tool_call_id")
        for e in events
        if isinstance(e, dict) and e.get("type") == "tool_result" and isinstance(e.get("data"), dict)
    ]
    print(f"1) 真流式入口 + 真门控装配（配置单源 max_loop_rounds={MAX_ROUNDS}）")
    print(f"   LLM 往返次数 = {len(llm.calls)}（第 3 轮不应再问模型）")
    print(f"   gate_terminate = {[(g.get('gate'), g.get('reason')) for g in gateEvents]}")
    print(f"   已让出的 tool_result id = {streamedResults}")
    assert gateEvents and gateEvents[0].get("gate") == "iteration", "生产上限出口未被走到"
    assert len(llm.calls) == MAX_ROUNDS, f"上限之后仍在问模型：{len(llm.calls)}"

    terminatingId = streamedResults[-1]
    historyToolIds = [m.get("tool_call_id") for m in messages if m.get("role") == "tool"]
    print("2) 终止那一轮必须已回放进消息历史（判据只决定要不要开下一轮）")
    print(f"   历史里的 tool 结果 id = {historyToolIds}")
    assert terminatingId in historyToolIds, f"终止那一轮 {terminatingId} 没进历史——只发不收"
    declared = {
        c.get("id")
        for m in messages
        if m.get("role") == "assistant" and m.get("tool_calls")
        for c in m["tool_calls"]
    }
    assert set(historyToolIds) <= declared, "历史里存在孤儿 tool 结果（缺 assistant 声明）"

    records = agent.get_tool_messages_snapshot()
    recIds = {r.get("tool_call_id") for r in records if r.get("type") == "tool_result"}
    print("3) 取证记录（前端配对与落盘的同一来源）")
    print(f"   记录条数 = {len(records)} / 结果侧 id = {sorted(recIds)}")
    assert terminatingId in recIds, "终止那一轮没进取证记录"

    pipeline = PostChatPipeline(agent)
    pipeline._step_results = []
    saved = asyncio.run(
        pipeline._step_save_session(
            user_input="连续读三个文件",
            reply="收口。",
            session_id=SESSION_ID,
            save_memory=True,
            metadata={"session_title": "batchB"},
        )
    )
    print(f"4) 真落盘 = {saved!r}")

    from neurova.session_repository import get_session_repository

    rows = get_session_repository().get_history(
        agent_id=AGENT_ID, session_id=SESSION_ID
    ) or []
    shapes = [(m.get("role"), sorted((m.get("metadata") or {}).keys())) for m in rows]
    print(f"   会话库行数 = {len(rows)} / 形态 = {shapes}")

    from neurova.session_manager import get_session_manager

    context = get_session_manager().get_recent_model_context(AGENT_ID, SESSION_ID, max_messages=20)
    toolIdsInNextTurn = [m.get("tool_call_id") for m in context if m.get("role") == "tool"]
    toolTexts = [str(m.get("content")) for m in context if m.get("role") == "tool"]
    print("5) 真读回：下一轮模型实际看到的上下文")
    print(f"   重建出的 tool 结果 id = {toolIdsInNextTurn}")
    print(f"   stats = {get_session_manager()._model_context_stats}")
    assert terminatingId in toolIdsInNextTurn, (
        f"终止那一轮没被下一轮读回：{toolIdsInNextTurn}——写→读→反馈未闭合"
    )
    _marker = terminatingId.replace("call_", "")  # call_r2 → r2 → 参数里写的是 s2
    assert f"s{_marker[1:]}" in "".join(toolTexts), (
        f"读回的不是那一轮的参数原文：{toolTexts}"
    )

    after, afterCount = fingerprintDataDir()
    print(f"6) 仓内 data/ 未被写入：指纹 {before[:12]}…({beforeCount} 文件) → {after[:12]}…({afterCount} 文件)")
    assert before == after, "活体把数据写进了仓库 data/（隔离失效）"

    print(f"   隔离数据根 = {DATA_ROOT}")
    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
