#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-03b live-verify：真生产构造面上的每轮会话身份接线（Issue #90 工单 §4bis）。

跑的是**真对象**，不是替身：
1. 真 `Agent`（`agent_core.Agent`）→ 真 `ContextOrchestrator` → 真 `ContextPool`；
2. 身份只经**生产单源**给：`agent.set_request_identity(...)` 写进
   `core.turn_context`，读法就是装配入口用的 `agent.current_session_id`；
3. 两个普通单聊会话先后超预算折叠 → 缓存键必须分槽、视图不得串台；
4. 第二命中点（`pool.session_id` / 条目 metadata）随同一份判据；
5. 无身份轮必须可见（读数面有计数，不静默共用 direct 槽）。

写盘全在系统临时目录（不碰仓库 data/）。
用法：PYTHONPATH=. python tests/manual/turn_identity_wiring_90.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

_TMP = tempfile.mkdtemp(prefix="t03b-turn-identity-")
os.environ["NEUROVA_DATA_DIR"] = _TMP


def _agent(agent_id: str):
    from neurova.agent_core import Agent, AgentConfig

    return Agent(
        AgentConfig(
            name=agent_id, agent_id=agent_id, llm_model="gpt-4o", workspace_path=os.getcwd()
        )
    )


def _long_history(topic: str):
    return [{"role": "user", "content": f"{topic}第{i}条：" + topic * 40} for i in range(12)]


async def _build(orch, *, user_input, history, collab=False, room_id=""):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as tools:
        tools.return_value = "工具描述"
        return await orch.build_context(
            user_input=user_input,
            session_context=history,
            relevant_memories=[],
            chat_collab=collab,
            chat_room_id=room_id,
        )


def main() -> int:
    agent = _agent("t03b-live")
    orch = agent.context_orchestrator
    print(f"1) 真构造面：orchestrator={type(orch).__name__} "
          f"pool session_id={orch.context_pool.session_id!r} "
          f"current_session_id={agent.current_session_id!r}")
    assert orch.context_pool.session_id is None, "生产构造面不该带 session_id 初值"

    orch._window_token_budget = 1200
    summaries: list = []

    async def fake_summary(dropped, previous_summary=""):
        summaries.append(len(dropped))
        text = " ".join((m or {}).get("content", "") for m in dropped or [])
        return "摘要：讨论量子" if "量子" in text else ("摘要：讨论火星" if "火星" in text else "摘要：其他")

    orch._window_summarizer = fake_summary

    print("2) 单聊会话 A（身份仅经生产单源 set_request_identity 给）")
    agent.set_request_identity(user_input="继续 A", session_id="sess-live-a", user_id="u1")
    view_a = asyncio.run(_build(orch, user_input="继续 A", history=_long_history("量子计算")))
    key_a = orch._resolve_window_cache_key()
    print(f"   键={key_a!r} 池 session_id={orch.context_pool.session_id!r} 视图 {len(view_a)} 条")
    assert key_a == "sess-live-a", "单聊身份没进装配入口（键仍退化）"
    assert orch.context_pool.session_id == "sess-live-a", "pool.session_id 没随每轮身份"

    print("3) 单聊会话 B：必须与 A 分槽，视图不得出现 A 的摘要")
    agent.set_request_identity(user_input="继续 B", session_id="sess-live-b", user_id="u1")
    view_b = asyncio.run(_build(orch, user_input="继续 B", history=_long_history("火星殖民")))
    keys = sorted(orch._window_compaction_cache)
    joined_b = "\n".join(str(m.get("content", "")) for m in view_b)
    print(f"   键集合={keys} | B 视图含 A 摘要={'量子' in joined_b}")
    assert {"sess-live-a", "sess-live-b"} <= set(keys), f"两个单聊会话未分槽：{keys}"
    assert "量子" not in joined_b, "单聊 B 的视图注入了 A 的摘要（跨会话串台）"

    print("4) 第二命中点：条目 metadata 与持久台账 session 列同值")
    archived = [
        c
        for c in orch.context_pool.get_contexts()
        if "火星殖民" in str(c.content)
    ]
    assert archived, "会话 B 的内容未入池——本脚本没打到归档路径"
    md_sessions = {(c.metadata or {}).get("session_id") for c in archived}
    print(f"   归档 {len(archived)} 条 | metadata.session_id={md_sessions}")
    assert md_sessions == {"sess-live-b"}, "条目 metadata 的 session_id 未随每轮身份"

    print("5) 协作轮：房间身份优先于每轮 session（作用域只认房间）")
    agent.set_request_identity(user_input="群聊", session_id="sess-live-plain", user_id="u1")
    asyncio.run(
        _build(
            orch,
            user_input="继续",
            history=[{"role": "user", "content": "群内容：项目代号 ZEPHYR-9"}],
            collab=True,
            room_id="project_roomB",
        )
    )
    room_chunks = [c for c in orch.context_pool.get_contexts() if "ZEPHYR-9" in str(c.content)]
    print(f"   pool session_id={orch.context_pool.session_id!r} | "
          f"归档作用域={(room_chunks[0].metadata or {}).get('chat_scope') if room_chunks else None!r}")
    assert orch.context_pool.session_id == "project_roomB", "协作轮房间身份被覆盖"
    assert (room_chunks[0].metadata or {}).get("chat_scope") == "room:project_roomB"

    print("6) 无身份轮必须可见（不静默共用 direct 槽）")
    agent.set_request_identity(user_input="无身份", session_id=None, user_id="u1")
    orch2 = _agent("t03b-live-clean").context_orchestrator
    asyncio.run(
        _build(
            orch2,
            user_input="无身份轮",
            history=[{"role": "user", "content": "没有身份的两条消息"}],
        )
    )
    readout = orch2.get_context_health()["turn_identity"]
    print(f"   读数={readout}")
    assert readout["identityless"] >= 1 and readout["last_key"] == "direct"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
