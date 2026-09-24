#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-03b 的 live-verify：每轮会话身份在真构造面上贯通（Issue #90 工单 §4bis）。

跑的是**真生产对象**，不是单测替身：

1. 真 `Agent` 实例（`Agent.__new__` + 与 `agent_core.init_memory` 同型的成员），
   身份面走**真 property** `Agent.current_session_id` → `TurnState` →
   `core.turn_context` 的 ContextVar（与 `chat_pipeline._init_agent_state` 同型写入）；
2. 真 `ContextOrchestrator` + 真 `ContextPool` + 真 SQLite 持久台账
   （写盘全在系统临时目录，经唯一注入口 `NEUROVA_DATA_DIR`）；
3. 真折叠路径（真 `window_compactor`，经 `build_context` 触发超预算折叠）。

复现三条命中点（同一根因）：
  A 折叠摘要缓存键 —— 两个单聊会话不得共槽；
  B 池归属 + 条目 metadata + 持久台账 session 列 —— 非协作轮不得写 None；
  C 预算读数 `used_tokens` —— 必须取**本会话**的实测快照。

一条命令复现：PYTHONPATH=. python tests/manual/turn_session_identity_t03b_90.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault(
    "NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="t03b-live-")
)


def _agent():
    """与 `agent_core` 构造面同型的真 Agent 壳：身份面是**真 property**。"""
    from neurova.agent_core import Agent

    agent = Agent.__new__(Agent)
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.agent_id = "a1"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.enable_auto_tagging = False
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u1"
    agent.agent_id = "a1"
    agent.llm_client = MagicMock()
    return agent


async def _build(orch, history):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as tools:
        tools.return_value = "工具描述"
        return await orch.build_context(
            user_input="继续",
            session_context=history,
            relevant_memories=[],
            chat_collab=False,
        )


def main() -> int:
    from neurova.context.orchestrator import ContextOrchestrator
    from neurova.core.turn_context import set_turn_identity
    from neurova.agent_core import Agent

    agent = _agent()
    assert isinstance(
        Agent.current_session_id, property
    ), "身份读面不是真 property —— 本探针走的不是生产链路"
    orch = ContextOrchestrator(agent, use_pool=True)
    orch._window_token_budget = 1200

    summaries: list = []

    async def summarize(dropped, previous_summary=""):
        summaries.append(previous_summary)
        return f"摘要{len(summaries)}"

    orch._window_summarizer = summarize

    print("A) 折叠摘要缓存键：两个单聊会话各自分槽")
    for sid, topic in (("sess_one", "量子计算"), ("sess_two", "火星殖民")):
        set_turn_identity("继续", sid, "u1")
        history = [
            {"role": "user", "content": f"{sid} 第{i}条：" + topic * 60} for i in range(12)
        ]
        view = asyncio.run(_build(orch, history))
        keys = sorted(orch._window_compaction_cache)
        print(f"   {sid} 折叠后缓存键 = {keys}")
        if sid == "sess_two":
            joined = "\n".join(str(m.get("content", "")) for m in view)
            print(f"   第二会话视图含第一会话摘要 = {'摘要1' in joined}")
            assert "摘要1" not in joined, "两个单聊会话共用了折叠摘要槽"
    assert sorted(orch._window_compaction_cache) == ["sess_one", "sess_two"], (
        f"键不是本轮真实身份：{sorted(orch._window_compaction_cache)}"
    )
    assert len(summaries) >= 2, "第二会话没有各自生成摘要（没打到折叠路径）"

    print("B) 池归属 / 条目 metadata / 持久台账 session 列")
    set_turn_identity("继续", "sess_ledger", "u1")
    asyncio.run(
        _build(orch, [{"role": "user", "content": "台账会话列探针内容"}])
    )
    print(f"   context_pool.session_id = {orch.context_pool.session_id!r}")
    assert orch.context_pool.session_id == "sess_ledger", "非协作轮把 None 写进池归属"

    entries = [
        c for c in orch.context_pool.get_contexts() if "台账会话列探针内容" in str(c.content)
    ]
    assert entries, "本轮历史未入池（没打到归档路径）"
    md_sessions = {c.metadata.get("session_id") for c in entries}
    print(f"   条目 metadata.session_id = {md_sessions}")
    assert md_sessions == {"sess_ledger"}, f"条目会话归属缺失：{md_sessions}"

    ledger = orch.context_pool._ledger_db
    assert ledger is not None, "编排器未装配持久台账"
    rows = [
        dict(r) for r in ledger.recentRows(50) if "台账会话列探针内容" in r["content"]
    ]
    assert rows, "归档未写穿持久台账"
    row_sessions = {r["session_id"] for r in rows}
    print(f"   持久台账行 session 列 = {row_sessions}")
    assert row_sessions == {"sess_ledger"}, f"台账会话列为 {row_sessions}"

    print("C) 预算读数的 used_tokens 取本会话快照")
    from neurova.context.composition import measure_composition

    measure_composition(
        agent_id="a1",
        messages=[{"role": "user", "content": "z"}],
        tools=None,
        session_id="sess_ledger",
    )
    measure_composition(
        agent_id="a1",
        messages=[{"role": "user", "content": "y" * 8000}],
        tools=None,
        session_id="sess_other",
    )
    used = orch.get_token_budget()["used_tokens"]
    print(f"   used_tokens = {used}（本会话真值 = 1，另一会话 = 2000）")
    assert used == 1, f"预算读数取了别的会话的快照：{used}"

    print("D) 无身份轮必须可见（计数 + 点名，不静默共槽）")
    set_turn_identity("继续", None, "u1")
    orch._resolve_window_cache_key()
    report = orch.get_context_health()["session_identity"]
    print(f"   session_identity 读数 = {report}")
    assert report["identityless_turns"] >= 1, "无身份轮没有被计数"
    assert report["last_error"] and "IdentitylessTurn" in report["last_error"], (
        "无身份轮没有点名原因（教义第 2 条：不许静默）"
    )

    print("E) 上限策略是最近使用（LRU），不是插入序")
    # 键数此前恒 1（身份取不到），上限无从触发；身份接通后槽数才真增长，
    # 故上限口径必须与接线同批验证：被反复引用的老会话不该因"建得早"先丢。
    def _lruHistory(label):
        return [{"role": "user", "content": f"{label} 第{i}条：" + "内容" * 60} for i in range(12)]

    def _foldFor(sid):
        set_turn_identity("继续", sid, "u1")
        asyncio.run(_build(orch, _lruHistory(f"会话 {sid}")))

    # 前几段留下的槽先清掉，只观察本段：填满 → **回访最早那个** → 再进一个新会话。
    orch._window_compaction_cache.clear()
    for i in range(orch._WINDOW_CACHE_SLOTS):
        _foldFor(f"sess_{i}")
    _foldFor("sess_0")          # 回访：sess_0 成为「最近使用」
    _foldFor("sess_newest")     # 该淘汰的是 sess_1（最久未使用），不是 sess_0
    slots = sorted(orch._window_compaction_cache)
    print(f"   槽数 = {len(slots)}（上限 {orch._WINDOW_CACHE_SLOTS}）| sess_0 仍在 = {'sess_0' in slots}")
    print(f"   槽 = {slots}")
    assert len(slots) <= orch._WINDOW_CACHE_SLOTS, f"槽数超上限：{len(slots)}"
    assert "sess_0" in slots, (
        "刚回访过的槽被淘汰 —— 淘汰口径是插入序（建得早先丢），"
        "不是工单 §4bis 要求的最近使用"
    )

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
