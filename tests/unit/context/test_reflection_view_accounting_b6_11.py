# -*- coding: utf-8 -*-
"""B6-11：反思效力记账改「进视图才记账」+ 未进视图降档兜底（Issue #90 · 决策 D5）。

## 根因（不是"少传一个参数"）

`mark_injected_logs` 在**选中那一刻**就被调用（与 `select_reflection_logs` 同一段），
于是"账目"与"视图"之间没有任何因果：

- 反思条目归档进池的优先级是 60（低于记忆 70、经验等），能否进视图要过
  `SemanticPool.draw` 的相关性门槛；
- 实测（真 `build_context`，无关输入 "今天天气怎么样"）：
  `status=applied`、`trace=['8ab03764-…']`，而**视图里一行 `[反思]` 都没有**。

后果是二重的：① `applied` 这件事被谎报（工单 §10.3 D5："未进视图的反思不再计入
applied"）；② 效力裁决的输入（`injected_reflections` 落进 assistant metadata →
`/chat/feedback` 的 like→validated / dislike→降置信）基于**幻影注入**，用户对一个
从未见过的教训投票（审计 §2.1 P2-9）。

## 本票契约（D5 两条）

1. **进视图才记账**：`applied` 与本轮痕迹只给**真的出现在视图注入面**里的条目。
   "进视图"必须是客观判据，且要覆盖"被 draw 取出、随后被 `compress_envelope`
   整块淘汰"这一形态 —— 故判据取**视图注入面里有没有这条的文本**（`parse_envelope`
   客观解析信封块，用户原文不算注入面）。
2. **降档兜底**：连续 `VIEW_MISS_LIMIT` 轮被选中却从未进视图的条目，走既有降档
   单一事实源 `register_negative_feedback`（只降不删）——否则低相关教训永不生效
   且没有退出路径（审计 §10 D5）。降到 rejected 即脱离恒定注入，池内原文仍在
   （无损归档语义不变）。

## 判据测的是视图，不是分支

最后一条用例走**非池降级分支**（`context_builder is None`）：那里反思确实以独立
消息进了视图，判据必须同样成立 —— 判定规则只有一条（"视图注入面里有没有这条文本"），
不按分支各写一份。
"""

from __future__ import annotations

import asyncio
import os

from unittest.mock import MagicMock

import pytest

from neurova.cognitive_layers.memory_layer.manager import MemoryManager
from neurova.cognitive_layers.meta_cognition_layer.growth_log import (
    GrowthLogManager,
    ReflectionLogStatus,
    ReflectionType,
)
from neurova.core.turn_context import get_turn_injected_reflections

LESSON = "固件升级前必须先备份配置"
TITLE = "固件升级"


@pytest.fixture(autouse=True)
def _isolatedDataRoot(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROVA_DATA_DIR", str(tmp_path / "data"))
    yield


def _growthLog(tmp_path, agentId: str = "a-b611") -> GrowthLogManager:
    manager = MemoryManager(
        db_path=str(tmp_path / "eff.db"), agent_id=agentId, user_id="u1"
    )
    return GrowthLogManager(memory_manager=manager)


def _agent(glog, tmp_path):
    agent = MagicMock()
    agent.config = MagicMock()
    agent.config.name = "t"
    agent.config.constitution = ""
    agent.config.behavior_rules = []
    agent.config.llm_model = "test-model"
    agent.config.show_empathy = True
    agent.config.agent_id = "a-b611"
    agent.memory_manager = MagicMock()
    agent.context_builder = MagicMock()
    agent.tool_router = None
    agent._skill_registry = None
    agent.soul = "测试助手"
    agent.personality = ""
    agent.conversation_history = []
    agent.growth_log_manager = glog
    agent.user_id = "u1"
    agent.agent_id = "a-b611"
    return agent


def _orchestrator(glog, *, use_pool: bool = True, agent=None):
    from neurova.context.orchestrator import ContextOrchestrator

    orch = ContextOrchestrator(
        agent if agent is not None else _agent(glog, None),
        use_pool=use_pool,
        auto_tag=False,
        session_id="sess-b611",
    )
    return orch


async def _lesson(glog, *, lesson: str = LESSON, title: str = TITLE, confidence: float = 0.6):
    return await glog.generate_log(
        type=ReflectionType.ERROR,
        title=title,
        content="正文",
        insights=[lesson],
        confidence=confidence,
    )


def _history(rounds: int = 3):
    return [{"role": "user", "content": f"第{i}轮闲聊"} for i in range(rounds)]


async def _build(orch, user_input: str):
    msgs = await orch.build_context(
        user_input=user_input, session_context=_history(), relevant_memories=[]
    )
    return msgs, get_turn_injected_reflections()


def _injectionText(msgs) -> str:
    """本轮视图的注入面文本（信封块 + 非信封消息正文）。"""
    from neurova.context.envelope import parse_envelope

    parts = []
    for msg in msgs or []:
        content = str((msg or {}).get("content", "") or "")
        blocks = parse_envelope(content)
        parts.append("\n".join(blocks.values()) if blocks else content)
    return "\n".join(parts)


class TestViewEntryDecidesAccounting:
    """D5 判据 1：`applied` 与痕迹只给真进视图的条目。"""

    @pytest.mark.asyncio
    async def test_reflection_absent_from_view_is_not_marked_applied(self, tmp_path):
        """无关输入 → 条目没进视图 → 不得记 applied、不得进本轮痕迹。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)

        msgs, trace = await _build(orch, "今天天气怎么样")

        assert LESSON not in _injectionText(msgs), "前置条件：无关输入下该教训本就不该进视图"
        assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING, (
            "条目没进视图却被记为 applied —— 这正是 P2-9 的幻影注入"
        )
        assert not trace, f"没进视图的条目不得进本轮痕迹（权威裁决输入），实得 {trace!r}"

    @pytest.mark.asyncio
    async def test_reflection_present_in_view_is_marked_applied_and_traced(self, tmp_path):
        """进了视图 → 仍然照旧记 applied + 痕迹（语义变更不得把真注入一起丢掉）。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)

        msgs, trace = await _build(orch, f"{LESSON}吗")

        assert LESSON in _injectionText(msgs), "前置条件：相关输入应把该教训召回进视图"
        assert glog._cache[entry.id].status == ReflectionLogStatus.APPLIED
        assert trace == [entry.id], f"真进视图的条目必须在痕迹里，实得 {trace!r}"

    @pytest.mark.asyncio
    async def test_drawn_then_envelope_dropped_is_not_marked_applied(self, tmp_path):
        """被 draw 取出、随后被信封压缩整块淘汰 → 仍算没进视图。

        判据取视图注入面而不是 draw 的输出集合：`compress_envelope` 超预算时会把
        `<history>` 整块丢掉（`COMPRESS_DROP_ORDER`），那时条目确实没到模型面前。
        """
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        orch = _orchestrator(glog)
        # 把信封额度压到装不下 history 块：draw 照旧命中，落地被淘汰。
        orch._envelopeBudget = lambda *a, **k: 120  # noqa: SLF001 - 判据要打在真正落地的那一步

        msgs, trace = await _build(orch, f"{LESSON}吗")

        assert LESSON not in _injectionText(msgs), "前置条件：预算不足时 history 块应被整块淘汰"
        assert glog._cache[entry.id].status == ReflectionLogStatus.PENDING
        assert not trace


