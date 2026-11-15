# -*- coding: utf-8 -*-
"""B5 跑数据：增长门开/关双臂马拉松对照（真 build_context 管线，受控摘要桩）。

回答的问题：增长门（默认关）转正后，在长会话里换来什么、付出什么——
- 门开：占用过下限且增量够大时**主动折叠**（任务间隙折叠，视图峰值更低）；
- 门关（现状）：只有预算击穿才折（视图峰值更高，摘要调用更少）。

度量：摘要 LLM 调用数、折叠代数、视图 token 峰值/均值、可恢复保留率
（B8 同款度量）。确定性：受控摘要桩，无真 LLM。
"""
import asyncio
import os
import sys
from typing import Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from neurova.context.orchestrator import ContextOrchestrator
from neurova.context.window_compactor import estimate_window_tokens
from tests.performance.test_retention_benchmark_b8 import build_marathon, markers_of, measure


def _mk_agent(agent_id: str):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "bench"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "基准助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = MagicMock()
    agent.user_id = "u-b5"
    agent.agent_id = agent_id
    return agent


async def _run_arm(rounds: int, budget: int, gate: bool, agent_id: str) -> Dict:
    from neurova.context.fold_trigger import splitFrozenCoveredPrefix

    orch = ContextOrchestrator(_mk_agent(agent_id), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0

    calls = {"n": 0}

    async def scripted_summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        heads = "；".join(
            str((m or {}).get("content", ""))[:60] for m in (dropped_msgs or [])[:12]
        )
        return f"第{calls['n']}代摘要：{heads}"

    orch._window_summarizer = scripted_summarize

    history = build_marathon(rounds)
    markers = markers_of(rounds)
    view_tokens = []
    folds = []
    final_view: List[dict] = []
    for end in range(len(history)):
        window = history[: end + 1]
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            final_view = await orch.build_context(
                user_input=f"继续第 {end} 步", session_context=window, relevant_memories=[]
            )
        view_tokens.append(estimate_window_tokens(final_view))
        key = orch._resolve_window_cache_key()
        slot = orch._window_compaction_cache.get(key, {})
        folds.append(len(slot.get("generations") or []))

    joined = "".join(str(m.get("content", "")) for m in final_view)
    quality = measure(joined, orch.context_pool, markers)
    return {
        "summary_calls": calls["n"],
        "generations": folds[-1] if folds else 0,
        "peak_view_tokens": max(view_tokens) if view_tokens else 0,
        "mean_view_tokens": int(sum(view_tokens) / len(view_tokens)) if view_tokens else 0,
        "final_view_tokens": view_tokens[-1] if view_tokens else 0,
        **quality,
    }


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


@pytest.mark.asyncio
async def test_growth_gate_on_off_marathon():
    """双臂跑数据：门关（现状） vs 门开（主动折叠）。

    预算给得比单条消息大一个量级：让视图长期在预算内缓增——这正是
    增长门的目标场景（预算击穿前、任务间隙主动收增量）。小预算马拉松
    里击穿每轮都发生，门没有发言权（两臂退化为同一行为）。
    """
    rounds, budget = 40, 20000

    os.environ.pop("NEUROVA_FOLD_GROWTH_GATE", None)
    off = await _run_arm(rounds, budget, gate=False, agent_id="a-b5-off")

    os.environ["NEUROVA_FOLD_GROWTH_GATE"] = "1"
    on = await _run_arm(rounds, budget, gate=True, agent_id="a-b5-on")
    os.environ.pop("NEUROVA_FOLD_GROWTH_GATE", None)

    print("\n[B5 数据] 门关:", {k: v for k, v in off.items()})
    print("[B5 数据] 门开:", {k: v for k, v in on.items()})

    # 质量地板（两臂都必须守住）：无损归档下可恢复率恒 1.0
    assert off["recoverable_retention"] == 1.0
    assert on["recoverable_retention"] == 1.0
    # 门开的价值主张：视图峰值/均值更低（更早把增量收进摘要）
    assert on["peak_view_tokens"] <= off["peak_view_tokens"], (
        f"门开应压低视图峰值：on={on['peak_view_tokens']} off={off['peak_view_tokens']}"
    )
