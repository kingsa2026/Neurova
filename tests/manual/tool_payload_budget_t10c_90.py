# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-10c 收口）：工具轮载荷真进窗口预算。

链路：真 `ContextOrchestrator` → 真 `build_context` → 真 `_apply_window_budget`
→ 真 `_clear_old_tool_results`（生产装配，不手工传预算、不绕装配点）。

判据：同一批含工具轮的会话，改前按"只读 content"的假读数判定（读到 85 token、
零折叠）；改后读数覆盖 `assistant.tool_calls` 的 arguments 原文，折叠与 microcompact
按真预算动手。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from neurova.context.composition import _measure_messages
from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens


def _agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-live-budget"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a-live-budget"
    return agent


def _tool_turn_window(turns: int, code_chars: int) -> list:
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        code = "def handler():\n    return 1\n" * max(1, code_chars // 24)
        msgs.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "id": f"call_lv_{i}",
                "type": "function",
                "function": {
                    "name": "run_code",
                    "arguments": '{"code": "%s"}' % code.replace("\n", "\\n"),
                },
            }],
        })
        msgs.append({
            "role": "tool",
            "tool_call_id": f"call_lv_{i}",
            "name": "run_code",
            "content": "200 OK",
        })
    return msgs


async def main() -> int:
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = 9600
    cap = max(0, orch._resolve_window_token_budget() - orch._ENVELOPE_MIN_TOKENS)
    failures = []

    for turns, chars in ((8, 3000), (4, 2000), (2, 100)):
        msgs = _tool_turn_window(turns, chars)
        folded = await orch._apply_window_budget(list(msgs), cap, cache_key=f"live-{turns}")
        cleared = orch._clear_old_tool_results(list(folded))
        placeholders = [
            m for m in cleared
            if str((m or {}).get("content", "")).startswith("[工具输出已移出上下文")
        ]
        judge = estimate_window_tokens(folded)
        display = _measure_messages(folded)["total_tokens"]
        readout = orch.get_context_health()["microcompact"]
        print(
            f"[turns={turns} chars={chars}] 判据读数={judge} 展示读数={display} "
            f"cap={cap} 折叠后行={len(folded)}/{len(msgs)} 占位={len(placeholders)} "
            f"microcompact={readout['triggered_calls']}"
        )
        if judge != display + len(folded) * 4:
            failures.append(f"turns={turns}: 判据 {judge} != 展示 {display} + 开销")
        if turns == 8 and len(folded) >= len(msgs):
            failures.append("turns=8: 工具轮撑爆预算却零折叠")
        if turns == 2 and len(folded) < len(msgs):
            failures.append("turns=2: 小载荷不该折叠")

    if failures:
        print("LIVE-VERIFY FAILED")
        for item in failures:
            print("  -", item)
        return 1
    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
