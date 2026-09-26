#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B6-10 批次 C live-verify：压缩面/去重面收口（真构造面，非单测替身）。

跑法：PYTHONPATH=. python tests/manual/context_compression_single_face_90.py

自证三件事（都走真实生产对象）：
1. 退场模块真的导不到（ModuleNotFoundError），且生产根文本里零引用；
2. 真 **ContextOrchestrator** 构造面可用，且它的压缩通路仍在工作
   （信封+历史确定性淘汰，不是"因为删了所以没跑"）；
3. 真 **ContextPool** 去重仍在工作（入池去重 + 视图层预算取用），
   而池上那两个已删出口确实不存在。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

RETIRED = ("neurova.context.compressor", "neurova.context_compressor")


def step1_retired_modules_are_gone() -> None:
    print("1) 退场模块导入自证")
    for name in RETIRED:
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            print(f"   {name}: ModuleNotFoundError（预期）")
        else:
            raise SystemExit(f"FAILED: {name} 仍可导入")
    hits = []
    for path in (ROOT / "neurova").rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for name in RETIRED:
            if name in text:
                hits.append(f"{path.relative_to(ROOT)} → {name}")
    if hits:
        raise SystemExit("FAILED: 生产侧仍有引用 " + "; ".join(hits))
    print("   生产根 neurova/ 零引用")


def step2_real_orchestrator_compression_still_works() -> None:
    print("2) 真构造面：ContextOrchestrator 的确定性淘汰仍在工作")
    from unittest.mock import MagicMock

    from neurova.context.injector import UnifiedContextInjector
    from neurova.context.models import TokenBudget

    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.llm_model = "gpt-4"
    agent.user_id = "u"
    agent.agent_id = "a"

    inj = UnifiedContextInjector(
        memory_manager=None,
        token_budget=TokenBudget(max_total=400),
        enable_cache=False,
        enable_compression=True,
    )
    if getattr(inj, "_compressor", None) is not None:
        raise SystemExit("FAILED: injector 仍装配了压缩器（装配点未删净）")

    history = [{"role": "user", "content": "很长的历史消息" * 30} for _ in range(6)]
    envelope, hist, ratio = inj._compress_context("信封内容", history, 10, system_tokens=10)
    print(f"   压缩后历史 {len(history)} → {len(hist)} 条；信封保留={bool(envelope)}")
    if len(hist) >= len(history):
        raise SystemExit("FAILED: 确定性淘汰未生效（历史未被淘汰）")
    if not envelope:
        raise SystemExit("FAILED: 预算尚存时信封被整包丢弃")

    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
    print(f"   真 ContextOrchestrator 构造完成；池={type(orch.context_pool).__name__}")


def step3_real_pool_dedup_still_works() -> None:
    print("3) 真构造面：ContextPool 去重 + 视图层取用，且退场出口不存在")
    from neurova.context.pool_models import ContextInput, ContextSource
    from neurova.context_pool import ContextPool

    pool = ContextPool(user_id="u", agent_id="a", max_tokens=200)
    pool.add_context(ContextInput(source=ContextSource.MEMORY, content="同内容", priority=80))
    pool.add_context(ContextInput(source=ContextSource.MEMORY, content="同内容", priority=70))
    pool.add_context(ContextInput(source=ContextSource.MEMORY, content="别的内容", priority=60))
    contents = [c.content for c in pool.get_contexts()]
    print(f"   入池 3 条 → 归档 {len(contents)} 条（同 hash 只出一条）")
    if len(contents) != 2:
        raise SystemExit(f"FAILED: 去重未生效：{contents}")
    same = [c for c in pool.get_contexts() if c.content == "同内容"]
    if not (len(same) == 1 and same[0].priority == 80):
        raise SystemExit("FAILED: 未保留高优先级条目")

    drawn = pool.draw(budget_tokens=60)
    print(f"   视图层取用 {len(drawn)} 条，合计 {sum(c.tokens for c in drawn)} tokens")
    if sum(c.tokens for c in drawn) > 60:
        raise SystemExit("FAILED: 视图层超出预算")
    if len(pool.get_contexts()) != 2:
        raise SystemExit("FAILED: 取用改动了归档（无损归档语义被破坏）")

    for name in ("dedup", "compress_context"):
        if hasattr(ContextPool, name):
            raise SystemExit(f"FAILED: ContextPool.{name} 仍存在")
    print("   ContextPool.dedup / compress_context 均不存在（预期）")


if __name__ == "__main__":
    step1_retired_modules_are_gone()
    step2_real_orchestrator_compression_still_works()
    step3_real_pool_dedup_still_works()
    print("\nLIVE-VERIFY PASSED")
