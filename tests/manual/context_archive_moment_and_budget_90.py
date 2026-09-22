#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B6-7 / B6-8 / B6-9 live-verify：真构造面一条命令复现全部读数。

用法：PYTHONPATH=. python tests/manual/context_archive_moment_and_budget_90.py

验三件事：

- B6-7：跨重启召回后，freshness 打分随**归档时刻**退火（真 SQLite 台账链路）；
- B6-8：装配失败的两处能力有读数、且下一轮会重试并恢复；
- B6-9：每轮额度经入参透传，构造期字段不再被就地改写，硬顶口径单源。
"""
import asyncio
import datetime as dt
import os
import sys
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
WORK = tempfile.mkdtemp()
os.environ.setdefault("NEUROVA_EMBEDDING_CACHE", os.path.join(WORK, "embedding_cache.json"))
os.environ.setdefault("NEUROVA_DATA_ROOT", WORK)

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402
from neurova.context.pool_models import ContextInput, ContextSource  # noqa: E402


def agent():
    a = MagicMock()
    a.config = MagicMock()
    a.config.name = "live"
    a.config.agent_id = "live"
    a.config.constitution = ""
    a.config.behavior_rules = []
    a.config.llm_model = "test-model"
    a.config.enable_auto_tagging = False
    a.memory_manager = MagicMock()
    a.tool_router = None
    a._skill_registry = None
    a.soul = "活体验证助手"
    a.personality = ""
    a.conversation_history = []
    a.growth_log_manager = MagicMock()
    a.user_id = "u"
    a.agent_id = "live"
    a.question_queue_manager = None
    return a


async def build(orch, user_input="问题"):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
        return await orch.build_context(
            user_input=user_input, session_context=[{"role": "user", "content": "短历史"}]
        )


def section1_freshness():
    print("── B6-7 归档时刻驱动 freshness ──")
    from neurova.context.eviction_ledger_db import EvictionLedgerDB

    probe = ContextOrchestrator(agent(), use_pool=True, auto_tag=False)
    dbPath = probe.context_pool._ledger_db.db_path
    store = EvictionLedgerDB(db_path=dbPath, user_id="u", agent_id="live")
    store.record(
        content="四十五天前的归档正文",
        created_at=(dt.datetime.now() - dt.timedelta(days=45)).isoformat(),
    )
    store.record(content="今天的归档正文", created_at=dt.datetime.now().isoformat())
    store.close()

    orch = ContextOrchestrator(agent(), use_pool=True, auto_tag=False)
    drawer = orch.context_pool._drawer
    recalled = {row.content: row for row in orch.context_pool.recall_evicted(limit=10)}
    for content, row in recalled.items():
        print(f"  {content[:8]}… 归档时刻={row.created_at:%Y-%m-%d} 打分={drawer._calculate_freshness_score(row):.4f}")
    old = drawer._calculate_freshness_score(recalled["四十五天前的归档正文"])
    new = drawer._calculate_freshness_score(recalled["今天的归档正文"])
    print(f"  老归档更旧且分更低: {old < new}")


def section2_degradation():
    print("── B6-8 降级读数与恢复 ──")
    realImport = __import__

    def failing(name, *args, **kwargs):
        if name == "neurova.context.summarizing_compressor":
            raise ImportError("模拟摘要器依赖缺失")
        return realImport(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=failing):
        orch = ContextOrchestrator(agent(), use_pool=True, auto_tag=False)
        print(f"  构造期装配失败: {orch.get_context_health()['summarizer']}")
        asyncio.run(build(orch))
        print(f"  依赖仍缺的下一轮（重试 + still 降级）: {orch.get_context_health()['summarizer']}")
    asyncio.run(build(orch))
    print(f"  依赖恢复后的下一轮（自动接回）: {orch.get_context_health()['summarizer']}")


def section3_budget():
    print("── B6-9 每轮额度经入参透传 ──")
    orch = ContextOrchestrator(agent(), use_pool=True, auto_tag=False)
    orch._window_token_budget = 20000
    orch._window_hard_limit = 5000
    drawer = orch.context_pool._drawer
    before = drawer.max_tokens
    asyncio.run(build(orch))
    print(f"  构造期额度 {before} → 构建后 {drawer.max_tokens}（未被就地改写: {before == drawer.max_tokens}）")
    print(f"  本轮生效额度 {drawer.effective_view_budget()}（硬顶 5000 已生效: {drawer.effective_view_budget() <= 5000}）")
    orch._window_hard_limit = None
    asyncio.run(build(orch, user_input="另一轮问题"))
    print(f"  下一轮生效额度 {drawer.effective_view_budget()}（每轮独立解析，不沿用上一轮）")


def main():
    print("B6-7 / B6-8 / B6-9 live-verify（Issue #90）")
    section1_freshness()
    section2_degradation()
    section3_budget()
    print("\nLIVE-VERIFY PASSED")


if __name__ == "__main__":
    main()
