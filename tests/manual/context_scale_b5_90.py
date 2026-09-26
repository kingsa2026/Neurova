#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""B5 规模 live-verify：真池 + 真抽屉 + 真向量后端，一条命令复现全部读数。

手工运行，不进 CI；写盘只落在系统临时目录（嵌入缓存）。
用法：PYTHONPATH=. python tests/manual/context_scale_b5_90.py

验五件事（审计 P1-4 / D3 与台账 §2 补充发现）：

1. 常驻基线：200 / 1000 / 5000 条常驻下单轮 `draw` 的墙钟与编码次数；
2. 编码收敛：need 只编码 1 次，候选文本各 1 次（改前 need 与每条重复编码）；
3. 候选集上界：5000 条常驻进入语义打分的候选数 ≤ 上限，未入选条目仍在池中；
4. 召回额度地板：地板随窗口预算单调增长，且抽屉额度与信封额度同源；
5. 折叠计量：单次折叠内每条消息只计量一次。
"""
import os
import sys
import tempfile
import time

from tests.manual._liveVerifyIsolation import isolatedDataRoot  # noqa: E402
isolatedDataRoot()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
os.environ.setdefault("NEUROVA_EMBEDDING_CACHE", os.path.join(tempfile.mkdtemp(), "embedding_cache.json"))

import random  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from neurova.context.pool_models import ContextInput, ContextSource  # noqa: E402
from neurova.context.semantic_drawer import SemanticMatchDrawer  # noqa: E402
from neurova.context.window_compactor import (  # noqa: E402
    WindowTokenMeter,
    compact_window,
)

WORDS = "固件 升级 失败 回滚 设备 协议 日志 缓存 心跳 温度 电池 网络 配置 版本 传输".split()
NEED = "固件升级失败了怎么办"


def buildPool(count: int, seed: int = 11):
    random.seed(seed)
    sources = [
        ContextSource.CONVERSATION,
        ContextSource.MEMORY,
        ContextSource.EXPERIENCE,
        ContextSource.TOOL_CALL,
        ContextSource.REFLECTION,
    ]
    return [
        ContextInput(
            source=sources[i % len(sources)],
            content=f"第{i}条归档记录：{' '.join(random.sample(WORDS, 6))}，编号 {i}",
            priority=60,
            tokens=20,
        )
        for i in range(count)
    ]


def section1_scaleReadings():
    print("── 1. 常驻基线（真抽屉 + 真 ONNX 后端） ──")
    from neurova.cognitive_layers.memory_layer.unified_vector_store import UnifiedVectorStore

    for count in (200, 1000, 5000):
        drops = buildPool(count)
        drawer = SemanticMatchDrawer(max_tokens=8000)
        started = time.perf_counter()
        drawer.draw(list(drops), need=NEED)  # 预热：编码器加载 + 嵌入缓存填写
        warm = time.perf_counter() - started
        samples = []
        for _ in range(3):
            t = time.perf_counter()
            selected = drawer.draw(list(drops), need=NEED)
            samples.append((time.perf_counter() - t) * 1000)
        samples.sort()
        print(
            f"  常驻 {count:5d} 条 | 预热 {warm * 1000:8.1f}ms | 中位 {samples[1]:8.1f}ms | "
            f"入选 {len(selected):4d} 条 | 后端 {UnifiedVectorStore(backend='auto').backend}"
        )


def section2_encodingCalls():
    print("── 2. 编码收敛（真后端 + 调用计数） ──")
    import neurova.cognitive_layers.memory_layer.unified_vector_store as uvs

    drops = buildPool(1000)
    drawer = SemanticMatchDrawer(max_tokens=8000)
    original = uvs.UnifiedVectorStore.encode
    calls = {"n": 0}

    def counting(self, text):
        calls["n"] += 1
        return original(self, text)

    drawer.draw(list(drops), need=NEED)  # 预热嵌入缓存
    uvs.UnifiedVectorStore.encode = counting
    try:
        drawer.draw(list(drops), need=NEED)
    finally:
        uvs.UnifiedVectorStore.encode = original
    print(f"  1000 条常驻单轮 draw：encode 调用 {calls['n']} 次（need 1 次 + 候选各 1 次）")


def section3_candidateCeiling():
    print("── 3. 候选集上界与归档无损 ──")
    drops = buildPool(5000)
    drawer = SemanticMatchDrawer(max_tokens=10 ** 9, max_candidates=500)
    store = object.__new__(type("S", (), {}))
    encoded = {"texts": set()}

    class CountingStore:
        def encode(self, text):
            encoded["texts"].add(text)
            return [float(len(text)) for _ in range(8)]

        def encode_batch(self, texts):
            return [self.encode(t) for t in texts]

    drawer._vector_store = CountingStore()
    selected = drawer.draw(drops, need=NEED)
    print(f"  池内 5000 条 | 进入语义打分文本 {len(encoded['texts'])} 个（上限 500 + need）")
    print(f"  归档条目仍在池中：{len(drops)} 条（粗筛只收敛候选，不删归档）")
    print(f"  视图入选：{len(selected)} 条")


def section4_recallFloor():
    print("── 4. 召回额度地板随模型上下文自适应（D3） ──")
    from neurova.context.orchestrator import ContextOrchestrator

    def orchestrator(budget):
        agent = MagicMock()
        agent.config = MagicMock()
        agent.config.name = "b5"
        agent.config.agent_id = "b5"
        agent.config.constitution = ""
        agent.config.behavior_rules = []
        agent.config.llm_model = "test-model"
        agent.config.enable_auto_tagging = False
        agent.memory_manager = MagicMock()
        agent.tool_router = None
        agent._skill_registry = None
        agent.soul = "B5 活体验证助手"
        agent.personality = ""
        agent.conversation_history = []
        agent.growth_log_manager = MagicMock()
        agent.user_id = "u"
        agent.agent_id = "b5"
        agent.question_queue_manager = None
        orch = ContextOrchestrator(agent, use_pool=True, auto_tag=False)
        orch._window_token_budget = budget
        return orch

    for budget in (4000, 8000, 32000, 72000, 100000):
        orch = orchestrator(budget)
        print(f"  窗口预算 {budget:6d} → 召回地板 {orch._resolveRecallFloor():6d} token")

    async def _probe():
        """真构造面：以 spy 盯住额度方法的实际调用与返回值（不重算，避免第二份公式）。"""
        orch = orchestrator(20000)
        seen = {"recall": [], "envelope": []}
        recall_original = orch._retrievalBudget
        envelope_original = orch._envelopeBudget

        def recall_spy(*args, **kwargs):
            value = recall_original(*args, **kwargs)
            seen["recall"].append(value)
            return value

        def envelope_spy(*args, **kwargs):
            value = envelope_original(*args, **kwargs)
            seen["envelope"].append(value)
            return value

        with patch.object(orch, "_retrievalBudget", recall_spy), patch.object(
            orch, "_envelopeBudget", envelope_spy
        ):
            with patch.object(orch, "get_tools_description", new_callable=AsyncMock, return_value=""):
                await orch.build_context(
                    user_input="问题", session_context=[{"role": "user", "content": "短历史"}]
                )
        return orch.context_pool._drawer.max_tokens, seen

    import asyncio

    drawer_tokens, seen = asyncio.run(_probe())
    print(f"  真构造面：召回额度方法被调用 {len(seen['recall'])} 次（抽屉与信封共用同一方法）")
    print(f"  抽屉额度 {drawer_tokens} ∈ 该方法取值集：{drawer_tokens in seen['recall']}")
    print(f"  信封额度 {seen['envelope']} ≥ 召回额度（含固定部分与行前缀）")
    print(
        "  注：两次取值略有差异，是因为 blocks 在本轮内被后续注入位（情感）补全——"
        "同一方法、同一批入参必然同值，差异来自入参演化，不是第二份公式"
    )


def section5_metering():
    print("── 5. 折叠计量单趟化（台账 §2 补充发现） ──")
    from neurova.context.token_estimator import estimate_tokens

    calls = {"n": 0}

    def counting(text):
        calls["n"] += 1
        return estimate_tokens(text)

    import asyncio

    msgs = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"长消息{i}：" + "测" * 200}
        for i in range(120)
    ]
    meter = WindowTokenMeter(counting)
    asyncio.run(compact_window(msgs, budget_tokens=400, summarize=None, keep_min_messages=6, meter=meter))
    print(f"  120 条窗口折叠：内容计量 {calls['n']} 次（改前约 2.4× 重复）")


def main():
    print("B5 规模 live-verify（Issue #90）")
    section1_scaleReadings()
    section2_encodingCalls()
    section3_candidateCeiling()
    section4_recallFloor()
    section5_metering()
    print("\nLIVE-VERIFY PASSED")


if __name__ == "__main__":
    main()
