#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live-verify：折叠零丢失判据在**真构造面**上真的被校验（Issue #90 · B6-10 批次 B）。

真 `Agent` 语义的编排器构造面（真 `ContextOrchestrator` → 真 `ContextPool`
→ 真归档与真折叠路径），不是手工调校验函数。一条命令复现全部读数：

    PYTHONPATH=. python tests/manual/context_fold_integrity_90.py

四段读数：
1. 折叠集合的指纹域与归档同源（工具结果走 TOOL_CALL）；
2. 折叠集合 ⊆ 池内条目（零丢失判据逐条成立）；
3. 读数面 `get_context_health()["fold_integrity"]` 有值且 `last_error` 为空；
4. 反向控制：把归档集合抹掉后同一输入必须报 `FoldBeforeArchive`（判据不空转）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402
from neurova.context_pool import ContextInput, ContextSource  # noqa: E402

TOOL_PAYLOAD = "工具结果" * 400


def _agent() -> MagicMock:
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "live-verify"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    return agent


def _history() -> list:
    history = [
        {"role": "user", "content": "帮我查一下固件版本"},
        {
            "role": "assistant",
            "content": "调用工具",
            "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "web_search", "arguments": "{}"}}
            ],
        },
        {"role": "tool", "content": TOOL_PAYLOAD, "tool_call_id": "c1", "name": "web_search"},
    ]
    for i in range(1, 8):
        history.append({"role": "user", "content": f"问题{i}: " + "问" * 300})
        history.append({"role": "assistant", "content": f"回答{i}: " + "答" * 300})
    return history


async def _build(orch: ContextOrchestrator) -> None:
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        await orch.build_context(
            user_input="固件 工具结果", session_context=_history(), relevant_memories=[]
        )


def _orchestrator() -> ContextOrchestrator:
    orch = ContextOrchestrator(_agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = 2500
    orch._window_summarizer = None
    return orch


async def main() -> int:
    orch = _orchestrator()
    await _build(orch)

    pool_hashes = set(orch.context_pool._by_hash.keys())
    folded = set(orch._last_folded_hashes)
    tool_hash = ContextInput.compute_hash(ContextSource.TOOL_CALL, TOOL_PAYLOAD)

    print("1) 指纹域同源")
    print(f"   折叠集合 {len(folded)} 条 | 归档集合 {len(orch._last_archived_window_hashes)} 条 "
          f"| 池内 {len(pool_hashes)} 条")
    print(f"   工具结果折叠指纹走 TOOL_CALL 域: {tool_hash in folded}")

    print("2) 零丢失判据（折叠集合 ⊆ 池内条目）")
    missing = folded - pool_hashes
    print(f"   缺失 {len(missing)} 条")

    print("3) 读数面")
    report = orch.get_context_health()["fold_integrity"]
    print(f"   {report}")

    print("4) 反向控制（抹掉归档集合后必须报红）")
    orch._last_archived_window_hashes = set()
    from neurova.context.fold_integrity import verifyFoldIntegrity

    late = verifyFoldIntegrity(folded, set(), orch.context_pool)
    print(f"   折叠早于归档: {late['not_archived_before_fold']} 条 | {late['last_error']}")

    ok = (
        tool_hash in folded
        and not missing
        and report["missing"] == 0
        and report["not_archived_before_fold"] == 0
        and report["last_error"] is None
        and late["not_archived_before_fold"] == len(folded)
        and late["last_error"] is not None
    )
    print("\nLIVE-VERIFY PASSED" if ok else "\nLIVE-VERIFY FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
