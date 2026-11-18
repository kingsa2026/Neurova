# -*- coding: utf-8 -*-
"""member 成本上下文绑定（fullrepo 审计 2026-11-18 C1 收尾）。

swarm 子代理跑 LLM 时，cost 上下文若仍是父轮的，usage 行的 agent_id 会
记到父代名下；完全不写则落空串（default 桶）。绑定必须**可还原**——
member 结束后，父代同任务内的后续 LLM 调用不被误记到 member 名下。

注意 ContextVar 会跨用例泄漏（同线程同 context），每个用例结尾统一
`set_llm_cost_context()` 复位成"空归属"，避免污染相邻用例的读数。
"""
from neurova.agent.swarm import SwarmManager
from neurova.models.cost_tracking import get_llm_cost_context, set_llm_cost_context

EMPTY = {"agent_id": None, "session_id": None, "turn_id": None}


class TestMemberCostContextBinding:
    def test_bind_overwrites_and_returns_prev(self):
        set_llm_cost_context(agent_id="parent-a", session_id="ps", turn_id="pt")
        try:
            prev = SwarmManager._bindMemberCostContext("member-m", "ms", "tt")
            assert prev == {"agent_id": "parent-a", "session_id": "ps", "turn_id": "pt"}
            assert get_llm_cost_context() == {
                "agent_id": "member-m", "session_id": "ms", "turn_id": "tt"}
        finally:
            set_llm_cost_context()

    def test_restore_brings_prev_back(self):
        set_llm_cost_context(agent_id="parent-a", session_id="ps", turn_id="pt")
        try:
            prev = SwarmManager._bindMemberCostContext("member-m", "ms", "tt")
            SwarmManager._restoreCostContext(prev)
            assert get_llm_cost_context() == {
                "agent_id": "parent-a", "session_id": "ps", "turn_id": "pt"}
        finally:
            set_llm_cost_context()

    def test_bind_from_empty_context(self):
        set_llm_cost_context()
        try:
            prev = SwarmManager._bindMemberCostContext("member-m", "ms", "tt")
            assert prev == EMPTY, prev
            assert get_llm_cost_context() == {
                "agent_id": "member-m", "session_id": "ms", "turn_id": "tt"}
            SwarmManager._restoreCostContext(prev)
            assert get_llm_cost_context() == EMPTY
        finally:
            set_llm_cost_context()
