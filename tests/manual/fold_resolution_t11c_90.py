# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-11c）：视图按距离几何退避装配多档分辨率概览。

链路：真 `ContextOrchestrator.build_context`（生产装配：归档 → 折叠 → 代际推进
→ 分辨率装配）→ 真池层索引 `summaryLayers()` → 真 `get_context_health()["fold_resolution"]`
→ 真 `/metrics` 抓取路径（`observe_context_health()`，T-10d 接的既有观测面）。

判据（六条都要过）：
1. 视图内档数 ≥ 3，且相邻档预算比 = 4（1:4:16 的相邻比，容差 ±25%）；
2. 概览行按**位置由远及近**排列（老 → 新），每行都带可解析 `covers_ref`；
3. 每行**实测 token ≤ 其授予预算**（预算不是摆设），且截断字符数可见；
4. 单调性：按位置分辨率（每覆盖一轮的 token 数）非递增；
5. 越界/旁路：视图里不含池内层节点的**原文行**（索引节点仍不参加概率性召回）；
6. 回退等式：`NEUROVA_CONTEXT_FOLD_RESOLUTION=0` 时视图逐字回到本票之前的形状
   （只有一行摘要），读数如实 `enabled=False`。

跑法：`PYTHONPATH=. python tests/manual/fold_resolution_t11c_90.py`
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaT11cLive_"))

from prometheus_client import REGISTRY  # noqa: E402

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402


