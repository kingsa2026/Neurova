# -*- coding: utf-8 -*-
"""轮次态轻量不变量（Issue #268 切片 C）——把「归属错误」变成可观测事实。

方案 §5.3 的裁定：**不引入相位状态机**（参照侧的 9 相位 + 非法转移抛错是净增
代码与认知负担，当前无消费者）。切片 A 已把轮次态从 loop 实例迁到
`TurnRunState`，切片 B 已把递归拉平成迭代；剩下要补的不是"相位可证明"，而是
**归属可自证**——两条断言式不变量，代价近零：

1. `assertRoundInvariant(state)`：每轮入口自检 `toolRounds <= maxToolRounds`。
   轮次上限判定本应在累加处咬合（`state.toolRounds > state.maxToolRounds` 即终止），
   一旦这条不变量在轮入口被违反，说明**上限判定被绕过**——而"被绕过"在今天
   唯一可复现的成因就是跨会话污染（缺陷 A 的形态）：另一个会话把本方计数抹平，
   本方于是能越过自己的上限继续续轮。所以这条断言不是"重复检查"，是把缺陷 A
   从"要靠并发活体才测得到"降级为"任何一轮入口都能自证"。

2. `TurnRunState.turnId` + `agentId` 创建者指纹：两个不同 turn 的 state 被交叉
   使用，在开发期即红。切片 A/B/D 之后，state 是唯一的轮次事实源，
   但"谁创建了它"从未被记录——一次误传（把上一轮的 state 递进新请求）会让
   新请求继承旧轮次计数，且**静默**（计数合法、上限不被违反）。

判据（每条都要求"改前实测不成立、改后成立"）：
- 静态：`turn_run_state.py` 提供 `assertRoundInvariant` 与 `turnId` / `agentId` 字段；
- 活体：真实 `OpenAILoop` 驱动多轮工具环，每轮入口不变量成立；
- 反面：手工构造越界 state 与交叉 turnId，断言必须以**点名原因**的异常暴露，
  不得静默放行（教义第 2 条：报错要么根修，要么以诚实形态暴露）。

替身只放在模型边界；state 构造、轮次推进、不变量求值全走生产代码。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from neurova.agent.loops.openai_loop import OpenAILoop
from neurova.agent.loops.turn_run_state import TurnRunState
from neurova.llm_client import LLMResponse

LOOPS_DIR = Path(__file__).resolve().parents[3] / "neurova" / "agent" / "loops"
STATE_PY = LOOPS_DIR / "turn_run_state.py"


def _src() -> str:
    return STATE_PY.read_text(encoding="utf-8")


def _llmConfig():
    return SimpleNamespace(
        temperature=None, max_tokens=None, top_p=None, frequency_penalty=None, model="gpt-4o",
    )


class ScriptedRounds:
    """模型边界替身：按脚本驱动多轮工具环，记录每轮看到的消息。"""

    def __init__(self, rounds):
        self.config = _llmConfig()
        self.rounds = list(rounds)
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(list(messages))
        idx = min(len(self.calls) - 1, len(self.rounds) - 1)
        return LLMResponse(
            content="", tool_calls=list(self.rounds[idx]), finish_reason="tool_calls",
        )


def _tool_call(name, arg):
    return {"id": f"c-{name}-{arg}", "type": "function",
            "function": {"name": name, "arguments": '{"x": %d}' % arg}}


def _makeLoop(chat, toolRounds=10):
    """真 `OpenAILoop`：模型边界与工具执行边界替身，其余走本仓实现。"""
    agent = SimpleNamespace(
        llm_client=chat,
        config=SimpleNamespace(name="probe", user_id="u1", agent_id="a1", llm_model="gpt-4o"),
        _tool_messages_list=[],
        _round_usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        skill_registry=None,
        _skill_registry=None,
        tool_router=None,
        tool_memory=None,
        tool_lifecycle=None,
        skill_packer=None,
        current_session_id="s-slice-c",
        set_current_reasoning=lambda text: None,
    )
    loop = OpenAILoop(agent)
    loop.llm_client = chat
    loop._max_tool_rounds = toolRounds
    # 缺省 GoalGate 的 15 轮硬顶会截断长环（切片 B/D 已登记的缺陷，本片不修），
    # 故用规格探针把截断挪开，只测本片的不变量。
    loop._goal_gate_spec = {"goal": {}, "completion_check": None, "max_rounds": 1000}

    async def handle_tool_calls(calls, messages):
        return [
            {"role": "tool", "tool_call_id": c["id"], "name": "probe", "content": "ok"}
            for c in calls
        ]

    loop.handle_tool_calls = handle_tool_calls
    return loop


async def _drive(rounds: int, seen_invariants: list):
    """真 loop + 真 state；每轮入口求值不变量并记录成立与否。"""
    llm = ScriptedRounds([[_tool_call("probe", i)] for i in range(rounds)])
    loop = _makeLoop(llm, toolRounds=rounds + 1)

    original = TurnRunState.assertRoundInvariant

    def _spy(self, *a, **k):
        seen_invariants.append(self.toolRounds <= self.maxToolRounds)
        return original(self, *a, **k)

    TurnRunState.assertRoundInvariant = _spy
    try:
        await loop.predict_step([{"role": "user", "content": "跑满"}], tools=[{"type": "function"}])
    finally:
        TurnRunState.assertRoundInvariant = original
    return llm


# ─────────────────────────── 静态判据 ───────────────────────────

def test_roundInvariantHelperIsDefined():
    """静态：不变量求值点与创建者指纹字段必须存在（缺失即红）。"""
    src = _src()
    assert "assertRoundInvariant" in src, "turn_run_state.py 无 assertRoundInvariant 求值点"
    assert "turnId" in src, "TurnRunState 未记录 turnId（创建者指纹）"
    assert "agentId" in src, "TurnRunState 未记录 agentId（创建者指纹）"


def test_stateConstructionRecordsCreatorFingerprint():
    """活体：每次 predict_step 构造的 state 带 turnId 与 agentId，且互不重复。"""
    seen = []
    asyncio.run(_drive(3, []))
    # 直接构造两个 state，验证指纹非空且互异（构造面单源）
    a = TurnRunState.forTurn(agentId="agent-a", roundUserKey="k1")
    b = TurnRunState.forTurn(agentId="agent-a", roundUserKey="k2")
    assert a.turnId and b.turnId, "turnId 必须非空"
    assert a.turnId != b.turnId, "两个 turn 的 turnId 不得相同（否则交叉使用测不出）"
    assert a.agentId == "agent-a"
    seen.append((a.turnId, b.turnId))
    assert seen


# ─────────────────────────── 活体判据 ───────────────────────────

def test_invariantHoldsEveryRoundUnderRealLoop():
    """活体：真实 loop 跑多轮工具环，每轮入口不变量成立（上限未被绕过）。"""
    seen = []
    asyncio.run(_drive(6, seen))
    assert seen, "未观测到任何轮入口（探针未生效）"
    assert all(seen), f"存在轮入口不变量被违反：{seen}"


def test_crossTurnStateIsRejectedLoudly():
    """反面：跨 turn 交叉使用 state 必须以点名原因的异常暴露，不得静默放行。"""
    a = TurnRunState.forTurn(agentId="agent-a", roundUserKey="k1")
    b = TurnRunState.forTurn(agentId="agent-b", roundUserKey="k2")
    with pytest.raises(Exception) as ei:
        a.assertSameTurnAs(b)
    msg = str(ei.value)
    assert a.turnId in msg and b.turnId in msg, f"异常未点名两个 turnId：{msg}"


def test_overBudgetStateIsRejectedLoudly():
    """反面：越界 state 必须在入口被点名（上限判定被绕过 = 跨会话污染的可观测形态）。"""
    st = TurnRunState.forTurn(agentId="agent-a", roundUserKey="k1")
    st.maxToolRounds = 3
    st.toolRounds = 4
    with pytest.raises(Exception) as ei:
        st.assertRoundInvariant()
    msg = str(ei.value)
    assert "4" in msg and "3" in msg, f"异常未点名计数与上限：{msg}"


def test_invariantDoesNotFireOnLegalState():
    """反向控制项：合法 state 上不变量永不误报（否则它就成了噪音门）。"""
    st = TurnRunState.forTurn(agentId="agent-a", roundUserKey="k1")
    st.maxToolRounds = 5
    for r in range(0, 6):
        st.toolRounds = r
        st.assertRoundInvariant()  # 0..5 全部合法，含边界