class TestMissFallbackDemotes:
    """D5 判据 2：连续未进视图走既有降档单一事实源（只降不删）。"""

    @pytest.mark.asyncio
    async def test_consecutive_misses_demote_confidence(self, tmp_path):
        from neurova.context.reflection_view import VIEW_MISS_LIMIT

        glog = _growthLog(tmp_path)
        entry = await _lesson(glog, confidence=0.6)
        orch = _orchestrator(glog)

        for _ in range(VIEW_MISS_LIMIT):
            await _build(orch, "今天天气怎么样")

        assert glog._cache[entry.id].confidence < 0.6, (
            f"{VIEW_MISS_LIMIT} 轮未进视图仍未降档 —— 低相关教训没有退出路径"
        )
        assert entry.id in glog._cache, "降档只降不删：原文仍在（无损归档语义）"
        assert orch.get_context_health()["reflection_injection"]["demoted"] >= 1

    @pytest.mark.asyncio
    async def test_entering_view_resets_miss_streak(self, tmp_path):
        from neurova.context.reflection_view import VIEW_MISS_LIMIT

        glog = _growthLog(tmp_path)
        entry = await _lesson(glog, confidence=0.6)
        orch = _orchestrator(glog)

        for _ in range(VIEW_MISS_LIMIT - 1):
            await _build(orch, "今天天气怎么样")
        await _build(orch, f"{LESSON}吗")  # 这一轮真进了视图
        for _ in range(VIEW_MISS_LIMIT - 1):
            await _build(orch, "今天天气怎么样")

        assert glog._cache[entry.id].confidence == pytest.approx(0.6), (
            "进视图的那轮必须把连击清零，否则'偶发命中'与'从不命中'被算成同一件事"
        )


class TestReadout:
    """可观测：选中 / 进视图 / 未进视图 / 降档四个数必须可判读。"""

    @pytest.mark.asyncio
    async def test_readout_reports_selected_entered_and_missed(self, tmp_path):
        glog = _growthLog(tmp_path)
        await _lesson(glog)
        orch = _orchestrator(glog)

        await _build(orch, "今天天气怎么样")
        missed = orch.get_context_health()["reflection_injection"]
        assert missed["selected"] == 1, missed
        assert missed["entered_view"] == 0, missed
        assert missed["missed"] == 1, missed

        await _build(orch, f"{LESSON}吗")
        entered = orch.get_context_health()["reflection_injection"]
        assert entered["selected"] == 1, entered
        assert entered["entered_view"] == 1, entered
        assert entered["missed"] == 0, entered


class TestJudgmentFollowsTheViewNotTheBranch:
    """判定规则只有一条：视图注入面里有没有这条文本（不按分支各写一份）。"""

    @pytest.mark.asyncio
    async def test_degraded_branch_view_entry_is_accounted(self, tmp_path):
        """非池降级分支（`context_builder is None`）里反思以独立消息进了视图 → 照旧记账。"""
        glog = _growthLog(tmp_path)
        entry = await _lesson(glog)
        agent = _agent(glog, tmp_path)
        agent.context_builder = None  # 触发降级装配
        agent.use_pool = False
        orch = _orchestrator(glog, use_pool=False, agent=agent)

        msgs, trace = await _build(orch, "随便问点什么")

        assert LESSON in _injectionText(msgs), "前置条件：降级分支把反思以独立消息注入视图"
        assert glog._cache[entry.id].status == ReflectionLogStatus.APPLIED
        assert trace == [entry.id]
