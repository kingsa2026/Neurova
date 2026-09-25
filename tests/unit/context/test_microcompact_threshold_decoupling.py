# -*- coding: utf-8 -*-
"""microcompact 的触发轴与保留窗：与窗口折叠**各自声明**（Issue #90 · T-10c 前置裁定）。

裁定（负责人 2026-09-25）：**裁掉共线**，同时**整合**「未触发折叠但工具输出已撑满
窗口」那一段的价值。

共线的实测形态（台账 §21.1，本文件按同一构造面复现）：`_TOOL_RESULT_KEEP_RECENT = 3`
曾是「折叠保留」与「microcompact 保留」两处共用的同一个数 —— `build_context` 的真
序列是**先折叠再 microcompact**，而折叠把窗口压到恰好 3 条工具结果，于是
`len(tool_positions) <= 3` 直接返回，占位指针在**真序列上恒不触发**。

契约（修复后）：

1. **触发轴 = 工具结果载荷**合计 token（不是整窗 token），触发线取
   「绝对臂 8k」与「窗口可用额度半数」中更严的一个。「工具输出已撑满窗口、
   而整窗仍未过折叠线」这一段只有按载荷判才覆盖得到 —— 它正是本策略的价值所在；
2. **保留窗 = 载荷份额** `_TOOL_RESULT_KEEP_SHARE`（最新若干条累计载荷不超过载荷
   的一半），与折叠的保留窗（对话消息条数 `keep_min_messages`）是两个各自声明的
   数，因此折叠发生之后 microcompact 仍能动手；至少保留 1 条；
3. 极短结果（< 80 字符，状态码类）恒保留原文；占位指针仍带 call_id 硬地址。

构造面：走生产构造（真 `ContextOrchestrator(use_pool=True)`），只按仓库既有约定
用 `_window_token_budget` 固定窗口预算以脱离 provider 元数据（测试确定性）。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens

_PLACEHOLDER_PREFIX = "[工具输出已移出上下文"


def _agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-microcompact"
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
    agent.agent_id = "a-microcompact"
    return agent


def _orchestrator(budget_tokens: int = 9600) -> ContextOrchestrator:
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget_tokens
    return orch


def _tool_window(pairs: int, chars: int, lead_user: int = 0) -> list:
    """含 `pairs` 组 (assistant.tool_calls, role=tool) 的窗口。

    `lead_user` 追加若干条普通用户消息（用来把整窗 token 抬到触发线之上而
    工具载荷仍在阈值之下——触发轴的判别用例）。
    """
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(lead_user):
        msgs.append({"role": "user", "content": f"普通对话{i}：" + "对话正文内容" * 300})
    filler = "结果数据" * max(1, chars // 4)
    for i in range(pairs):
        msgs.append({
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": f"c{i}", "type": "function",
                            "function": {"name": "read_file", "arguments": "{}"}}],
        })
        msgs.append({"role": "tool", "tool_call_id": f"c{i}", "name": "read_file",
                     "content": f"工具结果{i}: {filler}"})
    return msgs


def _tool_payload_tokens(msgs: list) -> int:
    return estimate_window_tokens([m for m in msgs if (m or {}).get("role") == "tool"])


def _placeholders(msgs: list) -> list:
    return [m for m in msgs if str((m or {}).get("content", "")).startswith(_PLACEHOLDER_PREFIX)]


@pytest.mark.asyncio
async def test_microcompact_fires_after_fold_on_real_sequence():
    """真序列（先折叠再 microcompact）：折叠之后 microcompact 仍必须动手。

    改前：折叠把窗口压到恰好 3 条工具结果 → `len(tool_positions) <= 3` 直接返回，
    占位指针 0 条（共线形态）。
    """
    orch = _orchestrator()
    msgs = _tool_window(pairs=6, chars=3000)
    cap = max(0, orch._resolve_window_token_budget() - orch._ENVELOPE_MIN_TOKENS)

    folded = await orch._apply_window_budget(list(msgs), cap, cache_key="t10c")
    assert len(folded) < len(msgs), "本用例前置：该形状必须触发折叠（否则打不到真序列）"
    tool_rows = [m for m in folded if (m or {}).get("role") == "tool"]
    assert len(tool_rows) == 3, f"本用例前置：折叠后工具行数应为折叠保留窗，实得 {len(tool_rows)}"

    cleared = orch._clear_old_tool_results(folded)

    assert _placeholders(cleared), (
        "折叠之后 microcompact 未动手 —— 两个保留窗仍是同一个数（共线未裁掉）："
        f"折叠后工具行 {len(tool_rows)} 条、载荷 {_tool_payload_tokens(folded)} token"
    )


@pytest.mark.asyncio
async def test_microcompact_fires_when_fold_inert():
    """折叠未触发、工具载荷已撑满窗口：这一段的价值必须整合（不得因解耦而丢）。"""
    orch = _orchestrator()
    msgs = _tool_window(pairs=4, chars=2000)
    cap = max(0, orch._resolve_window_token_budget() - orch._ENVELOPE_MIN_TOKENS)

    folded = await orch._apply_window_budget(list(msgs), cap, cache_key="t10c-inert")
    assert len(folded) == len(msgs), "本用例前置：该形状不得触发折叠（折叠未生效那一段）"
    assert _tool_payload_tokens(folded) > orch._toolPayloadTrigger(
        estimate_window_tokens(folded)
    ), "本用例前置：载荷须过触发线"

    cleared = orch._clear_old_tool_results(folded)

    assert _placeholders(cleared), (
        "折叠未触发但工具载荷已撑满窗口时，microcompact 未动手 —— 该段价值丢失"
    )
    assert all("call=" in m["content"] and "call= " not in m["content"] for m in _placeholders(cleared)), (
        f"占位指针的硬地址为空：{[m['content'] for m in _placeholders(cleared)][:2]}"
    )


def test_keep_window_is_payload_budget_not_fold_keep_count():
    """保留窗按载荷预算声明：工具行数恰等于折叠保留窗（3）时也要动手。"""
    orch = _orchestrator()
    msgs = _tool_window(pairs=3, chars=4000)
    assert _tool_payload_tokens(msgs) > orch._toolPayloadTrigger(estimate_window_tokens(msgs))

    cleared = orch._clear_old_tool_results(msgs)

    kept = [m for m in cleared if (m or {}).get("role") == "tool" and not _placeholders([m])]
    assert _placeholders(cleared), "工具行数 ≤ 折叠保留窗时未动手 —— 保留窗仍与折叠共用一个数"
    assert kept, "保留窗不得把工具原文清空（至少保留 1 条）"


def test_trigger_axis_is_tool_payload_not_whole_window():
    """整窗超触发线但工具载荷未超：零替换（触发轴是载荷，不是整窗）。"""
    orch = _orchestrator()
    msgs = _tool_window(pairs=2, chars=200, lead_user=8)
    assert estimate_window_tokens(msgs) > orch._TOOL_PAYLOAD_TRIGGER_TOKENS, (
        "本用例前置：整窗须过绝对触发线（它按整窗判，按载荷判则不该动手）"
    )
    assert _tool_payload_tokens(msgs) < orch._toolPayloadTrigger(
        estimate_window_tokens(msgs)
    ), "本用例前置：载荷须未过触发线"

    assert orch._clear_old_tool_results(msgs) == msgs


def test_short_results_and_keep_floor():
    """极短结果恒保留原文；保留窗至少 1 条（预算再小也不清空）。"""
    orch = _orchestrator()
    msgs = _tool_window(pairs=4, chars=4000)
    msgs[2] = {"role": "tool", "tool_call_id": "c0", "name": "read_file", "content": "200 OK"}

    cleared = orch._clear_old_tool_results(msgs)

    assert cleared[2]["content"] == "200 OK", "极短工具结果（状态码类）不得被占位"


def test_keep_window_has_a_single_declaration():
    """保留窗只有一处声明：与折叠共用的旧常量不得回流。"""
    orch = _orchestrator()
    assert not hasattr(orch, "_TOOL_RESULT_KEEP_RECENT"), (
        "`_TOOL_RESULT_KEEP_RECENT` 已退役 —— 它与折叠保留窗共用一个数即共线根因"
    )
    assert orch._TOOL_PAYLOAD_TRIGGER_TOKENS > 0
    assert 0 < orch._TOOL_RESULT_KEEP_SHARE <= 1


# ── 触发事实的可观测回执（下游「折叠后续写下一个卡片」的唯一事实源）──────

def test_trigger_readout_is_exposed_after_replacement():
    """替换发生后，触发事实必须可读（不得只留日志）。

    协作红线「不留断点」：写出无人读的字段、只写不读的读数都算断点。本条钉住
    「写入 → 读取」这一环 —— 下游（视图渲染/下一段续写）据此知道本轮工具结果
    被换成了占位指针，而不是靠解析日志猜。
    """
    orch = _orchestrator()
    msgs = _tool_window(pairs=4, chars=4000)

    before = orch.get_context_health()["microcompact"]
    assert before["triggered_calls"] == 0 and before["last_replaced"] == 0, (
        f"未调用前应为空账：{before}"
    )

    orch._clear_old_tool_results(msgs)

    readout = orch.get_context_health()["microcompact"]
    assert readout["triggered_calls"] >= 1, f"触发未记账：{readout}"
    assert readout["last_replaced"] >= 1, f"替换条数未记账：{readout}"
    assert readout["last_kept"] >= 1, f"保留条数未记账：{readout}"
    assert readout["last_payload_tokens"] > readout["last_trigger_tokens"] >= 0, (
        f"载荷与触发线未记账（下游要按它判断强度）：{readout}"
    )
    assert readout["last_payload_tokens"] > 0


def test_not_triggered_is_recorded_without_replacement():
    """未触发也要记账（triggered_calls 不涨），否则"没触发"与"没跑"不可分。"""
    orch = _orchestrator()
    msgs = _tool_window(pairs=2, chars=200, lead_user=8)

    orch._clear_old_tool_results(msgs)

    readout = orch.get_context_health()["microcompact"]
    assert readout["calls"] >= 1, f"调用次数未记账：{readout}"
    assert readout["triggered_calls"] == 0, f"未触发却记成触发：{readout}"
    assert readout["last_replaced"] == 0
    assert 0 < readout["last_payload_tokens"] < readout["last_trigger_tokens"], (
        f"未触发也要给出「离触发线多远」的读数：{readout}"
    )


class TestGuardIsInProtectedSubset:
    """本判据文件必须真被 CI 跑到（B5 收口批的形态：文件在仓、单跑全绿、清单里没有）。"""

    def test_listed_in_protected_tests(self):
        from pathlib import Path

        protected = Path(__file__).resolve().parents[3] / "scripts" / "ci" / "protected_tests.txt"
        listed = {
            line.split("#", 1)[0].strip()
            for line in protected.read_text(encoding="utf-8").splitlines()
            if line.split("#", 1)[0].strip()
        }
        rel = "tests/unit/context/test_microcompact_threshold_decoupling.py"
        assert rel in listed, (
            f"{rel} 不在受保护子集 —— 本守卫的判据在 CI 上不会执行。"
            "修复：加进 scripts/ci/protected_tests.txt（该文件单跑全绿后登记）。"
        )