def _agent(agentId: str = "a-live-t11c"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
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
    agent.agent_id = agentId
    return agent


def _round(i: int, chars: int = 1200):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


def _orchestrator(agentId: str, budget: int = 8000):
    orch = ContextOrchestrator(
        _agent(agentId), use_pool=True, auto_tag=False, session_id=f"sess-{agentId}"
    )
    orch._window_token_budget = budget
    orch._DELTA_RESUMMARY_MSGS = 0
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条。" + "细节" * 120

    orch._window_summarizer = _summarize
    return orch, calls


async def _foldMany(orch, rounds: int = 6):
    history = [_round(i) for i in range(14)]
    view = await _build(orch, history)
    for rnd in range(rounds - 1):
        history = history + [_round(100 + rnd)]
        view = await _build(orch, history)
    return view


async def _build(orch, history):
    with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
        m.return_value = "工具描述"
        return await orch.build_context(
            user_input="继续", session_context=history, relevant_memories=[]
        )


def _entries(orch, view):
    from neurova.context.fold_index import parseCoversRef
    from neurova.context.token_estimator import estimate_tokens

    layers = {layer["fold_seq"]: layer for layer in orch.context_pool.summaryLayers()}
    out = []
    for msg in view:
        content = str(msg.get("content", ""))
        if msg.get("role") != "system" or "早期对话摘要" not in content:
            continue
        parsed = parseCoversRef(content)
        assert parsed is not None, f"概览行不带引用：{content[-60:]!r}"
        layer = layers.get(parsed[0])
        assert layer is not None, f"引用 {parsed[0]} 在索引里不存在（悬空引用）"
        out.append({"level": layer["level"], "content": content,
                    "tokens": estimate_tokens(content), "layer": layer})
    return out


async def main() -> None:
    orch, calls = _orchestrator("live-t11c")
    view = await _foldMany(orch, rounds=6)
    entries = _entries(orch, view)
    readout = orch.get_context_health()["fold_resolution"]

    levels = sorted({entry["level"] for entry in entries})
    print(f"[1 档位] 池内索引 {len(orch.context_pool.summaryLayers())} 档 | 视图装配 {len(levels)} 档 "
          f"| 摘要调用 {calls['n']} 次 | level_budgets={tuple(readout['level_budgets'])}")
    for entry in entries:
        print(f"   level={entry['level']} tokens={entry['tokens']} :: {entry['content'][:64].replace(chr(10), ' | ')}")

    assert len(levels) >= 3, f"视图档数 {len(levels)} 少于三档：{levels}（判据 1）"
    budgets = list(readout["level_budgets"])[:3]
    ratios = [round(near / far, 2) for near, far in zip(budgets, budgets[1:])]
    assert len(ratios) >= 2 and all(4 * 0.75 <= r <= 4 * 1.25 for r in ratios), (
        f"相邻档预算比 {ratios} 不在 4 ±25%（判据 1）"
    )
    print(f"[1 几何退避] 前{len(budgets)}档预算={budgets} 相邻比={ratios} ✓")

    # 判据 2：位置序由远及近（老 → 新）
    order = [entry["level"] for entry in entries]
    assert order == sorted(order, reverse=True), f"概览行未按由远及近排列：{order}"
    print(f"[2 位置序] 档号序列={order}（由远及近）✓")

    # 判据 3：实测 token ≤ 授予预算，且截断可见
    byLevel = dict(zip(levels, readout["level_budgets"]))
    for entry in entries:
        assert entry["tokens"] <= byLevel[entry["level"]], (
            f"level {entry['level']} 实测 {entry['tokens']} 超授予预算 {byLevel[entry['level']]}"
        )
    assert readout["truncated_chars"] > 0, "远档预算小于其文本却报零截断（截断不可见）"
    print(f"[3 预算与截断] 每行实测 ≤ 授予预算 ✓ | 截断字符={readout['truncated_chars']} ✓")

    # 判据 4：单调性（每覆盖一轮的 token 数非递增）
    densities = []
    for entry in sorted(entries, key=lambda e: e["level"]):
        span = entry["layer"]["covers"]["turn_range"]
        covered = max(1, int(span[1]) - int(span[0]) + 1)
        densities.append((entry["level"], round(byLevel[entry["level"]] / covered, 3)))
    for (nearL, nearD), (farL, farD) in zip(densities, densities[1:]):
        assert nearD >= farD, f"更远的档分辨率更高：level {farL} {farD} > level {nearL} {nearD}"
    print(f"[4 单调性] 每覆盖轮 token（由近及远）={[d for _, d in densities]} ✓")

    # 判据 5：层节点原文行不得混进视图（索引面与召回面分工不得被本票破掉）
    layerTexts = {layer["content"] for layer in orch.context_pool.summaryLayers()}
    duplicated = [
        msg.get("content") for msg in view
        if str(msg.get("content")) in layerTexts
    ]
    assert not duplicated, f"索引节点原文以独立行重复注入视图：{duplicated[:1]}"
    print("[5 召回分工] 索引节点原文未重复注入 ✓")

    # 判据 6：回退等式（关掉开关 → 一行摘要）
    os.environ["NEUROVA_CONTEXT_FOLD_RESOLUTION"] = "0"
    try:
        offOrch, _ = _orchestrator("live-t11c-off")
        offView = await _foldMany(offOrch, rounds=4)
        offRows = [
            m for m in offView
            if m.get("role") == "system" and "早期对话摘要" in str(m.get("content", ""))
        ]
        offReadout = offOrch.get_context_health()["fold_resolution"]
        assert len(offRows) == 1, f"开关关闭时视图仍装配 {len(offRows)} 行概览（回退等式不成立）"
        assert offReadout["enabled"] is False, f"开关关闭但读数未如实标注：{offReadout}"
        assert offReadout["levels"] == 1, f"开关关闭却报装配多档：{offReadout}"
        print(f"[6 回退开关] 关闭后概览行=1 | enabled={offReadout['enabled']} levels={offReadout['levels']} ✓")
        offOrch.context_pool.close()
    finally:
        os.environ.pop("NEUROVA_CONTEXT_FOLD_RESOLUTION", None)

    # 判据 7：读数经既有观测面可抓取
    from neurova.core.metrics import get_metrics

    get_metrics().observe_context_health(
        SimpleNamespace(agents={"live-t11c": SimpleNamespace(context_orchestrator=orch)})
    )
    samples = [
        s
        for metric in REGISTRY.collect()
        for s in metric.samples
        if s.name == "neurova_context_health_value"
        and s.labels.get("kind") == "fold_resolution"
    ]
    assert samples, "fold_resolution 读数未出现在既有观测面（写了没人读 = 断点）"
    print(f"[7 抓取] fold_resolution 序列数={len(samples)}；样例={samples[0].labels} {samples[0].value}")

    orch.context_pool.close()
    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    asyncio.run(main())
