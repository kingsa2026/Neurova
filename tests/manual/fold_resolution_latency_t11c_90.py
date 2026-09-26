# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · T-11c 判据 6 的延迟侧）：开关关闭/开启两遍的可比 A/B 读数。

## 为什么单独一个脚本、且**不进 CI**

工单 §12.7 判据 6 的延迟口径是「视图构建延迟 p95 ≤ 关闭时基线 ×1.2，基线实测值
写进测试注释（不许空写目标数）」。它要的是**两遍可比实测**：同一条轨迹、同一台
机器，`NEUROVA_CONTEXT_FOLD_RESOLUTION` 关 / 开各跑一遍。

本条**不固化为常驻判据**，理由与同族两处一致（`test_ci_wallclock_assertion_ledger`
与 `test_clock_caliber_ledger` 的台账口径）：

- 它是**机时契约**（同机 A/B 比值），不是结构契约。本仓已两次因"结构性契约被编码成
  墙钟阈值"在 py3.11 绿、py3.12 红（同一个 commit、同一份代码）；
- 本机实测比值区间宽：连续 3 轮的 p95 比值实测 **0.99–1.72**（见下方"实测读数"），
  1.72 那一轮是 GC/调度抖动，不是装配器的成本 —— 阈值 1.2 上没有任何裕量；
- 把它做成常驻判据的**误判方向**是"负载越高越红"，那恰好会把真正的尾延迟回归
  一并放行（教义第 2 条明禁的"降级断言换绿"）。

故本条以**结构不变量**承担常驻门禁（`tests/unit/context/test_fold_resolution_t11c.py`
的 `test_assembly_work_does_not_scale_with_trajectory_length`：装配工作量由概览区
额度界定、**不随索引档数增长**），本脚本只负责把可比读数**真跑出来**供留存。

## 实测读数（本容器，2026-09-26；30 轮、budget 8000、§12.7 轨迹形态）

时间口径 = 本线程 CPU（`time.thread_time`，等待不计入；与 `scripts/ci/perf_gate.py`
的判分口径同一份）。跳过前 3 轮预热。

```
trial0: off p50=17.17ms p95=21.59ms | on p50=17.65ms p95=23.36ms | p95比=1.08
trial1: off p50=16.64ms p95=21.09ms | on p50=18.20ms p95=23.36ms | p95比=1.11
trial2: off p50=16.19ms p95=23.59ms | on p50=17.79ms p95=24.36ms | p95比=1.03
```

即开启多档装配的增量约 **1–2ms/轮**，p95 比值落在判据线 1.2 内，且裕量约 8–16%
—— 裕量偏小，这正是它不做常驻门禁的原因（常驻门禁取结构面，不信这个比值）。

跑法：`PYTHONPATH=. python tests/manual/fold_resolution_latency_t11c_90.py`
"""

from __future__ import annotations

import asyncio
import logging
import os
import statistics
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaT11cLat_"))
logging.disable(logging.INFO)

from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402

TRIALS = 3
ROUNDS = 30
WARMUP = 3


def _agent(agentId: str):
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


def _round(i: int) -> dict:
    """§12.7 测量规程的三形态混合轨迹（中文散文 : 英文散文 : JSON = 4:4:2）。"""
    kind = i % 5
    if kind in (0, 1):
        body = "本轮讨论产品演进路线与验收口径。" * 60
    elif kind in (2, 3):
        body = "This round reviews the roadmap and the acceptance criteria. " * 40
    else:
        body = '{"trace":["' + "a" * 1200 + '"],"ok":true}'
    return {"role": "user", "content": f"第{i}轮：{body}"}


def _p95(samples) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


async def _run(tag: str, enabled: bool) -> list:
    os.environ["NEUROVA_CONTEXT_FOLD_RESOLUTION"] = "1" if enabled else "0"
    orch = ContextOrchestrator(
        _agent(f"lat-{tag}"), use_pool=True, auto_tag=False, session_id=f"sess-{tag}"
    )
    orch._window_token_budget = 8000
    orch._DELTA_RESUMMARY_MSGS = 0
    calls = {"n": 0}

    async def _summarize(dropped_msgs, previous_summary=""):
        calls["n"] += 1
        return f"第{calls['n']}代摘要：覆盖 {len(dropped_msgs)} 条。" + "细节" * 120

    orch._window_summarizer = _summarize

    async def _build(history):
        with patch.object(orch, "get_tools_description", new_callable=AsyncMock) as m:
            m.return_value = "工具描述"
            return await orch.build_context(
                user_input="继续", session_context=history, relevant_memories=[]
            )

    history = [_round(i) for i in range(14)]
    samples = []
    try:
        for rnd in range(ROUNDS):
            if rnd:
                history = history + [_round(100 + rnd - 1)]
            started = time.thread_time()
            await _build(history)
            samples.append((time.thread_time() - started) * 1000.0)
    finally:
        orch.context_pool.close()
        os.environ.pop("NEUROVA_CONTEXT_FOLD_RESOLUTION", None)
    return samples[WARMUP:]


async def main() -> None:
    ratios = []
    for trial in range(TRIALS):
        off = await _run(f"off{trial}", False)
        on = await _run(f"on{trial}", True)
        ratio = _p95(on) / max(1e-9, _p95(off))
        ratios.append(ratio)
        print(
            f"trial{trial}: off p50={statistics.median(off):.2f}ms p95={_p95(off):.2f}ms | "
            f"on p50={statistics.median(on):.2f}ms p95={_p95(on):.2f}ms | p95比={ratio:.3f}"
        )
    print(
        f"[判据6 延迟侧] p95 比 min={min(ratios):.3f} max={max(ratios):.3f} "
        f"上界=1.2 全部落内={all(r <= 1.2 for r in ratios)}"
    )


if __name__ == "__main__":
    asyncio.run(main())
