#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B6-10 批次 D 的 live-verify：真构造面复现两条死线的终局（Issue #90）。

跑的是**真生产对象**，不是单测替身：
1. 真 `Agent` 构造面（`agent_core.init_memory` 同型）拿真 `ContextOrchestrator`
   与真 `ContextPool`（真 SQLite 台账，写盘全在系统临时目录）；
2. TTL 回收：生产档 `ttl_seconds=0` 必须一条不动；显式给出短 TTL 时，写入路径
   必须在下一次写入前把过期条目归档剔除，且该内容仍可经 `recall_evicted` 取回；
3. 会话身份：`build_context` 每轮刷新是**唯一**可变写入点 —— 换房间即写进池，
   而构造期初值不被就地改写；实例级 setter 在生产侧不存在。

一条命令复现：PYTHONPATH=. python tests/manual/ttl_reclaim_and_session_identity_90.py
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _agent_shape():
    """与 `neurova/agent_core.py` 的 init_memory 同型的 Agent 替身（成员齐备）。"""
    agent = MagicMock()
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
    return agent


def main() -> int:
    from neurova.context.eviction_ledger_db import EvictionLedgerDB
    from neurova.context.orchestrator import ContextOrchestrator
    from neurova.context.pool_models import ContextInput, ContextSource
    from neurova.context_pool import ContextPool

    with tempfile.TemporaryDirectory(prefix="ttl-identity-90-") as tmp:
        print("1) 生产档 ttl_seconds=0（永不丢失）：回收一条不动")
        pool = ContextPool(user_id="u1", agent_id="a1", session_id="s1", ttl_seconds=0)
        stale = ContextInput(source=ContextSource.CONVERSATION, content="久远条目")
        stale.created_at = dt.datetime.now() - dt.timedelta(days=7)
        pool.add_context(stale)
        pool.add_context(ContextInput(source=ContextSource.CONVERSATION, content="新条目"))
        print(f"   常驻 {pool.resident_count()} 条 | ttl 回收计数 "
              f"{pool.get_retention_stats()['archived_by_reason']['ttl']}")
        assert pool.resident_count() == 2, "生产档下 TTL 不应回收任何条目"

        print("2) 短 TTL：写入路径即回收点，且内容仍可召回（无损归档）")
        ledger = EvictionLedgerDB(
            db_path=Path(tmp) / "l.db", user_id="u1", agent_id="a1"
        )
        live = ContextPool(
            user_id="u1", agent_id="a1", session_id="s1",
            ttl_seconds=60, ledger_db=ledger,
        )
        expired = ContextInput(source=ContextSource.CONVERSATION, content="过期内容：上海天气讨论")
        expired.created_at = dt.datetime.now() - dt.timedelta(seconds=3600)
        live.add_context(expired)
        live.add_context(ContextInput(source=ContextSource.CONVERSATION, content="新条目"))
        recalled = live.recall_evicted(query="上海天气")
        print(f"   写入后常驻 {live.resident_count()} 条 | ttl 回收计数 "
              f"{live.get_retention_stats()['archived_by_reason']['ttl']} | "
              f"召回 {len(recalled)} 条")
        assert live.resident_count() == 1, "过期条目未被写入路径回收"
        assert recalled and "上海天气" in recalled[0].content, "回收把内容丢掉了"

        print("3) 会话身份：唯一可变写入点是每轮刷新")
        orch = ContextOrchestrator(_agent_shape(), use_pool=True, session_id="s1")
        print(f"   构造期初值 session_id={orch.session_id!r} | "
              f"实例级 setter 存在: {hasattr(orch, 'set_session_id')}")
        assert orch.session_id == "s1"
        assert not hasattr(orch, "set_session_id"), "第二写入方仍在（身份有两处可写）"

        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as tools:
            tools.return_value = "工具描述"
            asyncio.run(
                orch.build_context(
                    user_input="继续",
                    session_context=[{"role": "user", "content": "hi"}],
                    relevant_memories=[],
                    chat_collab=True,
                    chat_room_id="project_roomB",
                )
            )
        print(f"   轮次刷新后 context_pool.session_id={orch.context_pool.session_id!r} | "
              f"构造期初值={orch.session_id!r}")
        assert orch.context_pool.session_id == "project_roomB", "本轮有效会话没写进池"
        assert orch.session_id == "s1", "构造期初值被就地改写（身份又变成两处可写）"

    print("LIVE-VERIFY PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
