# -*- coding: utf-8 -*-
"""工具轮载荷的窗口预算计量（Issue #90 · T-10c 收口）。

根因（真构造面实测，见台账 §21.3）：窗口计量走 `WindowTokenMeter._contentOf`，
它**只读 `content`**。而 T-10b 之后，`get_recent_model_context()` 把会话台账里的
`metadata.tool_calls` 还原成了 provider 合法的 `assistant.tool_calls` 并放进视图
——这份载荷是要真发给模型（`arguments` 原文串常是调用参数本体，`run_code` 这类
工具一条就上千 token），却**不进任何窗口判据**。

同时展示侧 `composition._measure_messages` 自己算了一份"含 tool_calls、含多模态
分段"的口径。同一批消息因此有两个计量结果 —— 修复教义第 6 条禁止的平行体系。

契约（修复后）：

1. **一份派生**：`window_compactor.messagePayloadTokens()` 是"一条消息对 provider
   的载荷"的唯一派生处（文本内容 + 多模态分段 + `tool_calls` 原文串），
   判据侧（`WindowTokenMeter`）与展示侧（`composition`）都读它，不再各算一份；
2. **判据不得低估**：含工具轮的窗口实测值必须覆盖 `assistant.tool_calls` 的载荷，
   否则"含工具轮的窗口 ≤ 预算"这条 T-10c 判据在工具轮上是空判；
3. **多模态分段不得炸**：`content` 为分段 list 时计量必须给出读数（此前对 list
   做正则匹配直接抛 `TypeError`）。

构造面走生产装配（真 `ContextOrchestrator(use_pool=True)`），只按仓库既有约定用
`_window_token_budget` 固定预算以脱离 provider 元数据（测试确定性）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from neurova.context.composition import _measure_messages
from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.token_estimator import estimate_tokens
from neurova.context.window_compactor import PER_MSG_OVERHEAD, estimate_window_tokens


def _agent():
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a-budget-payload"
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
    agent.agent_id = "a-budget-payload"
    return agent


def _orchestrator(budget_tokens: int = 9600) -> ContextOrchestrator:
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget_tokens
    return orch


def _call(identifier: str, code_chars: int) -> dict:
    """一条 assistant 工具调用：content 为空，载荷全在 arguments 原文串里。"""
    code = "def handler():\n    return 1\n" * max(1, code_chars // 24)
    arguments = '{"code": "%s"}' % code.replace("\n", "\\n")
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [{
            "id": identifier,
            "type": "function",
            "function": {"name": "run_code", "arguments": arguments},
        }],
    }


def _tool_turn_window(turns: int, code_chars: int) -> list:
    msgs = [{"role": "system", "content": "sys"}]
    for i in range(turns):
        msgs.append(_call(f"call_{i}", code_chars))
        msgs.append({
            "role": "tool",
            "tool_call_id": f"call_{i}",
            "name": "run_code",
            "content": "200 OK",
        })
    return msgs


def test_tool_calls_arguments_are_metered():
    """`assistant.tool_calls` 的 arguments 原文是要发给模型的载荷，必须计入。"""
    msgs = [_call("call_x", 3000)]

    assert estimate_window_tokens(msgs) > estimate_tokens(
        msgs[0]["tool_calls"][0]["function"]["arguments"]
    ), (
        "窗口计量漏掉了 assistant.tool_calls 载荷："
        f"整窗读数 {estimate_window_tokens(msgs)}，"
        f"单 arguments 原文就 {estimate_tokens(msgs[0]['tool_calls'][0]['function']['arguments'])} token"
    )


def test_tool_rows_counted_in_window_budget():
    """工单 §11.4 第 2 条的具名判据：含工具轮的窗口实测必须过得住预算。

    真序列形状：工具调用的 arguments 已经把窗口撑爆，而 content 几乎为空。
    改前计量只读 content → 读数远低于 cap → 折叠/清占位/召回额度全部按假读数判。
    """
    orch = _orchestrator()
    msgs = _tool_turn_window(turns=8, code_chars=3000)
    cap = max(0, orch._resolve_window_token_budget() - orch._ENVELOPE_MIN_TOKENS)
    metered = estimate_window_tokens(msgs)

    assert metered > cap, (
        "含工具轮的窗口实测未过预算 —— 工具载荷没进判据："
        f"实测 {metered} / 可用额度 {cap}"
    )

    folded = asyncio.run(orch._apply_window_budget(list(msgs), cap, cache_key="t10c-budget"))

    assert len(folded) < len(msgs), (
        "工具轮撑爆窗口却零折叠（判据读的是不含工具载荷的假读数）："
        f"读数 {metered} / 可用额度 {cap}"
    )


def test_judge_and_display_planes_share_one_derivation():
    """判据侧与展示侧对同一批消息必须给出同一口径（只差协议开销）。

    改前两处各算一份：判据只读 content，展示另加 tool_calls 与多模态分段。
    同一批消息两个数字，就是修复教义第 6 条禁止的平行体系。
    """
    msgs = _tool_turn_window(turns=3, code_chars=2000)
    msgs.append({
        "role": "user",
        "content": [
            {"type": "text", "text": "这张图里是什么"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
        ],
    })

    judge = estimate_window_tokens(msgs)
    display = _measure_messages(msgs)["total_tokens"]

    assert judge == display + len(msgs) * PER_MSG_OVERHEAD, (
        "判据与展示的计量口径分裂："
        f"判据 {judge} / 展示 {display} + {len(msgs)}×{PER_MSG_OVERHEAD}"
    )


def test_multimodal_parts_metered_without_raising():
    """多模态分段（content 为 list）必须能计量：文本段计数 + 图像段按固定值。

    改前对 list 做字符类别正则匹配直接抛 `TypeError`（判据面因此完全没有多模态口径）。
    """
    from neurova.context.window_compactor import messagePayloadTokens

    single = [{"role": "user", "content": [
        {"type": "text", "text": "看图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,xxx"}},
    ]}]

    assert estimate_window_tokens(single) > 0
    assert messagePayloadTokens(single[0]) > estimate_tokens("看图"), (
        "图像段未计入载荷"
    )


def test_payload_derivation_has_a_single_declaration():
    """载荷派生只允许一处：展示侧不得再自带第二份 tool_calls / 多模态口径。"""
    import inspect

    from neurova.context import composition

    source = inspect.getsource(composition)
    assert "json.dumps(tool_calls" not in source, (
        "展示侧仍在自算 tool_calls 计量 —— 载荷派生应只经 "
        "`window_compactor.messagePayloadTokens()`"
    )
    assert "image_url" not in source, (
        "展示侧仍自带多模态计价口径 —— 图像段计价应只经 "
        "`window_compactor.IMAGE_PART_TOKENS`"
    )
