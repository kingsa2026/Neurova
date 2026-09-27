# -*- coding: utf-8 -*-
"""live-verify（Issue #90 · B6-11 / 决策 D5）：反思「进视图才记账」+ 未进视图降档兜底。

链路：真 `GrowthLogManager`（真 `MemoryManager` 临时库）→ 真 `ContextOrchestrator.build_context`
（真归档 → 真池 draw → 真信封压缩 → 真装配出口记账）→ 真 `core.turn_context` 痕迹面
→ 真 `get_context_health()["reflection_injection"]` → 真 `/metrics` 抓取路径。

判据（六条都要过）：
1. **未进视图不记账**：无关输入下条目仍在 `pending`，痕迹为空（改前：applied + 痕迹有 id）；
2. **进了视图照旧记账**：相关输入下条目转 `applied`、痕迹含该 id；
3. **压缩淘汰也算没进视图**：信封额度不足把 `<history>` 整块丢掉时，不记 applied；
4. **降档兜底**：连续 `VIEW_MISS_LIMIT` 轮未进视图 → 置信度下降且条目仍在（只降不删）；
5. **进视图清零连击**：偶发命中后重新起算，不被算成"从不命中"；
6. **读数与抓取**：`selected/entered_view/missed/demoted` 可判读，且真进 `/metrics`。

跑法：`PYTHONPATH=. python tests/manual/reflection_view_accounting_b6_11.py`
"""

from __future__ import annotations

import asyncio
import os
import tempfile

os.environ.setdefault("NEUROVA_DATA_DIR", tempfile.mkdtemp(prefix="neurovaB611Live_"))

from unittest.mock import MagicMock  # noqa: E402

from prometheus_client import REGISTRY  # noqa: E402

from neurova.cognitive_layers.memory_layer.manager import MemoryManager  # noqa: E402
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (  # noqa: E402
    GrowthLogManager,
    ReflectionLogStatus,
    ReflectionType,
)
from neurova.context.orchestrator import ContextOrchestrator  # noqa: E402
from neurova.context.reflection_view import VIEW_MISS_LIMIT  # noqa: E402
from neurova.core.turn_context import get_turn_injected_reflections  # noqa: E402

LESSON = "固件升级前必须先备份配置"
TITLE = "固件升级"


def _agent(glog, agentId: str = "a-live-b611"):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.show_empathy = True
    agent.config.agent_id = agentId
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = glog
    agent.user_id = "u1"
    agent.agent_id = agentId
    return agent


def _growthLog(dataDir: str, agentId: str) -> GrowthLogManager:
    manager = MemoryManager(
        db_path=os.path.join(dataDir, "eff.db"), agent_id=agentId, user_id="u1"
    )
    return GrowthLogManager(memory_manager=manager)


def _viewText(messages, userInput: str = "", history=None) -> str:
    """注入面文本：走生产那处判定，并把本轮对话原文一并喂进去。

    `authored` 不可省 —— 信封被整封弃掉时末条消息退化成裸用户输入，不刨原文
    就会把"用户自己提过这句"算成"教训进过视图"（本片修的那条判定）。
    """
    from neurova.context.reflection_view import authoredTexts, injectionSurface

    return injectionSurface(messages, authoredTexts(userInput, history))


