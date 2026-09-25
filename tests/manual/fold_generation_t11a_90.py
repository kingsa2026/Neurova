# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-11a）：折叠分代 —— 旧摘要降一层而非被覆盖。

链路：真 `ContextOrchestrator.build_context`（生产装配，含归档 → 折叠 → 视图）
→ 真 `_advanceFoldGeneration`（代际栈的唯一写入点）→ 真 `get_context_health()["fold_layers"]`
→ 真 `/metrics` 抓取路径（`observe_context_health()`，T-10d 接的既有观测面）。

判据（四条都要过）：
1. 多轮折叠后，**上一代摘要仍以文本原样在场**（不是被覆盖）；
2. 代际栈的档号单调：栈顶 level=1，往深依次 +1；
3. 代际栈超上限时截断**可见**（`truncated` 计数非 0）；
4. 读数经既有观测面可抓取（不新开端点）。

跑法：`PYTHONPATH=. python tests/manual/fold_generation_t11a_90.py`
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from prometheus_client import REGISTRY

from neurova.context.orchestrator import ContextOrchestrator


def _agent():
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
    agent.agent_id = "a-live-t11a"
    return agent


def _round(i: int, chars: int = 900):
    return {"role": "user", "content": f"第{i}轮的长讨论：" + "内容" * (chars // 2)}


async def main() -> None:
    orch = ContextOrchestrator(
        _agent(), use_pool=True, auto_tag=False, session_id="sess-t11a-live"
    )
    orch._window_token_budget = 3000
    orch._DELTA_RESUMMARY_MSGS = 0  # 每轮都真摘要，判据打在分代上而非防抖上

    calls = {"n": 0}

    async def summarizer(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条"

    orch._window_summarizer = summarizer

    history = [_round(i) for i in range(16)]
    for rnd in range(orch._MAX_FOLD_GENERATIONS + 3):
        history = history + [_round(100 + rnd) for _ in range(3)]
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述"
            await orch.build_context(
                user_input=f"第{rnd}轮追问", session_context=history, relevant_memories=[]
            )

    slot = orch._window_compaction_cache["sess-t11a-live"]
    stack = slot.get("generations") or []
    readout = orch.get_context_health()["fold_layers"]

    print(f"[1 代际栈] 摘要 LLM 调用 {calls['n']} 次 | 栈深 {len(stack)}")
    for node in stack:
        print(f"           level={node['level']} :: {node['summary']}")

    # 判据 1：**上一代文本原样在场**——栈里保留的每一代文本都必须是某次
    # 折叠的原文（不是被拼接/改写的合成长文，那是 §12.5 第 1 条假实现）。
    texts = [n["summary"] for n in stack]
    assert all(t.startswith("第") and "代摘要：覆盖" in t for t in texts), (
        f"代际节点文本不是折叠原文（疑似拼接冒充多层）：{texts}"
    )
    # 相邻两代确实是**不同的历史覆盖范围**（同文本重复入栈就是假分代）
    assert len(set(texts)) == len(texts), f"代际栈出现重复节点：{texts}"
    # 被截断掉的那几代：读数里如实可见（不是静默丢）
    assert calls["n"] == len(stack) + readout["truncated"], (
        f"摘要调用 {calls['n']} 次，栈内 {len(stack)} + 截断 {readout['truncated']}"
        " 对不上 —— 有一代既不在栈里也没被记为截断"
    )

    # 判据 2：档号单调 —— 栈顶 1，往深 +1
    levels = [n["level"] for n in stack]
    assert levels == sorted(levels) and levels[0] == 1, f"档号非单调或栈顶不是 1：{levels}"

    # 判据 3：截断可见
    assert readout["truncated"] > 0, f"截断发生了却无读数：{readout}"
    assert readout["levels"] == len(stack)

    # 判据 4：既有观测面可抓取（kind=fold_layers）
    orch.get_context_health()  # 编排器单源持有
    samples = [
        s
        for metric in REGISTRY.collect()
        for s in metric.samples
        if s.name == "neurova_context_health_value" and s.labels.get("kind") == "fold_layers"
    ]
    from neurova.core.metrics import get_metrics
    from types import SimpleNamespace

    get_metrics().observe_context_health(
        SimpleNamespace(agents={"a-live-t11a": SimpleNamespace(context_orchestrator=orch)})
    )
    samples = [
        s
        for metric in REGISTRY.collect()
        for s in metric.samples
        if s.name == "neurova_context_health_value"
        and s.labels.get("kind") == "fold_layers"
    ]
    assert samples, "fold_layers 读数未出现在既有观测面（写了没人读 = 断点）"
    print(f"[4 抓取] fold_layers 序列数={len(samples)}；样例={samples[0].labels} {samples[0].value}")

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    asyncio.run(main())
