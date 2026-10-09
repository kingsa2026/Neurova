# -*- coding: utf-8 -*-
"""批次 C 的 live-verify：晚到工具终态只回到发起它的那个会话。

跑的真生产对象：
1. 真 `ToolExecutor` 咽喉 + 真 `ToolCoordinator.run_with_timeout`（超时→转后台→观察者投递）；
2. 真 `OpenAILoop.handle_tool_calls`（执行链，工具执行体是替身，边界止于执行体）；
3. 真轮次身份：`turn_context.set_turn_identity`（与 `turn_state.py:119` 同一入口）；
4. 真排干 API：`pop_pending_hints(session_id)`——`chat_pipeline.py:2241` 调的就是它。

判据（缺一条这条链就是断的）：
- A 会话发起的慢工具超时转后台，完成后的终态归 A；
- 同一 agent 上的 B 会话排干拿不到它（改前：B 一把取走，把 A 的工具正文注进 B 的上下文）；
- A 自己排干取得到，正文是那次执行的真实结果；
- 无归属终态被点名拒绝（既不静默丢也不广播）。

全程在同一个事件循环里跑：后台任务的生命周期属于发起它的那个 loop，跨 `asyncio.run`
它根本不会继续，读数就会假空。

一条命令复现：PYTHONPATH="$(git rev-parse --show-toplevel)" .venv/Scripts/python.exe tests/manual/pending_hints_session_fence_live.py

如实记一句：本层证「执行咽喉→协调器→按会话排干」这段闭合，**不证** console HTTP 端点
——注入点是 `chat_pipeline._step_llm_call` 里的那几行，由
`test_pending_hints_session_fence.py::TestProductionConsumerPassesSession`（AST 判据）钉住。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.manual._liveVerifyIsolation import isolatedDataRoot

isolatedDataRoot()

TOOL_NAME = "probe_slow_reader"
SESSION_A = "sess_alpha_live"
SESSION_B = "sess_beta_live"


class _StubSkill:
    def __init__(self, name):
        self.name = name
        self.description = "C 批 live 探针：会超时的只读工具"
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


def buildAgent(coordinator):
    from neurova.agent_core import Agent
    from neurova.core.turn_context import set_turn_identity
    from neurova.tool_executor import ToolExecutor

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "cLive"
    agent.config.agent_id = "a_c_live"
    agent.config.workspace_path = str(PROJECT_ROOT)
    agent.user_id = "u1"
    agent.agent_id = "a_c_live"
    agent.session_manager = None
    agent.memory_agent = None
    agent._current_user_id = "u1"
    agent.tool_memory = None
    agent.tool_lifecycle = None
    agent.skill_packer = None
    agent.tool_router = None
    agent._tool_records = []
    agent.append_tool_messages = lambda records: agent._tool_records.extend(records or [])
    agent.get_tool_messages_snapshot = lambda: list(agent._tool_records)
    agent._collect_tool_messages = lambda: list(agent._tool_records)
    agent.reset_tool_messages = lambda: agent._tool_records.clear()

    async def slowExecute(*args, **kwargs):
        await asyncio.sleep(0.6)
        return {"content": "A 会话才该看到的正文"}

    agent._skill_registry = _StubRegistry(TOOL_NAME, slowExecute)
    agent.tool_executor = ToolExecutor(agent)
    # 协调器换成被测那一份，执行链其余全真
    agent.tool_executor.tool_coordinator = coordinator
    set_turn_identity("读一下", SESSION_A, "u1")
    return agent


async def scenario() -> int:
    from neurova.agent.loops.openai_loop import OpenAILoop
    from neurova.agent.tool_coordinator import ToolCoordinator
    from neurova.core.turn_context import set_turn_identity

    coordinator = ToolCoordinator()
    agent = buildAgent(coordinator)
    loop = OpenAILoop.__new__(OpenAILoop)
    loop.agent = agent

    # 把该工具的超时打到 0.05s（执行体睡 0.6s）才会走「转后台继续」这一支。
    # patch 落在真源 `tool_coordinator.get_tool_timeout`：执行链在使用点懒加载它，
    # 打在别处不会生效（与 tests/unit/agent/test_tool_timeout_wiring.py 同一做法）。
    import neurova.agent.tool_coordinator as tck

    tck.get_tool_timeout = lambda name, default=None: 0.05

    print(f"1) A 会话（{SESSION_A}）经真执行链发起一次会超时的工具执行")
    outcomes = await loop.handle_tool_calls(
        [{"id": "call_a1", "type": "function",
          "function": {"name": TOOL_NAME, "arguments": "{}"}}],
        [],
    )
    assert outcomes and outcomes[0]["role"] == "tool", "工具轮没有配对回环"
    assert "background" in str(outcomes[0]["content"]), (
        f"未走转后台分支，本探针前提不成立：{outcomes[0]['content']!r}"
    )
    print(f"   当场回环正文 = {str(outcomes[0]['content'])[:90]!r}")

    print("2) 等后台观察者把终态投进队列")
    for _ in range(80):
        if coordinator._pending_hints:
            break
        await asyncio.sleep(0.05)
    assert coordinator._pending_hints, "后台终态从未投递（G4-RC6 那类断链复现）"
    hint = coordinator._pending_hints[0]
    print(f"   队列归属 session = {hint.get('session_id')!r}")
    assert hint.get("session_id") == SESSION_A, f"终态归属错：{hint}"

    print(f"3) 同一 agent 上的 B 会话（{SESSION_B}）排干 → 必须拿不到")
    set_turn_identity("别人的一轮", SESSION_B, "u1")
    foreign = coordinator.pop_pending_hints(SESSION_B)
    print(f"   B 取到 = {foreign}")
    assert foreign == [], f"B 会话把 A 的后台工具结果读进了自己的上下文：{foreign}"

    print(f"4) 回到 A 会话排干 → 取得到，且正文是那次执行的真实结果")
    set_turn_identity("A 的下一轮", SESSION_A, "u1")
    mine = coordinator.pop_pending_hints(SESSION_A)
    print(f"   A 取到 = {[(h.get('tool_name'), h.get('success')) for h in mine]}")
    assert len(mine) == 1 and mine[0]["success"] is True
    assert "A 会话才该看到的正文" in str(mine[0].get("result")), f"取回的不是那次执行：{mine[0]}"
    assert coordinator.pop_pending_hints(SESSION_A) == [], "取走未清空，会被重复注入"

    print("5) 无归属终态 → 点名拒绝，不广播也不入队")
    set_turn_identity("无会话身份的一轮", None, "u1")
    coordinator.recordApprovalOutcome(
        "file_write", "call_orphan", success=True, session_id=None, result={"ok": 1}
    )
    print(f"   队列 = {coordinator._pending_hints}")
    assert coordinator._pending_hints == [], "无归属终态仍入队，等着被任意会话读走"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(scenario()))