async def main() -> None:
    dataDir = tempfile.mkdtemp(prefix="neurovaB611LiveData_")
    glog = _growthLog(dataDir, "a-live-b611")
    entry = await glog.generate_log(
        type=ReflectionType.ERROR,
        title=TITLE,
        content="正文",
        insights=[LESSON],
        confidence=0.6,
    )
    orch = ContextOrchestrator(
        _agent(glog), use_pool=True, auto_tag=False, session_id="sess-live-b611"
    )
    history = [{"role": "user", "content": f"第{i}轮闲聊"} for i in range(3)]

    async def build(userInput: str):
        msgs = await orch.build_context(
            user_input=userInput, session_context=history, relevant_memories=[]
        )
        return msgs, get_turn_injected_reflections()

    # [1] 未进视图不记账
    msgs, trace = await build("今天天气怎么样")
    in_view = LESSON in _viewText(msgs, "今天天气怎么样", history)
    readout = orch.get_context_health()["reflection_injection"]
    print(
        f"[1 未进视图] 视图含教训={in_view} 状态={glog._cache[entry.id].status.value} "
        f"痕迹={trace} 读数=selected {readout['selected']}/entered {readout['entered_view']}/"
        f"missed {readout['missed']}"
    )
    assert not in_view, "前置条件：无关输入不该把该教训召回进视图"
    assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING, "未进视图不得记 applied"
    assert not trace, "未进视图不得进痕迹"
    assert (readout["selected"], readout["entered_view"], readout["missed"]) == (1, 0, 1), readout

    # [2] 进了视图照旧记账
    msgs, trace = await build(f"{LESSON}吗")
    readout = orch.get_context_health()["reflection_injection"]
    print(
        f"[2 进视图] 视图含教训={LESSON in _viewText(msgs, f'{LESSON}吗', history)} "
        f"状态={glog._cache[entry.id].status.value} 痕迹={trace} "
        f"读数=selected {readout['selected']}/entered {readout['entered_view']}/missed {readout['missed']}"
    )
    assert LESSON in _viewText(msgs, f"{LESSON}吗", history), "前置条件：相关输入应召回该教训"
    assert glog._cache[entry.id].status == ReflectionLogStatus.APPLIED
    assert trace == [entry.id]
    assert (readout["selected"], readout["entered_view"], readout["missed"]) == (1, 1, 0), readout

    # [3] 压缩淘汰也算没进视图
    entry2 = await glog.generate_log(
        type=ReflectionType.ERROR, title="另一条", content="正文乙",
        insights=["另一条教训：先复述需求"], confidence=0.6,
    )
    # 额度取固定部分（免疫句壳 + `<time>`）的复算值：硬编码常数会在跨日历边界
    # 失效（`<time>` 随"临近节日"多一行，一旦常数低于固定部分，弃掉的是整封，
    # 被测形态根本没发生）。
    orch._envelopeBudget = lambda *a, **k: orch._envelopeFixedTokens({})  # noqa: SLF001 - 判据打在真正落地那一步
    msgs, trace = await build("另一条教训要不要用")
    from neurova.context.envelope import parse_envelope

    blocks = parse_envelope(str(msgs[-1].get("content", "")))
    dropped = "先复述需求" not in _viewText(msgs, "另一条教训要不要用", history)
    print(
        f"[3 压缩淘汰] 信封在场={bool(blocks)} history 块被丢={'history' not in blocks} "
        f"教训不在注入面={dropped} 状态={glog._cache[entry2.id].status.value} 痕迹={trace}"
    )
    assert blocks, "前置条件：壳 + `<time>` 装得下 ⇒ 信封在场"
    assert "history" not in blocks, "前置条件：预算不足时 history 块应被整块淘汰"
    assert dropped, "被淘汰的块里的文本不该出现在注入面"
    assert glog._cache[entry2.id].status == ReflectionLogStatus.PENDING, "被淘汰等于没进视图"
    del orch._envelopeBudget

    # [4] 降档兜底
    orch2 = ContextOrchestrator(
        _agent(glog, "a-live-b611-2"), use_pool=True, auto_tag=False, session_id="sess-live-b611-2"
    )

    async def build2(userInput: str):
        return await orch2.build_context(
            user_input=userInput, session_context=history, relevant_memories=[]
        )

    before = glog._cache[entry2.id].confidence
    for _ in range(VIEW_MISS_LIMIT):
        await build2("今天天气怎么样")
    after = glog._cache[entry2.id].confidence
    readout = orch2.get_context_health()["reflection_injection"]
    print(
        f"[4 降档兜底] {VIEW_MISS_LIMIT} 轮未进视图 置信度 {before:.2f}→{after:.2f} "
        f"条目仍在={entry2.id in glog._cache} demoted={readout['demoted']}"
    )
    assert after < before, "连续未进视图必须降档（低相关教训的退出路径）"
    assert entry2.id in glog._cache, "只降不删"
    assert readout["demoted"] >= 1

    # [5] 进视图清零连击
    orch3 = ContextOrchestrator(
        _agent(glog, "a-live-b611-3"), use_pool=True, auto_tag=False, session_id="sess-live-b611-3"
    )
    entry3 = await glog.generate_log(
        type=ReflectionType.ERROR, title="第三条", content="正文丙",
        insights=["第三条教训：先复述确认关注点"], confidence=0.6,
    )

    async def build3(userInput: str):
        return await orch3.build_context(
            user_input=userInput, session_context=history, relevant_memories=[]
        )

    confBefore = glog._cache[entry3.id].confidence
    for _ in range(VIEW_MISS_LIMIT - 1):
        await build3("今天天气怎么样")
    await build3("第三条教训：先复述确认关注点 要不要用")  # 真进视图 → 清零
    for _ in range(VIEW_MISS_LIMIT - 1):
        await build3("今天天气怎么样")
    confAfter = glog._cache[entry3.id].confidence
    print(f"[5 连击清零] 置信度 {confBefore:.2f} → {confAfter:.2f}（偶发命中不算从不命中）")
    assert confAfter == confBefore, "进视图须把连击清零"

    # [6] 真进 /metrics 抓取面
    from neurova.core.metrics import get_metrics

    state = MagicMock()
    state.agents = {"a-live-b611": MagicMock(context_orchestrator=orch)}
    get_metrics().observe_context_health(state)
    samples = [
        s for m in REGISTRY.collect() for s in m.samples
        if s.name == "neurova_context_health_value" and s.labels.get("kind") == "reflection_injection"
    ]
    fields = sorted({s.labels["field"] for s in samples})
    print(f"[6 抓取] reflection_injection 序列数={len(samples)} 字段={fields}")
    assert {"selected", "entered_view", "missed", "demoted"} <= set(fields), fields

    print("LIVE-VERIFY PASSED")


if __name__ == "__main__":
    asyncio.run(main())
