#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Issue #90 · T-10c 前置裁定 live-verify：microcompact 两根轴各自声明（真链路）。

走**真构造面**，不手工调 `_clear_old_tool_results` 之外的任何替身：

1. 真 `ContextOrchestrator`（生产构造形状）→ 真 `_apply_window_budget`（折叠）
   → 真 `_clear_old_tool_results`（microcompact）→ 真视图装配；
2. 三段形状各跑一遍：折叠已触发（真序列）、折叠未触发但载荷已撑满窗口、小载荷；
3. 读数取 `get_context_health()["microcompact"]`（触发回执的唯一消费面）。

改前本条第一、二段即红（占位 0 条 —— 两处保留窗共线，microcompact 恒不触发）。

用法：
    PYTHONPATH=. python tests/manual/microcompact_threshold_t10c_90.py
"""
import asyncio
import sys
from pathlib import Path

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from unittest.mock import AsyncMock, MagicMock, patch

from neurova.context.orchestrator import ContextOrchestrator


def make_agent():
    a = MagicMock()
    a.config = MagicMock()
    a.config.name = "lv"
    a.config.agent_id = "lv_agent"
    a.config.llm_model = "test-model"
    a.config.constitution = ""
    a.config.behavior_rules = []
    a.config.enable_auto_tagging = False
    a.memory_manager = MagicMock()
    a.context_builder = MagicMock()
    a.tool_router = None
    a._skill_registry = None
    a.soul = "lv"
    a.personality = ""
    a.conversation_history = []
    a.growth_log_manager = MagicMock()
    a.user_id = "u1"
    a.agent_id = "lv_agent"
    return a


def session(n_pairs, chars):
    msgs = [{"role": "user", "content": "开始"}]
    filler = "工具输出正文 " * (chars // 7)
    for i in range(n_pairs):
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"id": f"call_lv_{i}", "type": "function",
                                     "function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "tool_call_id": f"call_lv_{i}", "name": "read_file",
                     "content": f"第{i}份结果: {filler}"})
    return msgs


async def run(n_pairs, chars, label):
    orch = ContextOrchestrator(make_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = 9600
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        ctx = await orch.build_context(
            user_input="继续", session_context=session(n_pairs, chars), relevant_memories=[]
        )
    placeholders = [x for x in ctx if str(x.get("content", "")).startswith("[工具输出已移出上下文")]
    folded = [x for x in ctx if "[早期对话摘要]" in str(x.get("content", ""))]
    tool_rows = [x for x in ctx if x.get("role") == "tool"]
    health = orch.get_context_health().get("microcompact", "（字段不存在：改前形态）")
    print(f"[{label}] pairs={n_pairs} chars={chars} 视图行={len(ctx)} "
          f"折叠摘要行={len(folded)} tool行={len(tool_rows)} 占位={len(placeholders)}")
    print(f"          microcompact 读数={health}")
    if placeholders:
        print(f"          首条占位={placeholders[0]['content'][:78]}")
    return len(placeholders), health


async def main():
    a = await run(6, 3000, "折叠已触发（真序列：先折叠后 microcompact）")
    b = await run(4, 2000, "折叠未触发但工具载荷已撑满窗口")
    c = await run(2, 200, "小载荷（不应动手）")
    print()
    ok = a[0] > 0 and b[0] > 0 and c[0] == 0
    print("LIVE-VERIFY", "PASSED" if ok else "FAILED")
    sys.exit(0 if ok else 1)


asyncio.run(main())
