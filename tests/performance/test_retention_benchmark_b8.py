# -*- coding: utf-8 -*-
"""B8 基准的可重复跑法（CI 稳定档）：小马拉松 × 三臂，锁质量地板。

完整规模（百轮＋真模型三臂对比）属手动基准（另票）；本文件锁定的是
**可复跑的质量地板**：
1. folding 臂可恢复保留率 = 1.0（无损归档 + 检索取回——体系的存在性证明）；
2. folding 的视图保留率 ≥ sliding（滑窗丢掉的旧事实，折叠体系仍可见或可取回）；
3. folding 视图 token < full 视图 token（有界视图——省的就是这个）；
4. sliding 的可恢复率 < 1.0（滑窗的不可恢复丢失是结构性的——对照组意义）。
"""
import os
import sys
from typing import Dict, List, Tuple
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

def build_marathon(rounds: int) -> List[Dict[str, str]]:
    """合成马拉松：每轮一条用户消息（头部植入事实标记）+ 一条助手回执。"""
    history: List[Dict[str, str]] = []
    for i in range(rounds):
        history.append({
            "role": "user",
            "content": f"【事实F{i}】项目{i} 的截止日期是 2031-{(i % 12) + 1:02d}-{(i % 27) + 1:02d}。"
                       f"随后是第 {i} 轮的执行细节：" + "细节" * 120,
        })
        history.append({"role": "assistant", "content": f"收到，项目{i} 已记录并排期。"})
    return history


def markers_of(rounds: int) -> List[str]:
    return [f"【事实F{i}】" for i in range(rounds)]


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
    agent.user_id = "u-b8"
    agent.agent_id = agent_id
    return agent


async def run_folding_arm(rounds: int, budget: int, agent_id: str = "a-b8-fold") -> Dict:
    """folding 臂：真 build_context 管线逐轮推进（归档→折叠→阶梯→召回）。"""
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(_mk_agent(agent_id), use_pool=True, auto_tag=False)
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0

    calls = {"n": 0}

    async def scripted_summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        # 受控摘要桩：保留每条 chunk 头部（植入标记在头部，随摘要进视图）
        heads = "；".join(
            str((m or {}).get("content", ""))[:60] for m in (dropped_msgs or [])[:12]
        )
        return f"第{calls['n']}代摘要：{heads}"

    orch._window_summarizer = scripted_summarize

    history = build_marathon(rounds)
    view: List[dict] = []
    for end in range(len(history)):
        window = history[: end + 1]
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述占位"
            view = await orch.build_context(
                user_input=f"继续第 {end} 步", session_context=window, relevant_memories=[]
            )

    joined = "".join(str(m.get("content", "")) for m in view)
    view_tokens = _estimate(view)
    return {
        "view": view,
        "view_text": joined,
        "view_tokens": view_tokens,
        "pool": orch.context_pool,
    }


def run_sliding_arm(rounds: int, keep_messages: int) -> Dict:
    """sliding 臂：只保留最近 K 条消息的裸窗口（无池、无摘要）。"""
    history = build_marathon(rounds)
    view = history[-keep_messages:]
    joined = "".join(str(m.get("content", "")) for m in view)
    return {
        "view": view,
        "view_text": joined,
        "view_tokens": _estimate(view),
        "pool": None,
    }


def run_full_arm(rounds: int) -> Dict:
    """full 臂：全量上下文（不折、不滑）。"""
    history = build_marathon(rounds)
    joined = "".join(str(m.get("content", "")) for m in history)
    return {
        "view": history,
        "view_text": joined,
        "view_tokens": _estimate(history),
        "pool": None,
    }


def measure(view_text: str, pool, markers: List[str]) -> Dict[str, float]:
    """R(t) 两面：view_retention（直接可见）与 recoverable（可按需取回）。"""
    visible = sum(1 for marker in markers if marker in view_text)

    recoverable = 0
    for marker in markers:
        if marker in view_text:
            recoverable += 1
            continue
        if pool is not None and _recoverable_from_pool(pool, marker):
            recoverable += 1
    total = max(1, len(markers))
    return {
        "view_retention": round(visible / total, 4),
        "recoverable_retention": round(recoverable / total, 4),
    }


def _recoverable_from_pool(pool, marker: str) -> bool:
    """按需取回：池语义检索（B9 同一打分面）或 FTS 台账。"""
    try:
        for drop in pool.search(marker, limit=3):
            if marker in str(getattr(drop, "content", "")):
                return True
    except Exception:  # noqa: BLE001 - 检索失败不算不可恢复，还有 FTS 路
        pass
    try:
        for drop in pool.recall_evicted(query=marker, limit=5):
            if marker in str(getattr(drop, "content", "")):
                return True
    except Exception:  # noqa: BLE001
        pass
    return False


def _estimate(msgs: List[dict]) -> int:
    from neurova.context.window_compactor import estimate_window_tokens

    return estimate_window_tokens(list(msgs))


async def run_benchmark(rounds: int = 24, budget: int = 4000, keep_messages: int = 8) -> Dict[str, Dict]:
    """三臂基准。返回 {arm: {view_retention, recoverable_retention, view_tokens}}。"""
    markers = markers_of(rounds)
    folding = await run_folding_arm(rounds, budget)
    sliding = run_sliding_arm(rounds, keep_messages)
    full = run_full_arm(rounds)

    return {
        "folding": {
            **measure(folding["view_text"], folding["pool"], markers),
            "view_tokens": folding["view_tokens"],
        },
        "sliding": {
            **measure(sliding["view_text"], None, markers),
            "view_tokens": sliding["view_tokens"],
        },
        "full": {
            **measure(full["view_text"], None, markers),
            "view_tokens": full["view_tokens"],
        },
        "_meta": {"rounds": rounds, "budget": budget, "keep_messages": keep_messages,
                  "markers": len(markers)},
    }



@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


@pytest.mark.asyncio
async def test_retention_floor_and_bounded_view():
    result = await run_benchmark(rounds=16, budget=3000, keep_messages=6)
    folding = result["folding"]
    sliding = result["sliding"]
    full = result["full"]

    assert folding["recoverable_retention"] == 1.0, (
        f"无损归档体系下可恢复保留率必须为 1.0：{folding}"
    )
    assert folding["view_retention"] >= sliding["view_retention"], (
        f"折叠臂视图保留率不得低于滑窗：folding={folding} sliding={sliding}"
    )
    assert folding["view_tokens"] < full["view_tokens"], (
        f"折叠臂视图必须小于全量（有界视图）：{folding['view_tokens']} vs {full['view_tokens']}"
    )
    assert sliding["recoverable_retention"] < 1.0, (
        "滑窗臂必须出现结构性不可恢复丢失（对照组的存在的意义）"
    )
